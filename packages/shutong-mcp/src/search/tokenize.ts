/**
 * Text canonicalization and CJK-aware tokenization.
 *
 * The canonical form mirrors citeindex.ingestion.deterministic.canonicalize_text:
 * CRLF/CR become LF, every run of Python-whitespace inside a line collapses to
 * one space, line edges are stripped, then the whole string is trimmed.
 */
const PYTHON_WHITESPACE =
  /[\t\n\v\f\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/gu;

export function canonicalizeText(text: unknown): string {
  if (text === null || text === undefined) return "";
  const value = typeof text === "string" ? text : String(text);
  const normalized = value.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  return normalized
    .split("\n")
    .map((line) => line.split(PYTHON_WHITESPACE).filter(Boolean).join(" "))
    .join("\n")
    .trim();
}

const segmenter = new Intl.Segmenter("zh", { granularity: "word" });

/**
 * Segment Chinese and Latin text into index terms.
 *
 * `Intl.Segmenter` is built into Node and gives a useful first pass for both
 * scripts. `@node-rs/jieba` can replace this implementation later without
 * changing the schema, because only the token string is persisted.
 */
export function tokenize(text: string): string {
  return queryTokens(text).join(" ");
}

export function queryTokens(text: string): string[] {
  const value = text.normalize("NFC");
  const tokens: string[] = [];
  for (const part of segmenter.segment(value)) {
    if (!part.isWordLike) continue;
    const token = part.segment.trim().toLowerCase();
    if (!token) continue;
    tokens.push(token);
  }
  return tokens;
}

/**
 * Build an FTS5 query that ORs quoted terms, so a multi-word query does not
 * silently require every term (which is FTS5's default AND behavior).
 */
export function ftsQuery(text: string): string | null {
  const tokens = queryTokens(text);
  if (tokens.length === 0) return null;
  return tokens.map((token) => `"${token.replaceAll('"', '""')}"`).join(" OR ");
}
