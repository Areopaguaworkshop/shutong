import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { hashPayload } from "../contract/hash.ts";
import { runtimeConfig } from "./context.ts";

// Mirrors shutong_backend.agents.indexing._STOP_WORDS.
const STOP_WORDS = new Set([
  "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "from",
  "is", "it", "as", "be", "was", "were", "are", "this", "that", "these", "those", "not", "no", "do",
  "does", "did", "has", "have", "had", "will", "would", "can", "could", "may", "might", "shall",
  "should", "its", "also", "than", "then", "so", "if", "we", "he", "she", "they", "you", "i", "me",
  "my", "our", "his", "her", "their", "your", "all", "each", "every", "both", "few", "more", "most",
  "other", "some", "such", "only", "own", "same", "very", "just", "about", "above", "after", "before",
  "between", "into", "through", "during", "up", "down", "out", "over", "under", "again", "further",
  "been", "being", "there", "here", "when", "where", "which", "who", "whom", "what", "how", "de",
  "des", "du", "la", "le", "les", "un", "une", "et", "en", "的", "了", "在", "是", "我", "他", "她",
  "它", "们", "这", "那", "有", "和", "与", "为", "以", "而", "之", "其", "也", "不", "所", "于", "中",
  "上", "下",
]);

const TOKEN_RE = /[\p{L}\p{N}_\u4e00-\u9fff\u3400-\u4dbf]+/gu;

function pythonTokenize(text: string): string[] {
  const raw = text.toLowerCase().match(TOKEN_RE) ?? [];
  return raw.filter((token) => token.length > 1 && !STOP_WORDS.has(token));
}

interface MemoryEntry {
  entry_id?: string;
  timestamp?: string;
  thread_id?: string;
  query?: string;
  response?: string;
  evidence_node_ids?: string[];
  sha256?: string;
}

function memoryDir(): string {
  return path.join(runtimeConfig().corpusRoot, ".memory");
}

function listThreads(): string[] {
  const dir = memoryDir();
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((file) => file.endsWith(".jsonl"))
    .sort()
    .map((file) => file.slice(0, -6));
}

function loadThread(threadId: string): MemoryEntry[] {
  const file = path.join(memoryDir(), `${threadId.replace(/[^a-zA-Z0-9_-]/g, "_")}.jsonl`);
  if (!existsSync(file)) return [];
  return readFileSync(file, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line) as MemoryEntry;
      } catch {
        return null;
      }
    })
    .filter((entry): entry is MemoryEntry => entry !== null);
}

function searchMemory(query: string, limit: number, threadId?: string): MemoryEntry[] {
  const queryTokens = new Set(pythonTokenize(query));
  if (queryTokens.size === 0) return [];
  const threads = threadId ? [threadId] : listThreads();
  const scored: Array<{ score: number; entry: MemoryEntry }> = [];
  for (const thread of threads) {
    for (const entry of loadThread(thread)) {
      const entryTokens = new Set(pythonTokenize(`${entry.query ?? ""} ${entry.response ?? ""}`));
      let overlap = 0;
      for (const token of queryTokens) if (entryTokens.has(token)) overlap += 1;
      if (overlap > 0) scored.push({ score: overlap, entry });
    }
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, limit).map((item) => item.entry);
}

export async function handleMemory(args: {
  action?: string;
  query?: string;
  thread_id?: string;
  limit?: number;
}): Promise<Record<string, unknown>> {
  const limit = Math.max(1, Math.min(200, Number(args.limit ?? 20) || 20));
  if (args.action === "search") {
    if (!args.query) {
      return { status: "error", error_code: "invalid_input", message: "query is required" };
    }
    return {
      status: "ok",
      results: searchMemory(args.query, limit, args.thread_id),
    };
  }
  if (args.action === "list") {
    return {
      status: "ok",
      threads: listThreads()
        .slice(0, limit)
        .map((threadId) => {
          const entries = loadThread(threadId);
          const latest = entries[entries.length - 1];
          return {
            thread_id: threadId,
            entry_count: entries.length,
            latest_timestamp: latest?.timestamp ?? null,
            latest_query: latest?.query ?? null,
          };
        }),
    };
  }
  if (args.action === "save") {
    const title = String((args as any).title ?? "").trim();
    const content = String((args as any).content ?? "");
    if (!title || !content) {
      return {
        status: "error",
        error_code: "invalid_input",
        message: "title and content are required",
      };
    }
    const timestamp = new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00");
    const sha256 = hashPayload(`${timestamp}|${title}|${content}`);
    const entry = {
      entry_id: sha256.slice(0, 16),
      evidence_node_ids: [],
      query: title,
      response: content,
      sha256,
      thread_id: "notes",
      timestamp,
    };
    const dir = memoryDir();
    mkdirSync(dir, { recursive: true });
    appendFileSync(path.join(dir, "notes.jsonl"), `${JSON.stringify(entry)}\n`, "utf8");
    return { status: "ok", entry };
  }
  return {
    status: "error",
    error_code: "invalid_action",
    message: `Unknown memory action: ${args.action ?? ""}`,
    next_action: "Use action=search or action=list.",
  };
}
