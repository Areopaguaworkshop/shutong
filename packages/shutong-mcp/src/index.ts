#!/usr/bin/env node
const args = process.argv.slice(2);
if (args[0] === "search-json") {
  const { mkdtempSync, readFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { handleSearch } = await import("./tools/search.ts");
  const temporaryIndex = process.env.SHUTONG_SKIP_INDEX === "1"
    ? null : mkdtempSync(join(tmpdir(), "shutong-sqlite-"));
  if (temporaryIndex) process.env.SHUTONG_INDEX_DB = join(temporaryIndex, "search.sqlite");
  try {
    console.log(JSON.stringify(await handleSearch(JSON.parse(readFileSync(0, "utf8")))));
  } catch (error) {
    console.log(JSON.stringify({ status: "error", error_code: "search_failed", message: (error as Error).message }));
    process.exitCode = 1;
  } finally {
    if (temporaryIndex) {
      rmSync(temporaryIndex, { recursive: true, force: true });
    }
  }
} else if (args.length > 0 && ["doctor", "install", "rollback", "--version", "-v", "help", "--help", "-h"].includes(args[0])) {
  const { main } = await import("./cli.ts");
  process.exitCode = await main(args);
} else {
  await import("./mcp/server.ts");
}
