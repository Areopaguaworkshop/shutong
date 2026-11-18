import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

/**
 * Package version, read from package.json so the CLI, the MCP server metadata
 * and the published manifest cannot drift apart.
 *
 * `../package.json` resolves to the package root from both `src/` and `dist/`.
 */
export const VERSION: string = (
  JSON.parse(
    readFileSync(fileURLToPath(new URL("../package.json", import.meta.url)), "utf8"),
  ) as { version: string }
).version;
