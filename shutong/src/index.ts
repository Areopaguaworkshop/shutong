import yargs from "yargs"
import { hideBin } from "yargs/helpers"
import { runDoctor } from "./cli/doctor"
import { runStatus } from "./cli/status"
import { initProject } from "./cli/init"
import { HOSTS, type Host } from "./cli/hosts"
import { addPaperSource, auditPaper, createPaper, paperStatus, usePaper, type SourceRole } from "./cli/papers"
import { setupBackend } from "./cli/setup"

export async function run(): Promise<void> {
  await yargs(hideBin(process.argv))
    .scriptName("shutong")
    .version("0.4.0")
    .command(
      "init",
      "Create native .shutong project scaffolding",
      (y) => y.option("force", { type: "boolean", default: false, description: "Overwrite generated scaffold files" }).option("host", { choices: HOSTS, description: "Target host" }).option("list-hosts", { type: "boolean", default: false, description: "List detected hosts and exit" }),
      async (argv) => {
        const { detectHosts } = await import("./cli/hosts")
        const detected = detectHosts(process.cwd())
        if (argv.listHosts) { console.log(`Detected: ${detected.join(", ") || "none"}\nSupported: ${HOSTS.join(", ")}`); return }
        let host = argv.host as Host | undefined
        if (!host && detected.length > 1) {
          const selected = prompt(`Select host (${detected.join(", ")}):`)
          host = selected as Host | undefined
          if (!host || !detected.includes(host)) throw new Error("Select one detected host with --host.")
        }
        if (!host && detected.length === 1) console.log(`Detected host: ${detected[0]}`)
        const result = initProject(process.cwd(), argv.force ?? false, host)
        console.log(`Initialized Shutong project in ${process.cwd()}`)
        if (result.written.length > 0) {
          console.log("wrote:")
          for (const item of result.written) console.log(`  ${item}`)
        } else {
          console.log("No files were written.")
        }
        if (result.warnings.length > 0) {
          console.log("warnings:")
          for (const item of result.warnings) console.log(`  ${item}`)
        }
      },
    )
    .command("setup", "Create or verify the per-user Shutong Python backend", () => {}, async () => {
      const result = setupBackend()
      console.log(result.detail)
      if (!result.ok) { process.exitCode = 1; return }
      console.log(`Python: ${result.python}`)
    })
    .command("paper <action> [id] [source]", "Create, use, inspect, audit, or add sources to a paper", (y) => y.positional("action", { choices: ["create", "add-source", "use", "status", "audit"] as const }).positional("id", { type: "string" }).positional("source", { type: "string" }).option("title", { type: "string" }).option("question", { type: "string" }).option("role", { choices: ["primary", "secondary", "unknown"] as const, default: "unknown" }), (argv) => {
      const root = process.cwd()
      const action = argv.action as string
      if (action === "create") {
        if (!argv.id || !argv.title) throw new Error("Usage: shutong paper create <id> --title <title>")
        console.log(`Created paper: ${createPaper(root, argv.id as string, argv.title as string, argv.question as string | undefined).id}`)
      } else if (action === "add-source") {
        if (!argv.id || !argv.source) throw new Error("Usage: shutong paper add-source <paper> <source> --role <role>")
        addPaperSource(root, argv.id as string, argv.source as string, argv.role as SourceRole)
        console.log(`Added ${argv.source} to ${argv.id} as ${argv.role}`)
      } else if (action === "use") {
        if (!argv.id) throw new Error("Usage: shutong paper use <id>")
        usePaper(root, argv.id as string)
        console.log(`Active paper: ${argv.id}`)
      } else if (action === "status") {
        console.log(JSON.stringify(paperStatus(root, argv.id as string | undefined) ?? { status: "no_active_paper" }, null, 2))
      } else {
        console.log(JSON.stringify(auditPaper(root, argv.id as string | undefined), null, 2))
      }
    })
    .command("doctor", "Diagnose launcher, project scaffold, Ollama, and backend health", () => {}, async () => {
      const failures = await runDoctor(process.cwd())
      process.exitCode = failures > 0 ? 1 : 0
    })
    .command("status", "Show engine status", () => {}, () => {
      runStatus(process.cwd())
    })
    .help()
    .parseAsync()
}

if (import.meta.main) {
  await run()
}
