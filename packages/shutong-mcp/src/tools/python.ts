import { spawnSync } from "node:child_process";

export function pythonBin(): string {
  return process.env.SHUTONG_PYTHON ?? "python3";
}

/**
 * Serialize note frontmatter with PyYAML so note_digest stays byte-compatible
 * with notes written by the Python backend. The npm YAML emitter differs in
 * quoting and line folding, which would break every claim digest.
 */
export function serializeNote(metadata: Record<string, unknown>, body: string): string {
  const script =
    "import json,sys,yaml; " +
    "data=json.load(sys.stdin); " +
    "sys.stdout.write(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False))";
  const result = spawnSync(pythonBin(), ["-c", script], {
    input: JSON.stringify(metadata),
    encoding: "utf8",
    maxBuffer: 1024 * 1024,
  });
  if (result.error || result.status !== 0) {
    const detail = result.stderr?.trim() || result.error?.message || "unknown error";
    throw new Error(`note frontmatter serializer failed: ${detail}`);
  }
  return `---\n${result.stdout}---\n${body}`;
}
