import { existsSync, readdirSync } from "node:fs";
import path from "node:path";

/** Continue after the highest existing numeric suffix, matching papers._next_id. */
export function nextId(directory: string, prefix: string, suffix: string): string {
  let highest = 0;
  if (existsSync(directory)) {
    const pattern = new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(\\d+)${suffix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);
    for (const name of readdirSync(directory)) {
      const match = pattern.exec(name);
      if (match) highest = Math.max(highest, Number(match[1]));
    }
  }
  return `${prefix}${highest + 1}`;
}
