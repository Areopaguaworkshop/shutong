#!/usr/bin/env python3
"""
ingest_all.py — Batch ingest a folder of academic PDFs via citeindex
with resume, duplicate detection, and interactive dedup.

Usage:
  python ingest_all.py [options] [FOLDER]

Options:
  --corpus-root DIR   Corpus output directory (default: ./corpus)
  --resume            Skip files already in corpus (default: True)
  --re-ingest         Re-ingest all files, even already-ingested ones
  --dry-run           Show what would be ingested, don't run citeindex
  --batch {digital,scanned,all}
                       Which batch to process (default: all)
  --page-range RANGE  Page range for citeindex (default: all)
  --ocr-engine ENGINE OCR engine: mineru or glm-ocr (default: mineru)
  --llm MODEL         LLM model for citation extraction
  --verbose           Show citeindex verbose output
  --quiet             Suppress citeindex debug output
  --parallel N        Run up to N ingestions in parallel (default: 1)

Examples:
  # First run: interactively resolve duplicates, then ingest digital first
  python ingest_all.py ./example

  # Resume (skip already-ingested), only scanned batch
  python ingest_all.py --batch scanned --resume

  # Re-ingest everything, force OCR
  python ingest_all.py --re-ingest --force-ocr
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_EXTS = {".pdf", ".PDF", ".docx", ".doc", ".rtf", ".odt", ".djvu", ".epub"}

# Known duplicate groups: each tuple lists files that are likely the same work.
# The script will ask the user which to keep.
DUPLICATE_CANDIDATES: list[list[str]] = [
    [
        "Daoism-Handbook.pdf",
        "Daoism Handbook.pdf",
    ],
    [
        "Pregadio-2024-Dictionary_of_Taoist_Internal_Alchemy.pdf",
        "Pregadio-2024-Dictionary of Taoist Internal Alchemy.pdf",
    ],
    [
        "Pregadio-2020-Man-Bird Mountain.pdf",
        "Pregadio2-2021-MAN-BIRD MOUNTAIN.pdf",
    ],
    [
        "Pregadio_2009_悟真篇英译.pdf",
        "悟真篇-Pregodio-en.pdf",
    ],
    [
        "Bokenkamp-Early Daoist Scriptures.pdf",
        "early-Daoist-Scriptures-t.pdf",
    ],
    [
        "Encyclopedia_of_Taoism.pdf",
        "道教百科.PDF",
    ],
    [
        "庄子集释[清]郭庆藩（全四册） (庄子集释[清]郭庆藩（全四册）).pdf",
        "Guo-qingfan-庄子集释 (郭庆藩).pdf",
    ],
]

# Files known to be problematic
KNOWN_PROBLEMS: dict[str, str] = {
    # Add any future problematic files here as "filename": "reason"
}

# Files explicitly excluded from corpus ingestion.
EXCLUDED_FILES: dict[str, str] = {
    "Guo-qingfan-庄子集释 (郭庆藩).pdf": "Excluded by ingest_all.py: user requested not to ingest",
    "帛书老子校注（中华书局） (高明, 老子).pdf": "Excluded by ingest_all.py: user requested not to ingest",
    "庄子集释[清]郭庆藩（全四册） (庄子集释[清]郭庆藩（全四册）).pdf": "Excluded by ingest_all.py: user requested not to ingest",
    "老子今注今译 参照简帛本最新修订版 (陈鼓应注译).pdf": "Excluded by ingest_all.py: user requested not to ingest",
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    path: Path
    size_mb: float
    pages: int
    pdf_kind: str  # "digital", "scanned", "epub_converted", "office", "unknown"
    avg_text_per_page: float = 0.0
    doc_type_hint: str = ""  # "book", "thesis", "journal", "bookchapter", ""
    skip_reason: str = ""


@dataclass
class IngestResult:
    filepath: Path
    success: bool
    source_id: str = ""
    csl_id: str = ""
    resource_type: str = ""
    error: str = ""
    duration_sec: float = 0.0


@dataclass
class CorpusState:
    ingested_files: dict[str, dict] = field(default_factory=dict)  # input_path -> {csl_id, resource_type, merkle_root, timestamp}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def classify_pdf(path: Path) -> tuple[int, str, float]:
    """Return (pages, kind, avg_text_per_page) for a PDF."""
    try:
        import fitz
        doc = fitz.open(str(path))
        pages = doc.page_count
        sample = min(5, pages) if pages > 0 else 1
        total_chars = 0
        for i in range(sample):
            try:
                total_chars += len(doc[i].get_text())
            except Exception:
                pass
        doc.close()
        avg_txt = total_chars / sample if sample > 0 else 0
        kind = "digital" if avg_txt > 100 else "scanned"
        return pages, kind, avg_txt
    except Exception as e:
        return 0, "unknown", 0.0


def scan_folder(folder: Path, skip_set: set[str]) -> list[FileInfo]:
    """Scan folder and classify all supported files."""
    results = []
    seen_paths: set[str] = set()  # resolved paths already added (avoids epub->docx dup)

    # Pre-scan: find epub files that have been converted to docx
    epub_docx_paths: set[str] = set()
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() == ".epub":
            docx_path = f.with_suffix(".docx")
            if docx_path.exists():
                epub_docx_paths.add(str(docx_path.resolve()))

    for f in sorted(folder.iterdir()):
        if not f.is_file():
            continue
        resolved = str(f.resolve())

        if resolved in seen_paths:
            continue

        if f.name in skip_set or str(f) in skip_set:
            results.append(FileInfo(
                path=f, size_mb=0, pages=0, pdf_kind="skipped",
                skip_reason="User chose to skip (duplicate)"
            ))
            seen_paths.add(resolved)
            continue
        if f.name in EXCLUDED_FILES:
            results.append(FileInfo(
                path=f, size_mb=f.stat().st_size / (1024*1024),
                pages=0, pdf_kind="excluded",
                skip_reason=EXCLUDED_FILES[f.name]
            ))
            seen_paths.add(resolved)
            continue
        if f.name in KNOWN_PROBLEMS:
            results.append(FileInfo(
                path=f, size_mb=f.stat().st_size / (1024*1024),
                pages=0, pdf_kind="problem",
                skip_reason=KNOWN_PROBLEMS[f.name]
            ))
            seen_paths.add(resolved)
            continue

        ext = f.suffix.lower()
        if ext == ".epub":
            # Use the converted docx instead
            docx_path = f.with_suffix(".docx")
            if docx_path.exists():
                docx_resolved = str(docx_path.resolve())
                if docx_resolved not in seen_paths:
                    sz = docx_path.stat().st_size / (1024*1024)
                    results.append(FileInfo(
                        path=docx_path, size_mb=sz, pages=0, pdf_kind="office",
                        doc_type_hint="book", skip_reason=""
                    ))
                    seen_paths.add(docx_resolved)
            else:
                results.append(FileInfo(
                    path=f, size_mb=f.stat().st_size / (1024*1024),
                    pages=0, pdf_kind="epub",
                    skip_reason="Unsupported .epub format — convert to .docx first: pandoc FILE.epub -o FILE.docx"
                ))
                seen_paths.add(resolved)
            continue

        # Skip docx files that are just converted epubs (already handled above)
        if resolved in epub_docx_paths and resolved in seen_paths:
            continue

        if ext in {".docx", ".doc", ".rtf", ".odt"}:
            results.append(FileInfo(
                path=f, size_mb=f.stat().st_size / (1024*1024),
                pages=0, pdf_kind="office", doc_type_hint=""
            ))
            seen_paths.add(resolved)
            continue

        if ext in {".pdf", ".PDF"} or ext == "":
            if ext == "" and ".PDF" in f.name:
                ext = ".PDF"
            if ext not in {".pdf", ".PDF"}:
                continue
            sz = f.stat().st_size / (1024*1024)
            pages, kind, avg_txt = classify_pdf(f)
            dtype = ""
            # Heuristic doc type from filename
            name_lower = f.name.lower()
            if any(kw in name_lower for kw in ["thesis", "dissertation", "论文"]):
                dtype = "thesis"
            elif any(kw in name_lower for kw in ["handbook", "encyclopedia", "百科", "集释", "导引"]):
                dtype = "book"
            elif any(kw in name_lower for kw in ["journal", "journal "]):
                dtype = "journal"
            results.append(FileInfo(
                path=f, size_mb=sz, pages=pages, pdf_kind=kind,
                avg_text_per_page=avg_txt, doc_type_hint=dtype
            ))
            continue

    return results


def load_corpus_state(corpus_root: Path) -> CorpusState:
    """Load existing corpus state from ingestion_log.jsonl."""
    state = CorpusState()
    log_path = corpus_root / "ingestion_log.jsonl"
    if not log_path.exists():
        return state
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                state.ingested_files[entry.get("input_ref", "")] = {
                    "csl_id": entry.get("csl_id", ""),
                    "resource_type": entry.get("resource_type", ""),
                    "merkle_root": entry.get("merkle_root", ""),
                    "timestamp": entry.get("ingestion_timestamp", ""),
                }
            except json.JSONDecodeError:
                continue
    return state


def file_already_ingested(filepath: Path, corpus_state: CorpusState) -> bool:
    """Check if a file has already been successfully ingested."""
    key = str(filepath)
    return key in corpus_state.ingested_files


# ---------------------------------------------------------------------------
# Interactive dedup
# ---------------------------------------------------------------------------

def _pick_best_in_group(infos: list[dict]) -> int:
    """Auto-pick best file in a duplicate group.
    
    Priority: digital > scanned; then most pages; then largest size.
    Penalize files with suspiciously small size relative to others (likely partial/corrupt).
    """
    if len(infos) <= 1:
        return 0

    # Flag files that are < 20% of the max size in group (likely partial/preview)
    max_size = max(i["size_mb"] for i in infos)

    def score(info):
        # Base: digital=2, scanned=1, unknown=0
        kind_score = {"digital": 2, "scanned": 1, "office": 2, "unknown": 0}.get(info["kind"], 0)
        page_score = info["pages"]  # more pages = more complete
        size_penalty = -10 if (max_size > 1 and info["size_mb"] < max_size * 0.2) else 0
        return (kind_score, size_penalty, page_score, info["size_mb"])

    best_idx = max(range(len(infos)), key=lambda i: score(infos[i]))
    return best_idx


def resolve_duplicates(
    folder: Path,
    no_interactive: bool = False,
    dedup_choices_file: Optional[Path] = None,
    corpus_root: Optional[Path] = None,
) -> tuple[set[str], dict[str, str]]:
    """
    Resolve duplicate file groups.
    
    Returns:
        skip_set: set of filenames to skip
        choices: dict mapping group_id -> kept filename (for saving)
    
    Modes:
        - Interactive (default): ask user which to keep
        - --no-interactive: auto-pick best (digital > scanned, largest)
        - --dedup-choices FILE: load/save pre-answered choices from JSON
    """
    skip_set: set[str] = set()
    choices: dict[str, str] = {}

    # Load pre-answered choices if provided
    pre_choices: dict[str, str] = {}
    if dedup_choices_file and dedup_choices_file.exists():
        with open(dedup_choices_file) as f:
            pre_choices = json.load(f)

    existing_files = {f.name for f in folder.iterdir() if f.is_file()}

    # Load corpus state to check already-ingested files
    corpus_log = corpus_root / "ingestion_log.jsonl" if corpus_root else None
    already_ingested_names: set[str] = set()
    if corpus_log and Path(corpus_log).exists():
        with open(corpus_log) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    p = Path(entry.get("input_ref", ""))
                    already_ingested_names.add(p.name)
                except Exception:
                    pass

    for group in DUPLICATE_CANDIDATES:
        # Only resolve if at least 2 files from the group actually exist
        present = [name for name in group if name in existing_files]
        if len(present) < 2:
            continue

        # If any member is already ingested, skip the un-ingested ones (they're extras)
        already_in_group = [n for n in present if n in already_ingested_names]
        if already_in_group:
            for n in present:
                if n not in already_ingested_names:
                    skip_set.add(n)
                    print(f"  Dedup [skip]: '{n}' — duplicate of already-ingested '{already_in_group[0]}'")
            continue

        # Group ID = sorted tuple of filenames for stable key
        group_id = " | ".join(sorted(present))

        # Gather info for each file
        infos = []
        for name in present:
            fp = folder / name
            sz = fp.stat().st_size / (1024*1024)
            pages, kind, avg_txt = 0, "unknown", 0.0
            if name.lower().endswith((".pdf", ".pdf")):
                pages, kind, avg_txt = classify_pdf(fp)
            infos.append({
                "name": name,
                "size_mb": sz,
                "pages": pages,
                "kind": kind,
                "avg_text": avg_txt,
            })

        # Check pre-answered choices
        if group_id in pre_choices:
            kept_name = pre_choices[group_id]
            if kept_name == "__ALL__":
                print(f"  Dedup [pre-answered]: Keep ALL in group: {group_id}")
                choices[group_id] = "__ALL__"
                continue
            elif kept_name == "__NONE__":
                for info in infos:
                    skip_set.add(info["name"])
                print(f"  Dedup [pre-answered]: Skip ALL in group: {group_id}")
                choices[group_id] = "__NONE__"
                continue
            else:
                for info in infos:
                    if info["name"] != kept_name:
                        skip_set.add(info["name"])
                print(f"  Dedup [pre-answered]: Keep '{kept_name}' in group: {group_id}")
                choices[group_id] = kept_name
                continue

        # Auto-pick if non-interactive
        if no_interactive or not sys.stdin.isatty():
            best_idx = _pick_best_in_group(infos)
            kept_name = infos[best_idx]["name"]
            for idx, info in enumerate(infos):
                if idx != best_idx:
                    skip_set.add(info["name"])
            print(f"  Dedup [auto]: Keep '{kept_name}' in group with {len(infos)} files")
            choices[group_id] = kept_name
            continue

        # Interactive
        print(f"\n{'='*60}")
        print(f"Duplicate group detected:")
        print(f"{'='*60}")

        for i, info in enumerate(infos):
            tag = ""
            if info["kind"] == "digital":
                tag = "[DIGITAL]"
            elif info["kind"] == "scanned":
                tag = "[SCANNED]"
            print(f"  [{i+1}] {info['size_mb']:7.1f} MB  {info['pages']:>5} pg  {tag:10}  {info['name']}")

        # Suggest the best pick
        best_idx = _pick_best_in_group(infos)
        print(f"\n  Suggested: [{best_idx+1}] {infos[best_idx]['name']}")
        print(f"  [a] Keep ALL (ingest every copy)")
        print(f"  [s] Skip ALL (none of these)")
        print(f"  [Enter] Accept suggestion")

        while True:
            choice = input("  Which to KEEP? (number(s), 'a', 's', Enter=suggest): ").strip().lower()
            if choice == '':
                # Accept suggestion
                kept_name = infos[best_idx]["name"]
                for idx, info in enumerate(infos):
                    if idx != best_idx:
                        skip_set.add(info["name"])
                choices[group_id] = kept_name
                break
            elif choice == 'a':
                choices[group_id] = "__ALL__"
                break
            elif choice == 's':
                for info in infos:
                    skip_set.add(info["name"])
                choices[group_id] = "__NONE__"
                break
            else:
                try:
                    indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip()]
                    if all(0 <= idx < len(infos) for idx in indices):
                        if len(indices) == 1:
                            kept_name = infos[indices[0]]["name"]
                            choices[group_id] = kept_name
                        else:
                            choices[group_id] = "__ALL__"
                        kept_indices = set(indices)
                        for idx, info in enumerate(infos):
                            if idx not in kept_indices:
                                skip_set.add(info["name"])
                        break
                    else:
                        print("  Invalid selection, try again.")
                except (ValueError, IndexError):
                    print("  Invalid input, enter number(s) like '1' or '1,3'")

    # Save choices for future runs
    if dedup_choices_file:
        with open(dedup_choices_file, "w") as f:
            json.dump(choices, f, indent=2, ensure_ascii=False)
        print(f"\n  Dedup choices saved to: {dedup_choices_file}")

    return skip_set, choices


# ---------------------------------------------------------------------------
# Ingest execution
# ---------------------------------------------------------------------------

def build_citeindex_cmd(
    filepath: Path,
    corpus_root: Path,
    page_range: str = "all",
    ocr_engine: str = "mineru",
    llm: str = "",
    doc_type: str = "",
    force_ocr: bool = False,
    force_digital: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    no_pageindex: bool = False,
) -> list[str]:
    """Build the citeindex CLI command."""
    citeindex_bin = _find_citeindex()
    cmd = [str(citeindex_bin), str(filepath), "--corpus-root", str(corpus_root)]

    if page_range:
        cmd += ["--page-range", page_range]
    if ocr_engine:
        cmd += ["--ocr-engine", ocr_engine]
    if llm:
        cmd += ["--llm", llm]
    if doc_type:
        cmd += ["--type", doc_type]
    if force_ocr:
        cmd.append("--force-ocr")
    if force_digital:
        cmd.append("--force-digital")
    if no_pageindex:
        cmd.append("--no-pageindex")
    if verbose:
        cmd.append("--verbose")
    if quiet:
        cmd.append("--quiet")

    return cmd


_citeindex_bin: Optional[str] = None


def _find_citeindex() -> Path:
    global _citeindex_bin
    if _citeindex_bin:
        return Path(_citeindex_bin)
    # 1. In the venv
    venv_bin = Path(__file__).parent / ".venv" / "bin" / "citeindex"
    if venv_bin.exists():
        _citeindex_bin = str(venv_bin)
        return venv_bin
    # 2. In PATH
    import shutil
    found = shutil.which("citeindex")
    if found:
        _citeindex_bin = found
        return Path(found)
    print("ERROR: citeindex not found. Install it: pip install citeindex", file=sys.stderr)
    sys.exit(1)


def run_ingest(
    filepath: Path,
    corpus_root: Path,
    page_range: str = "all",
    ocr_engine: str = "mineru",
    llm: str = "",
    doc_type: str = "",
    force_ocr: bool = False,
    force_digital: bool = False,
    verbose: bool = False,
    quiet: bool = True,
    timeout: int = 3600,
) -> IngestResult:
    """Run citeindex on a single file and return the result."""
    # Digital/office PDFs can sometimes stall in PageIndex generation.
    # Retry once without PageIndex so a single slow document does not block the batch.
    attempts: list[bool] = [False]
    if force_digital:
        attempts.append(True)

    last_error = ""
    total_start = time.time()

    for no_pageindex in attempts:
        cmd = build_citeindex_cmd(
            filepath, corpus_root, page_range, ocr_engine, llm, doc_type,
            force_ocr, force_digital, verbose, quiet, no_pageindex=no_pageindex,
        )
        attempt_start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            attempt_duration = time.time() - attempt_start
            if result.returncode == 0:
                # Try to parse output
                source_id = ""
                csl_id = ""
                resource_type = ""
                try:
                    out = result.stdout
                    # citeindex may print JSON at the end
                    # Try to extract from the last JSON block
                    json_match = re.findall(r'\{[^{}]*"source_id"[^{}]*\}', out, re.DOTALL)
                    if json_match:
                        j = json.loads(json_match[-1])
                        source_id = j.get("source_id", "")
                        csl_id = j.get("csl", {}).get("id", "")
                        resource_type = j.get("resource_type", "")
                except Exception:
                    pass
                return IngestResult(
                    filepath=filepath, success=True,
                    source_id=source_id, csl_id=csl_id,
                    resource_type=resource_type, duration_sec=time.time() - total_start,
                )

            last_error = result.stderr.strip()[:500] if result.stderr else result.stdout.strip()[:500]
            return IngestResult(
                filepath=filepath, success=False,
                error=last_error, duration_sec=attempt_duration,
            )
        except subprocess.TimeoutExpired:
            last_error = f"Timeout after {timeout}s"
            if no_pageindex:
                break
            continue
        except Exception as e:
            return IngestResult(
                filepath=filepath, success=False,
                error=str(e), duration_sec=time.time() - total_start,
            )

    return IngestResult(
        filepath=filepath, success=False,
        error=last_error or f"Timeout after {timeout}s",
        duration_sec=time.time() - total_start,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Batch ingest academic PDFs with citeindex — with resume & dedup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("folder", nargs="?", default=None, help="Folder containing files to ingest")
    parser.add_argument("--corpus-root", default=None, help="Corpus output directory (default: ./corpus)")
    parser.add_argument("--resume", action="store_true", default=True, help="Skip already-ingested files (default: True)")
    parser.add_argument("--re-ingest", action="store_true", help="Re-ingest all, even already-done files")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    parser.add_argument("--batch", choices=["digital", "scanned", "all"], default="all", help="Which batch to process")
    parser.add_argument("--page-range", default="all", help="Page range (default: all)")
    parser.add_argument("--ocr-engine", default="mineru", choices=["mineru", "glm-ocr"], help="OCR engine for scanned PDFs")
    parser.add_argument("--llm", default="", help="LLM model (default: citeindex default)")
    parser.add_argument("--force-ocr", action="store_true", help="Force OCR pipeline")
    parser.add_argument("--force-digital", action="store_true", help="Force digital pipeline")
    parser.add_argument("--verbose", action="store_true", help="citeindex verbose output")
    parser.add_argument("--quiet", action="store_true", default=True, help="Suppress citeindex debug (default: True)")
    parser.add_argument("--parallel", type=int, default=1, help="Max parallel ingestions (default: 1)")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-file timeout in seconds (default: 3600)")
    parser.add_argument("--no-interactive", action="store_true", help="Auto-resolve duplicates (pick best: digital > scanned, largest)")
    parser.add_argument("--dedup-choices", default="", help="JSON file to load/save dedup choices (enables resume of dedup decisions)")

    args = parser.parse_args()

    # Determine folder
    if args.folder:
        folder = Path(args.folder).resolve()
    else:
        folder = Path(__file__).parent / "1Taoism"
    if not folder.is_dir():
        print(f"ERROR: {folder} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Determine corpus root
    if args.corpus_root:
        corpus_root = Path(args.corpus_root).resolve()
    else:
        corpus_root = Path(__file__).parent.parent / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True)

    # If re-ingest, disable resume
    resume = args.resume and not args.re_ingest

    print(f"Folder:       {folder}")
    print(f"Corpus root:  {corpus_root}")
    print(f"Resume:       {resume}")
    print(f"Batch:        {args.batch}")
    print(f"Page range:   {args.page_range}")
    print(f"OCR engine:   {args.ocr_engine}")
    print(f"No-interactive: {args.no_interactive}")
    if args.dedup_choices:
        print(f"Dedup choices: {args.dedup_choices}")
    print()

    # --- Step 1: Resolve duplicates ---
    print("=" * 60)
    print("STEP 1: Resolve duplicate files")
    print("=" * 60)
    dedup_file = Path(args.dedup_choices) if args.dedup_choices else None
    if dedup_file and dedup_file.parent != Path(__file__).parent:
        dedup_file = Path(__file__).parent / args.dedup_choices
    skip_set, dedup_choices = resolve_duplicates(folder, args.no_interactive, dedup_file, corpus_root)

    # --- Step 2: Scan and classify ---
    print()
    print("=" * 60)
    print("STEP 2: Scanning & classifying files")
    print("=" * 60)
    all_files = scan_folder(folder, skip_set)

    digital_files = [f for f in all_files if f.pdf_kind == "digital" and not f.skip_reason]
    scanned_files = [f for f in all_files if f.pdf_kind == "scanned" and not f.skip_reason]
    office_files = [f for f in all_files if f.pdf_kind == "office" and not f.skip_reason]
    skipped_files = [f for f in all_files if f.skip_reason]
    problem_files = [f for f in all_files if f.pdf_kind == "problem"]

    # Sort each by size (smallest first = fastest first)
    digital_files.sort(key=lambda f: f.size_mb)
    scanned_files.sort(key=lambda f: f.size_mb)
    office_files.sort(key=lambda f: f.size_mb)

    # Build the work queue: digital+office first, then scanned
    work_queue: list[FileInfo] = []
    if args.batch in ("digital", "all"):
        work_queue += office_files + digital_files
    if args.batch in ("scanned", "all"):
        work_queue += scanned_files

    # --- Step 3: Load corpus state for resume ---
    if resume:
        corpus_state = load_corpus_state(corpus_root)
        already = []
        still_todo = []
        for fi in work_queue:
            if file_already_ingested(fi.path, corpus_state):
                already.append(fi)
            else:
                still_todo.append(fi)
        work_queue = still_todo
    else:
        already = []

    # --- Step 4: Print plan ---
    print()
    print("=" * 60)
    print("STEP 3: Ingestion plan")
    print("=" * 60)

    if already:
        print(f"\n  Already ingested (SKIPPED): {len(already)}")
        for fi in already:
            entry = corpus_state.ingested_files.get(str(fi.path), {})
            print(f"    ✓  {fi.path.name}  ({entry.get('resource_type','?')})")

    if skipped_files:
        print(f"\n  Skipped (user choice or unsupported): {len(skipped_files)}")
        for fi in skipped_files:
            print(f"    ✗  {fi.path.name}  — {fi.skip_reason}")

    if problem_files:
        print(f"\n  Problem files: {len(problem_files)}")
        for fi in problem_files:
            print(f"    ⚠  {fi.path.name}  — {fi.skip_reason}")

    print(f"\n  To ingest: {len(work_queue)}")
    for i, fi in enumerate(work_queue, 1):
        tag = fi.pdf_kind.upper()
        dtype_tag = f" --type {fi.doc_type_hint}" if fi.doc_type_hint else ""
        ocr_tag = f" --ocr-engine {args.ocr_engine}" if fi.pdf_kind == "scanned" else ""
        print(f"    {i:>2}. [{tag:7}] {fi.size_mb:7.1f} MB {fi.pages:>5} pg{dtype_tag}{ocr_tag}  {fi.path.name}")

    if not work_queue:
        print("\n  Nothing to ingest. Done!")
        return

    if args.dry_run:
        print("\n  [DRY RUN] No files were ingested.")
        return

    # --- Step 5: Execute ---
    print()
    print("=" * 60)
    print("STEP 4: Ingesting")
    print("=" * 60)

    results: list[IngestResult] = []
    total = len(work_queue)

    if args.parallel <= 1:
        # Sequential
        for i, fi in enumerate(work_queue, 1):
            ocr = args.ocr_engine if fi.pdf_kind == "scanned" else ""
            print(f"\n  [{i}/{total}] {fi.path.name} ({fi.size_mb:.1f} MB, {fi.pages} pg, {fi.pdf_kind})")

            res = run_ingest(
                filepath=fi.path,
                corpus_root=corpus_root,
                page_range=args.page_range,
                ocr_engine=ocr or "mineru",
                llm=args.llm,
                doc_type=fi.doc_type_hint,
                force_ocr=args.force_ocr or (fi.pdf_kind == "scanned"),
                force_digital=args.force_digital or (fi.pdf_kind in ("digital", "office")),
                verbose=args.verbose,
                quiet=not args.verbose,
                timeout=args.timeout,
            )
            results.append(res)
            status = "✓ OK" if res.success else f"✗ FAIL: {res.error[:80]}"
            print(f"    {status}  ({res.duration_sec:.1f}s)")
    else:
        # Parallel
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures: dict[Future, tuple[int, FileInfo]] = {}
            for i, fi in enumerate(work_queue, 1):
                ocr = args.ocr_engine if fi.pdf_kind == "scanned" else ""
                future = pool.submit(
                    run_ingest,
                    filepath=fi.path,
                    corpus_root=corpus_root,
                    page_range=args.page_range,
                    ocr_engine=ocr or "mineru",
                    llm=args.llm,
                    doc_type=fi.doc_type_hint,
                    force_ocr=args.force_ocr or (fi.pdf_kind == "scanned"),
                    force_digital=args.force_digital or (fi.pdf_kind in ("digital", "office")),
                    verbose=args.verbose,
                    quiet=not args.verbose,
                    timeout=args.timeout,
                )
                futures[future] = (i, fi)

            for future in as_completed(futures):
                i, fi = futures[future]
                res = future.result()
                results.append(res)
                status = "✓ OK" if res.success else f"✗ FAIL: {res.error[:80]}"
                print(f"  [{i}/{total}] {fi.path.name}: {status}  ({res.duration_sec:.1f}s)")

    # --- Step 6: Summary ---
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]

    print(f"  Total:   {len(results)}")
    print(f"  Success: {len(successes)}")
    print(f"  Failed:  {len(failures)}")

    if failures:
        print(f"\n  Failed files:")
        for r in failures:
            print(f"    ✗  {r.filepath.name}  — {r.error[:100]}")

    print(f"\n  Corpus: {corpus_root}")
    print(f"  Corpus entries: {len(list(corpus_root.iterdir())) - 1}")  # -1 for ingestion_log.jsonl

    # Save manifest
    manifest_path = corpus_root / "ingest_manifest.json"
    manifest = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "folder": str(folder),
        "corpus_root": str(corpus_root),
        "results": [
            {
                "file": str(r.filepath),
                "name": r.filepath.name,
                "success": r.success,
                "source_id": r.source_id,
                "error": r.error,
                "duration_sec": round(r.duration_sec, 1),
            }
            for r in results
        ],
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"  Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
