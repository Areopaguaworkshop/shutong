import { mkdirSync, existsSync } from "fs"
import path from "path"

export class StorageLayout {
  readonly root: string
  readonly documents_dir: string
  readonly sources_dir: string
  readonly sessions_dir: string
  readonly memory_dir: string

  constructor(storageRoot: string) {
    this.root = storageRoot
    this.documents_dir = path.join(storageRoot, "documents")
    this.sources_dir = path.join(storageRoot, "documents", "sources")
    this.sessions_dir = path.join(storageRoot, "memory", "sessions")
    this.memory_dir = path.join(storageRoot, "memory")

    mkdirSync(this.documents_dir, { recursive: true })
    mkdirSync(this.sources_dir, { recursive: true })
    mkdirSync(this.sessions_dir, { recursive: true })
  }

  init(): void {
    // Create all directories
    mkdirSync(this.documents_dir, { recursive: true })
    mkdirSync(this.sources_dir, { recursive: true })
    mkdirSync(this.sessions_dir, { recursive: true })
  }

  isBootstrapped(): boolean {
    return existsSync(path.join(this.root, "legacy_bootstrap_complete.json"))
  }
}