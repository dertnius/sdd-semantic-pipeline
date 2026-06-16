/**
 * Claude root resolution, current-window→session mapping (by the verified `cwd`
 * field), and genuine-user-prompt extraction for the per-session drill-down.
 */
import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export interface SessionPrompt {
  promptId: string;
  iso: string | null;
  text: string;
  chars: number;
  bytes: number;
}

export function claudeRoot(configDir: string): string {
  if (configDir) {
    return configDir;
  }
  return process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
}

function normPath(p: string): string {
  return p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

/**
 * Newest session whose cwd matches the workspace folder. `sessions` is expected
 * newest-first (ClaudeReader sorts that way), so the first match wins.
 */
export function currentSessionId(
  sessions: Array<{ id: string; cwd: string | null }>,
  workspacePath: string | undefined,
): string | null {
  if (!workspacePath) {
    return null;
  }
  const w = normPath(workspacePath);
  const match = sessions.find((s) => s.cwd && normPath(s.cwd) === w);
  return match ? match.id : null;
}

/**
 * Extract the genuine user prompts from a session's jsonl file: type=="user",
 * not a tool result / meta / sidechain, content a plain string (not a slash
 * command) or text blocks. Parses the whole file — only called on drill-down.
 */
export async function readSessionPrompts(
  file: string,
  sessionId: string,
): Promise<SessionPrompt[]> {
  let text: string;
  try {
    text = await fs.readFile(file, "utf8");
  } catch {
    return [];
  }
  const out: SessionPrompt[] = [];
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    let rec: any;
    try {
      rec = JSON.parse(line);
    } catch {
      continue;
    }
    if (rec.type !== "user") {
      continue;
    }
    if (sessionId && rec.sessionId && rec.sessionId !== sessionId) {
      continue;
    }
    if (rec.isMeta || rec.isSidechain || "toolUseResult" in rec) {
      continue;
    }
    const c = (rec.message ?? {}).content;
    let value: string | null = null;
    if (typeof c === "string") {
      if (c.startsWith("<command") || c.startsWith("<local-command")) {
        continue;
      }
      value = c;
    } else if (Array.isArray(c)) {
      const texts = c
        .filter((b: any) => b && b.type === "text" && typeof b.text === "string")
        .map((b: any) => b.text as string);
      if (texts.length === 0) {
        continue;
      }
      value = texts.join("\n");
    }
    if (!value || !value.trim()) {
      continue;
    }
    const ts: string | null = rec.timestamp ?? null;
    out.push({
      promptId: rec.uuid ?? `${sessionId}:${out.length}`,
      iso: ts,
      text: value,
      chars: value.length,
      bytes: Buffer.byteLength(value, "utf8"),
    });
  }
  return out;
}
