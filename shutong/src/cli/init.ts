import { existsSync, mkdirSync, writeFileSync } from "fs"
import path from "path"
import { discoverConfig, projectConfigPath, writeProjectConfig } from "../engine/config"
import { detectHosts, type Host } from "./hosts"
import { renderHostArtifacts } from "./renderer"

const defaultGlossary = `{
  "_meta": { "version": "1.0", "domain": "patristic-theology", "source_lang": "en", "target_lang": "zh-simplified" },
  "hypostasis": "位格", "ousia": "本质", "logos": "道", "pneuma": "灵", "theotokos": "神之母", "kenosis": "虚己", "perichoresis": "互契", "homoousios": "同质", "homoiousios": "相似质", "apophatic": "否定神学", "cataphatic": "肯定神学", "patristic": "教父", "Syriac": "叙利亚文", "Peshitta": "贝西大", "Ephrem": "以弗连", "memra": "话语", "Estrangelo": "古典叙利亚文体", "Serto": "西叙利亚文体", "liturgy": "礼仪", "anaphora": "圣餐祷文", "epiclesis": "圣灵祈求", "doxology": "荣耀颂", "exegesis": "释经", "hermeneutics": "诠释学", "soteriology": "救恩论", "Christology": "基督论", "pneumatology": "圣灵论", "eschatology": "末世论", "ecclesiology": "教会论", "protology": "创始论", "pericope": "选段", "miaphysitism": "一性论", "Chalcedon": "迦克墩", "Ephesus": "以弗所", "Nicaea": "尼西亚", "anathema": "绝罚", "theosis": "神化", "apocatastasis": "万物复原", "dyophysitism": "二性论", "miaphysite": "一性论者", "Chalcedonian": "迦克墩派", "non-Chalcedonian": "非迦克墩派"
}\n`

function renderProjectAgentsMd(): string {
  return `# Shutong 書童 — Project Instructions

<!-- SHUTONG:BEGIN — do not remove this marker -->

## Scholar Principle

Never state a fact without a citation.

- Every factual claim must trace to a corpus source or a file + line number.
- If no citation is available, say exactly: "No citation available for this claim in the current corpus."
- Distinguish clearly: known (corpus-cited) / probable (evidence noted but indirect) / speculative (clearly labelled as such).
- Citation format: Chicago author-date — (Author Year, page).

## Shutong Skills

Shutong ships skills, not specialist agents. Load the skill that owns the
requested artifact and follow its Role, Tools, Evidence gate, and Never sections.

| Request | Skill |
|---|---|
| Discover or update a bibliography | \`explore-bibliography\` |
| Check lawful access before intake | \`copyright-access\` |
| Ingest an approved source | \`ingest-source\` |
| Read, quote, translate, or note a passage | \`noter\` with \`text-analysis\`, \`evidence-synthesis\` |
| Audit bibliography, integrity, notes, claims | \`verify-bibliography\` with \`verify-corpus\`, \`citation-check\` |
| Start, resume, or switch a project/work | \`workspace-planner\` with \`paper-workspace\` |

## Research Protocol

The host agent is the conductor: it confirms the active work, loads the owning
skill, enforces the evidence lineage, and drafts only from verified notes after
an explicit scholar request. Full-paper composition is not the default deliverable.

Before answering any research question:
1. Call \`shutong_search\` with the query to check the local corpus.
2. Call \`shutong_verify\` with \`mode: node\` on the top results before quoting them.
3. If \`shutong_verify\` returns FAIL for a node, mark it [UNVERIFIED] and exclude it from your answer.
4. Do not answer factual scholarly questions from parametric memory alone.
5. If the corpus is empty, say: "No documents ingested yet." and explain that the scholar must approve and ingest sources first.

## Translation Protocol

Translation is a host-agent task, not a Shutong backend workflow; the output is a
private note, not prose. Use the translate-academic skill.

1. Confirm the source is approved and ingested. Ask the scholar for the target
   language; default to Traditional Chinese (zh-Hant).
2. Read \`.shutong/glossary/*.json\` first; glossary matches are mandatory.
   Untranslatable proper nouns: \`[未译: OriginalTerm]\`.
3. Preserve citation keys and footnote markers exactly as they appear.
4. Direct quotations: keep the original-language quotation verbatim and follow it
   with a parenthetical translation \`（譯：……）\`. Never replace the original.
5. Bind every quotation to its \`source_id\`, exact corpus locator, and a Chicago
   author-date reference rendered with \`shutong_citation\`. A translated quotation
   is evidence only when the verbatim original and locator are recorded.
6. Record the note with \`shutong_note\` action \`add\`, with confidence (\`known\`,
   \`probable\`, or \`speculative\`) and tags including \`translation\` and the target
   language.

## Coding Discipline

1. Think before coding. State assumptions. Ask if unclear.
2. Simplicity first. Minimum code. No speculative features.
3. Surgical edits. Touch only what the task requires.
4. Goal-driven. Define success criteria. Verify each step.

## Corpus

- Corpus root: \`./corpus/\`
- Library: \`./library/\`
- Glossaries: \`./.shutong/glossary/\`

<!-- SHUTONG:END -->
`
}

export interface InitResult {
  written: string[]
  warnings: string[]
}

export function initProject(root = process.cwd(), force = false, host?: Host): InitResult {
  const written: string[] = []
  const warnings: string[] = []
  const selected = host ? [host] : detectHosts(root)
  if (selected.length === 0) return { written, warnings: ["No supported agent hosts detected. Supported: opencode, claude, codex, pi, hermes."] }
  const corpusRoot = path.join(root, "corpus")
  const libraryRoot = path.join(root, "library")
  const shutongRoot = path.join(root, ".shutong")

  mkdirSync(corpusRoot, { recursive: true })
  mkdirSync(libraryRoot, { recursive: true })

  const agentsPath = path.join(root, "AGENTS.md")
  if (force || !existsSync(agentsPath)) {
    writeFileSync(agentsPath, renderProjectAgentsMd(), "utf-8")
    written.push(agentsPath)
  }

  const glossary = path.join(shutongRoot, "glossary", "theology-en-zh.json")
  if (force || !existsSync(glossary)) { mkdirSync(path.dirname(glossary), { recursive: true }); writeFileSync(glossary, defaultGlossary, "utf8"); written.push(glossary) }

  if (force || !existsSync(projectConfigPath(root))) {
    writeProjectConfig({
      corpus_root: "corpus",
      library_root: "library",
    }, root)
    written.push(projectConfigPath(root))
  }
  const config = discoverConfig(root)
  for (const target of selected) written.push(...renderHostArtifacts(target, root, config.python_bin, force))

  return { written, warnings }
}
