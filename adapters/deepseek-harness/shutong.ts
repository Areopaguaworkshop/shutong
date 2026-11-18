// Shutong adapter for DeepSeek Harness (deepseek-ai/deepseek-harness).
//
// DeepSeek Harness is a Cordis-based "everything is a plugin" harness in
// developer preview (breaking changes expected). This adapter bridges the
// Shutong Python backend to the harness by spawning the NDJSON RPC server
// (python -m shutong_backend.rpc_server) and registering model-facing tools
// that forward to it.
//
// NOTE: targets the dev-preview Cordis API. Verify against the installed
// @deepseek-ai/cordis version before relying on it — the tool/agent registry
// surface may have shifted.

import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'

const PYTHON = process.env.SHUTONG_PYTHON || 'python3'
const RPC_MODULE = 'shutong_backend.rpc_server'

// ── NDJSON RPC bridge ────────────────────────────────────────────────

let rpc: ReturnType<typeof spawn> | null = null
let rpcLines: ReturnType<typeof createInterface> | null = null
let nextId = 0
const pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>()

function ensureRpc() {
  if (rpc) return
  rpc = spawn(PYTHON, ['-m', RPC_MODULE], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      SHUTONG_CORPUS_ROOT: process.env.SHUTONG_CORPUS_ROOT || './corpus',
      SHUTONG_STORAGE_DIR: process.env.SHUTONG_STORAGE_DIR || './.shutong',
    },
  })
  rpcLines = createInterface({ input: rpc.stdout! })
  rpcLines.on('line', (line) => {
    const msg = JSON.parse(line)
    const p = pending.get(msg.id)
    if (!p) return
    pending.delete(msg.id)
    if (msg.error) p.reject(new Error(msg.error.message))
    else p.resolve(msg.result)
  })
  rpc.stderr!.on('data', () => {}) // swallow; errors surface via response
}

function call(method: string, params: Record<string, unknown> = {}): Promise<any> {
  ensureRpc()
  const id = ++nextId
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    rpc!.stdin!.write(JSON.stringify({ id, method, params }) + '\n')
  })
}

// ── Plugin ───────────────────────────────────────────────────────────

export const name = 'shutong'
export const inject = ['tools', 'systemPrompt', 'agent']

export function apply(ctx: any) {
  // Model-facing tools — bridge to the Python backend.
  const tools = [
    {
      name: 'shutong_search',
      description: 'BM25 keyword search over the local academic corpus.',
      parameters: {
        query: { type: 'string', required: true, description: 'Search query' },
        top_k: { type: 'number', description: 'Max results (default 20)' },
      },
      async execute(args: any) {
        const r = await call('search', { query: args.query, top_k: args.top_k ?? 20 })
        return JSON.stringify(r)
      },
    },
    {
      name: 'shutong_verify',
      description: 'Verify Merkle integrity of a corpus citation.',
      parameters: {
        csl_id: { type: 'string', required: true, description: 'Source id' },
        node_hash: { type: 'string', description: 'Optional node hash' },
      },
      async execute(args: any) {
        const r = await call('verify_document', { csl_id: args.csl_id, node_hash: args.node_hash })
        return JSON.stringify(r)
      },
    },
    {
      name: 'shutong_pipeline',
      description: 'Run the academic pipeline (research → outline → draft → style → quality → review).',
      parameters: {
        topic: { type: 'string', required: true, description: 'Research topic' },
        mode: { type: 'string', description: 'research|outline|draft|review|full' },
        skip_checkpoints: { type: 'boolean', description: 'Run straight through' },
      },
      async execute(args: any) {
        const r = await call('pipeline', {
          topic: args.topic,
          mode: args.mode ?? 'full',
          skip_checkpoints: args.skip_checkpoints ?? false,
        })
        return JSON.stringify(r)
      },
    },
    {
      name: 'shutong_state_wake_up',
      description: 'Load cross-session research context (passport, diary, graph).',
      parameters: {},
      async execute() {
        const r = await call('state_wake_up', {})
        return r.context ?? ''
      },
    },
    {
      name: 'shutong_status',
      description: 'Corpus health, integrity, and research state in one call.',
      parameters: {},
      async execute() {
        const r = await call('state_snapshot', {})
        return JSON.stringify(r)
      },
    },
  ]

  for (const t of tools) {
    ctx.tools.register(t)
  }

  // Scholar Principle as a system-prompt section.
  ctx.systemPrompt.register({
    id: 'shutong-scholar-principle',
    content:
      'Never state a fact without a citation. Every factual claim must trace to a corpus source. ' +
      'If no citation is available, say exactly: "No citation available for this claim in the current corpus." ' +
      'Citation format: Chicago author-date — (Author Year, page).',
  })

  // Wake-up context injection at session start.
  ctx.agent.on('session/start', async () => {
    try {
      const context = await call('state_wake_up', {})
      if (context?.context) {
        ctx.agent.inject({ content: context.context, source: 'shutong' })
      }
    } catch {
      // corpus may be empty; ignore
    }
  })
}
