import { cpSync, existsSync, lstatSync, rmSync } from "fs"
import path from "path"

const source = path.resolve(import.meta.dir, "../../packages/shutong-backend")
const target = path.resolve(import.meta.dir, "../python-backend")
if (!existsSync(path.join(source, "pyproject.toml"))) throw new Error(`Backend source not found: ${source}`)
rmSync(target, { recursive: true, force: true })
cpSync(source, target, {
  recursive: true,
  filter: (entry) => {
    const relative = path.relative(source, entry).split(path.sep).join("/")
    const stat = lstatSync(entry)
    if (stat.isSymbolicLink() || relative.split("/").some((part) => part.startsWith(".") || part === "__pycache__")) return false
    if (!relative || relative === "pyproject.toml" || relative === "README.md") return true
    if (!relative.startsWith("shutong_backend/") && relative !== "shutong_backend") return false
    if (stat.isDirectory()) return true
    return relative.endsWith(".py") || /^shutong_backend\/templates\/.*\.(md|json|j2)$/.test(relative)
  },
})
