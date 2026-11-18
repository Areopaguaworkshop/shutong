import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { runtimeConfig } from "./context.ts";

function readJson(file: string): any | null {
  if (!existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function passportList(storageDir: string): Array<Record<string, unknown>> {
  const dir = path.join(storageDir, "passport");
  if (!existsSync(dir)) return [];
  const passports: Array<Record<string, unknown>> = [];
  for (const file of readdirSync(dir)) {
    if (!file.endsWith(".json")) continue;
    const passport = readJson(path.join(dir, file));
    if (!passport) continue;
    passports.push({
      passport_id: passport.passport_id ?? "",
      project_name: passport.project_name ?? "",
      updated_at: passport.updated_at ?? "",
      sources_count: Array.isArray(passport.sources_consulted) ? passport.sources_consulted.length : 0,
      insights_count: Array.isArray(passport.key_insights) ? passport.key_insights.length : 0,
    });
  }
  return passports.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
}

function passportSummary(storageDir: string, passportId: string, maxTokens: number): string {
  const passport = readJson(path.join(storageDir, "passport", `${passportId}.json`));
  if (!passport) return "";
  const lines = [
    `Project: ${passport.project_name ?? "Untitled"}`,
    `Goals: ${(passport.research_goals ?? []).slice(0, 5).join(", ") || "(none set)"}`,
    `Sources consulted: ${(passport.sources_consulted ?? []).length}`,
    `Open questions: ${(passport.open_questions ?? []).length}`,
    `Key insights: ${(passport.key_insights ?? []).length}`,
  ];
  for (const insight of (passport.key_insights ?? []).slice(0, 3)) {
    lines.push(`  - ${String(insight?.insight ?? "").slice(0, 80)}`);
  }
  for (const question of (passport.open_questions ?? []).slice(0, 3)) {
    lines.push(
      `  ? ${String(question?.question ?? "").slice(0, 80)} [${question?.status ?? "open"}]`,
    );
  }
  const text = lines.join("\n");
  return text.length > maxTokens * 4 ? text.slice(0, maxTokens * 4) : text;
}

function diaryDates(storageDir: string): string[] {
  const dir = path.join(storageDir, "diary");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((file) => file.endsWith(".json"))
    .map((file) => file.slice(0, -5))
    .sort()
    .reverse();
}

function recentDiary(storageDir: string, count: number): Array<Record<string, any>> {
  const entries: Array<Record<string, any>> = [];
  for (const date of diaryDates(storageDir).slice(0, count)) {
    const value = readJson(path.join(storageDir, "diary", `${date}.json`));
    if (Array.isArray(value)) entries.push(...value);
  }
  return entries.slice(0, count);
}

function graphStats(storageDir: string): Record<string, number> {
  const graph = readJson(path.join(storageDir, "graph", "graph.json"));
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  return {
    nodes: nodes.length,
    edges: edges.length,
    claims: nodes.filter((node: any) => node?.node_type === "claim").length,
    sources: nodes.filter((node: any) => node?.node_type === "source").length,
    contradictions: edges.filter((edge: any) => edge?.edge_type === "contradicts").length,
  };
}

function memoryThreads(memoryDir: string): Array<Record<string, unknown>> {
  if (!existsSync(memoryDir)) return [];
  const threads: Array<Record<string, unknown>> = [];
  for (const file of readdirSync(memoryDir).filter((name) => name.endsWith(".jsonl")).sort()) {
    const threadId = file.slice(0, -6);
    const entries = readFileSync(path.join(memoryDir, file), "utf8")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
    threads.push({
      thread_id: threadId,
      entry_count: entries.length,
      latest_timestamp: entries.length ? entries[entries.length - 1].timestamp ?? null : null,
    });
  }
  return threads;
}

export async function handleStateWakeUp(args: {
  passport_id?: string;
  max_tokens?: number;
}): Promise<Record<string, unknown>> {
  const cfg = runtimeConfig();
  const storageDir = cfg.storageDir;
  const parts: string[] = [];
  const requested = args.passport_id;
  const passportId = requested ?? passportList(storageDir)[0]?.passport_id;
  if (typeof passportId === "string") {
    const summary = passportSummary(storageDir, passportId, Number(args.max_tokens ?? 500));
    if (summary) parts.push(summary);
  }

  const recent = recentDiary(storageDir, 3);
  if (recent.length > 0) {
    const lines = ["## Recent sessions"];
    for (const entry of recent) {
      const topics = Array.isArray(entry.topics_discussed)
        ? entry.topics_discussed.slice(0, 3).join(", ")
        : "";
      lines.push(`- ${entry.timestamp ?? ""}: ${topics || "(no topics)"}`);
    }
    parts.push(lines.join("\n"));
  }

  const stats = graphStats(storageDir);
  if (stats.nodes > 0) {
    parts.push(
      `## Knowledge graph: ${stats.nodes} nodes, ${stats.edges} edges, ${stats.contradictions} contradictions`,
    );
  }
  return { context: parts.join("\n\n") };
}

export async function handleStateSnapshot(): Promise<Record<string, unknown>> {
  const cfg = runtimeConfig();
  return {
    passports: passportList(cfg.storageDir),
    graph: graphStats(cfg.storageDir),
    diary_dates: diaryDates(cfg.storageDir),
    memory_threads: memoryThreads(path.join(cfg.storageDir, "memory")),
  };
}

function localTimestamp(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

function localDate(): string {
  return localTimestamp().slice(0, 10);
}

function mergePassport(
  storageDir: string,
  passportId: string,
  updates: Record<string, unknown>,
): void {
  const file = path.join(storageDir, "passport", `${passportId}.json`);
  if (!existsSync(file)) return;
  const passport = readJson(file);
  if (!passport || typeof passport !== "object") return;
  for (const [key, value] of Object.entries(updates)) {
    if (key === "passport_id" || key === "created_at" || key === "schema_version") continue;
    if (Array.isArray(value) && Array.isArray(passport[key])) {
      const existing = new Set(passport[key].map((item: unknown) => String(item)));
      for (const item of value) {
        if (!existing.has(String(item))) {
          passport[key].push(item);
          existing.add(String(item));
        }
      }
    } else if (value && typeof value === "object" && passport[key] && typeof passport[key] === "object") {
      Object.assign(passport[key], value);
    } else {
      passport[key] = value;
    }
  }
  passport.updated_at = localTimestamp();
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(passport, null, 2), "utf8");
}

export async function handleStateRecordSession(args: {
  session_id?: string;
  topics?: string[];
  sources?: string[];
  insights?: string[];
  open_questions?: string[];
  passport_id?: string;
}): Promise<Record<string, unknown>> {
  const cfg = runtimeConfig();
  const sessionId = String(args.session_id ?? "");
  if (!sessionId) {
    return { status: "error", error_code: "invalid_input", message: "session_id is required" };
  }
  const entry = {
    schema_version: "1.0.0",
    entry_id: `diary-${Math.floor(Date.now() / 1000)}`,
    timestamp: localTimestamp(),
    session_id: sessionId,
    topics_discussed: args.topics ?? [],
    sources_consulted: args.sources ?? [],
    key_insights: args.insights ?? [],
    open_questions: args.open_questions ?? [],
    depth_trend: "stable",
    passport_updates: {},
  };
  const diaryDir = path.join(cfg.storageDir, "diary");
  mkdirSync(diaryDir, { recursive: true });
  const diaryFile = path.join(diaryDir, `${localDate()}.json`);
  let entries: unknown[] = [];
  if (existsSync(diaryFile)) {
    const existing = readJson(diaryFile);
    if (Array.isArray(existing)) entries = existing;
  }
  entries.push(entry);
  writeFileSync(diaryFile, JSON.stringify(entries, null, 2), "utf8");

  const result: Record<string, unknown> = { diary_entry_id: entry.entry_id };
  if (args.passport_id) {
    mergePassport(cfg.storageDir, args.passport_id, {
      sources_consulted: args.sources ?? [],
      key_insights: (args.insights ?? []).map((insight) => ({ insight })),
      open_questions: (args.open_questions ?? []).map((question) => ({ question, status: "open" })),
    });
    result.passport_updated = args.passport_id;
  }
  return result;
}
