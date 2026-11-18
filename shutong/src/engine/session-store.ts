import { mkdirSync, readFileSync, writeFileSync, readdirSync, existsSync } from "fs"
import path from "path"
import type { ChatMessage } from "../shared/types"

export interface SessionMeta {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messageCount: number
}

export class SessionStore {
  private sessionsDir: string

  constructor(storageRoot: string) {
    this.sessionsDir = path.join(storageRoot, "sessions")
    mkdirSync(this.sessionsDir, { recursive: true })
  }

  private sessionPath(sessionId: string): string {
    const safe = sessionId.replace(/[^a-zA-Z0-9\-_]/g, "_")
    return path.join(this.sessionsDir, `${safe}.json`)
  }

  private metaPath(): string {
    return path.join(this.sessionsDir, "_index.json")
  }

  /** Save a session's messages. Creates the session if it doesn't exist. */
  save(sessionId: string, messages: ChatMessage[], title?: string): void {
    const filePath = this.sessionPath(sessionId)
    const now = Date.now()

    const existing = this.loadMeta(sessionId)
    const meta: SessionMeta = {
      id: sessionId,
      title: title ?? existing?.title ?? this.autoTitle(messages),
      createdAt: existing?.createdAt ?? now,
      updatedAt: now,
      messageCount: messages.length,
    }

    writeFileSync(filePath, JSON.stringify({ meta, messages }, null, 2), "utf-8")
    this.updateIndex(sessionId, meta)
  }

  /** Load a session's messages. Returns empty array if not found. */
  load(sessionId: string): ChatMessage[] {
    const filePath = this.sessionPath(sessionId)
    if (!existsSync(filePath)) return []

    try {
      const data = JSON.parse(readFileSync(filePath, "utf-8"))
      return data.messages ?? []
    } catch {
      return []
    }
  }

  /** Load a session's metadata. */
  loadMeta(sessionId: string): SessionMeta | null {
    const filePath = this.sessionPath(sessionId)
    if (!existsSync(filePath)) return null

    try {
      const data = JSON.parse(readFileSync(filePath, "utf-8"))
      return data.meta ?? null
    } catch {
      return null
    }
  }

  /** List all sessions, most recently updated first. */
  list(): SessionMeta[] {
    const indexPath = this.metaPath()
    if (!existsSync(indexPath)) return []

    try {
      const data = JSON.parse(readFileSync(indexPath, "utf-8"))
      const sessions: SessionMeta[] = data.sessions ?? []
      return sessions.sort((a: SessionMeta, b: SessionMeta) => b.updatedAt - a.updatedAt)
    } catch {
      return []
    }
  }

  /** Delete a session. */
  delete(sessionId: string): void {
    const filePath = this.sessionPath(sessionId)
    if (existsSync(filePath)) {
      const { unlinkSync } = require("fs")
      unlinkSync(filePath)
    }
    this.removeFromIndex(sessionId)
  }

  /** Generate a new unique session ID. */
  createId(): string {
    return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  }

  private autoTitle(messages: ChatMessage[]): string {
    const first = messages.find((m) => m.role === "user")
    if (!first) return "New session"
    const text = first.content.slice(0, 60).replace(/\n/g, " ")
    return text.length < first.content.length ? `${text}…` : text
  }

  private updateIndex(sessionId: string, meta: SessionMeta): void {
    const sessions = this.list().filter((s) => s.id !== sessionId)
    sessions.unshift(meta)

    // Keep only last 100 sessions in the index
    const trimmed = sessions.slice(0, 100)
    writeFileSync(this.metaPath(), JSON.stringify({ sessions: trimmed }, null, 2), "utf-8")
  }

  private removeFromIndex(sessionId: string): void {
    const sessions = this.list().filter((s) => s.id !== sessionId)
    writeFileSync(this.metaPath(), JSON.stringify({ sessions }, null, 2), "utf-8")
  }
}
