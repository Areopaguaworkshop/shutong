from __future__ import annotations

import json
import shutil
from pathlib import Path


def _ensure_dir(glossary_dir: Path) -> Path:
    glossary_dir.mkdir(parents=True, exist_ok=True)
    return glossary_dir


def _read_glossary(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Glossary file must contain a JSON object: {path}")
    return data


def _normalize_entries(data: dict) -> dict[str, str]:
    return {
        key: value
        for key, value in data.items()
        if key != "_meta" and isinstance(key, str) and isinstance(value, str)
    }


def list_all(glossary_dir: Path | str) -> dict[str, dict[str, str]]:
    root = _ensure_dir(Path(glossary_dir))
    result: dict[str, dict[str, str]] = {}
    for path in sorted(root.glob("*.json")):
        result[path.name] = dict(sorted(_normalize_entries(_read_glossary(path)).items()))
    return result


def load_all_glossaries(glossary_dir: Path | str, extra_files: list[str] | None = None) -> dict[str, str]:
    merged: dict[str, str] = {}
    for entries in list_all(glossary_dir).values():
        for term, translation in entries.items():
            merged[term.lower()] = translation

    for raw_path in extra_files or []:
        path = Path(raw_path)
        if path.exists():
            for term, translation in _normalize_entries(_read_glossary(path)).items():
                merged[term.lower()] = translation
    return merged


def lookup(terms: list[str], glossary_dir: Path | str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for filename, entries in list_all(glossary_dir).items():
        lower_map = {term.lower(): term for term in entries}
        for term in terms:
            match = lower_map.get(term.lower())
            if match is not None:
                result[term] = {"zh": entries[match], "source_file": filename}
    return result


def add_entry(term_en: str, term_zh: str, glossary_dir: Path | str, file: str | None = None) -> dict:
    root = _ensure_dir(Path(glossary_dir))
    filename = file or "theology-en-zh.json"
    path = root / filename
    data = _read_glossary(path)
    if "_meta" not in data:
        data["_meta"] = {
            "version": "1.0",
            "source_lang": "en",
            "target_lang": "zh-simplified",
        }
    data[term_en] = term_zh
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"status": "ok", "file": filename, "term_en": term_en, "term_zh": term_zh}


def load_file(filepath: str, glossary_dir: Path | str) -> dict:
    source = Path(filepath)
    if not source.exists():
        raise FileNotFoundError(filepath)
    data = _read_glossary(source)
    root = _ensure_dir(Path(glossary_dir))
    target = root / source.name
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"status": "ok", "loaded_file": str(target)}


def copy_file(filepath: str, glossary_dir: Path | str) -> dict:
    source = Path(filepath)
    if not source.exists():
        raise FileNotFoundError(filepath)
    root = _ensure_dir(Path(glossary_dir))
    target = root / source.name
    shutil.copyfile(source, target)
    return {"status": "ok", "loaded_file": str(target)}
