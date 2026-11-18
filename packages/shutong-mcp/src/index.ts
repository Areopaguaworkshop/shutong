#!/usr/bin/env node
const args = process.argv.slice(2);
if (args.length > 0 && ["doctor", "install", "rollback", "--version", "-v", "help", "--help", "-h"].includes(args[0])) {
  const { main } = await import("./cli.ts");
  process.exitCode = await main(args);
} else {
  await import("./mcp/server.ts");
}
