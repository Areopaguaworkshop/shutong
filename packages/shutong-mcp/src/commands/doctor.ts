import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { SearchIndex } from "../search/index.ts";
import { loadRuntimeConfig } from "../config.ts";
import { shutongHome } from "./install.ts";

export interface Check {
  name: string;
  ok: boolean;
  detail: string;
}

function commandCheck(command: string, args: string[], detail?: string): Check {
  const result = spawnSync(command, args, { encoding: "utf8", timeout: 10000 });
  return {
    name: detail ?? command,
    ok: !result.error && result.status === 0,
    detail: result.error?.message ?? (result.stdout || result.stderr).trim().split("\n")[0] ?? "",
  };
}

async function llmCheck(): Promise<Check> {
  const configured = process.env.SHUTONG_LLM_MODEL;
  if (configured) return { name: "LLM model", ok: true, detail: configured };
  try {
    const response = await fetch("http://localhost:11434/api/tags", {
      signal: AbortSignal.timeout(2000),
    });
    if (response.ok) return { name: "LLM endpoint", ok: true, detail: "Ollama on localhost:11434" };
    return { name: "LLM endpoint", ok: false, detail: `HTTP ${response.status}` };
  } catch {
    return {
      name: "LLM endpoint",
      ok: false,
      detail: "Set SHUTONG_LLM_MODEL or start Ollama; local PDF ingestion needs an LLM.",
    };
  }
}

export async function runDoctor(): Promise<{ ok: boolean; checks: Check[] }> {
  const cfg = loadRuntimeConfig();
  const checks: Check[] = [];

  const nodeMajor = Number(process.versions.node.split(".")[0]);
  checks.push({ name: "Node.js", ok: nodeMajor >= 24, detail: process.versions.node });

  checks.push(
    commandCheck(
      process.env.SHUTONG_CITEINDEX_BIN ?? "citeindex",
      ["--help"],
      "citeindex CLI",
    ),
  );
  checks.push(
    commandCheck(
      process.env.SHUTONG_PYTHON ?? "python3",
      ["-c", "import yaml; print(yaml.__version__)"],
      "PyYAML (note frontmatter)",
    ),
  );

  checks.push({
    name: "Corpus root",
    ok: existsSync(cfg.corpusRoot),
    detail: cfg.corpusRoot,
  });

  if (existsSync(cfg.dbPath)) {
    const index = new SearchIndex(cfg.dbPath);
    const stats = index.stats();
    index.close();
    checks.push({
      name: "Search index",
      ok: stats.documents > 0,
      detail: `${stats.documents} documents, ${stats.nodes} nodes, ${(stats.dbBytes / 1e6).toFixed(1)} MB`,
    });
  } else {
    checks.push({ name: "Search index", ok: false, detail: "not built; first tool call builds it" });
  }

  checks.push(await llmCheck());

  const home = shutongHome();
  for (const [name, file] of [
    ["OpenCode config", path.join(home, ".config", "opencode", "opencode.json")],
    ["Claude config", path.join(home, ".claude.json")],
    ["Codex config", path.join(home, ".codex", "config.toml")],
    ["Pi config", path.join(home, ".pi", "mcp.json")],
  ] as const) {
    checks.push({ name, ok: true, detail: existsSync(file) ? file : "not configured" });
  }

  return { ok: checks.every((check) => check.ok), checks };
}
