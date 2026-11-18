import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

export function readJsonFile(file: string): any | null {
  if (!existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

export function projectRoot(corpusRoot: string): string {
  const resolved = path.resolve(corpusRoot);
  return resolved === path.resolve(process.cwd()) ? resolved : path.dirname(resolved);
}

export function activePaperId(corpusRoot: string): string | null {
  const file = path.join(projectRoot(corpusRoot), ".shutong", "active-paper");
  if (!existsSync(file)) return null;
  const value = readFileSync(file, "utf8").trim();
  return value || null;
}

export function activeWorkspace(corpusRoot: string): Record<string, unknown> | null {
  return readJsonFile(path.join(projectRoot(corpusRoot), ".shutong", "active-workspace.json"));
}
