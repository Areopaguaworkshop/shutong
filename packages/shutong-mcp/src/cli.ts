import { runDoctor } from "./commands/doctor.ts";
import { HOSTS, hermesInstructions, installAll, rollbackAll, type Host } from "./commands/install.ts";
import { VERSION } from "./version.ts";

function parseHosts(value: string | undefined): Host[] {
  if (!value) return HOSTS.filter((host) => host !== "hermes");
  const selected = value.split(",").map((item) => item.trim()).filter(Boolean) as Host[];
  const invalid = selected.filter((host) => !HOSTS.includes(host));
  if (invalid.length > 0) throw new Error(`Unknown host(s): ${invalid.join(", ")}`);
  return selected;
}

export async function main(argv: string[]): Promise<number> {
  const command = argv[0];
  if (command === "--version" || command === "-v") {
    console.log(VERSION);
    return 0;
  }
  if (command === "help" || command === "--help" || command === "-h" || !command) {
    console.log("Usage: shutong-mcp [doctor|install|rollback|help|--version]");
    console.log("  doctor [--json]");
    console.log("  install [--host opencode,claude,codex,pi,hermes] [--dry-run] [--no-backup] [--home PATH]");
    console.log("  rollback [--dry-run] [--home PATH]");
    return 0;
  }
  if (command === "doctor") {
    const result = await runDoctor();
    if (argv.includes("--json")) {
      console.log(JSON.stringify(result, null, 2));
    } else {
      for (const check of result.checks) {
        console.log(`[${check.ok ? "OK" : "FAIL"}] ${check.name}: ${check.detail}`);
      }
    }
    return result.ok ? 0 : 1;
  }
  if (command === "install") {
    const hostArg = argv.includes("--host") ? argv[argv.indexOf("--host") + 1] : undefined;
    const home = argv.includes("--home") ? argv[argv.indexOf("--home") + 1] : undefined;
    const dryRun = argv.includes("--dry-run");
    const backup = !argv.includes("--no-backup");
    const hosts = parseHosts(hostArg);
    for (const result of installAll(hosts, { home, dryRun, backup })) {
      console.log(
        `${result.host}: ${result.path}${dryRun ? " (dry run)" : ""}${result.backup ? ` · backup ${result.backup}` : ""}`,
      );
    }
    if (hosts.includes("hermes")) console.log(hermesInstructions());
    return 0;
  }
  if (command === "rollback") {
    const home = argv.includes("--home") ? argv[argv.indexOf("--home") + 1] : undefined;
    const dryRun = argv.includes("--dry-run");
    for (const result of rollbackAll(home, dryRun)) {
      console.log(`${result.host}: ${result.path} · ${result.restored ? "restored" : "no backup"}${dryRun ? " (dry run)" : ""}`);
    }
    return 0;
  }
  console.error(`Unknown command: ${command}`);
  return 2;
}
