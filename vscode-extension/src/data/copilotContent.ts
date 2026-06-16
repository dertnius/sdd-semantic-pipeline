/**
 * Reads the OTel content JSONL the sidecar writes (otelmeter.py --capture-content)
 * into per-session user prompts, for the Copilot drill-down. Each line:
 *   {session, ts, model, response_id, input, output, system}
 * `input` is Copilot's gen_ai.input.messages — a JSON string of chat messages, or
 * plain text. We extract the user-role text.
 */
import { promises as fs } from "node:fs";
import type { SessionPrompt } from "./sessionIndex";

function extractFromMessages(m: unknown): string {
  if (Array.isArray(m)) {
    const parts: string[] = [];
    for (const msg of m as any[]) {
      const role = msg?.role;
      if (role && role !== "user") {
        continue; // prompts = user-authored messages
      }
      const c = msg?.content;
      if (typeof c === "string") {
        parts.push(c);
      } else if (Array.isArray(c)) {
        parts.push(c.map((b: any) => (typeof b === "string" ? b : (b?.text ?? ""))).join(""));
      }
    }
    return parts.join("\n");
  }
  if (m && typeof m === "object" && typeof (m as any).content === "string") {
    return (m as any).content;
  }
  return typeof m === "string" ? m : "";
}

function extractText(input: unknown): string {
  if (typeof input === "string") {
    const s = input.trim();
    if (s.startsWith("[") || s.startsWith("{")) {
      try {
        return extractFromMessages(JSON.parse(s));
      } catch {
        return input;
      }
    }
    return input;
  }
  return extractFromMessages(input);
}

export async function readCopilotPrompts(path: string): Promise<Map<string, SessionPrompt[]>> {
  let text: string;
  try {
    text = await fs.readFile(path, "utf8");
  } catch {
    return new Map();
  }
  const bySession = new Map<string, SessionPrompt[]>();
  let i = 0;
  for (const line of text.split("\n")) {
    const l = line.trim();
    if (!l) {
      continue;
    }
    let rec: any;
    try {
      rec = JSON.parse(l);
    } catch {
      continue;
    }
    if (rec.input == null) {
      continue;
    }
    const t = extractText(rec.input);
    if (!t || !t.trim()) {
      continue;
    }
    const sid = rec.session || "unknown";
    const iso =
      typeof rec.ts === "number"
        ? new Date(rec.ts > 1e12 ? rec.ts : rec.ts * 1000).toISOString()
        : null;
    const arr = bySession.get(sid) ?? [];
    arr.push({
      promptId: `${sid}:${i++}`,
      iso,
      text: t,
      chars: t.length,
      bytes: Buffer.byteLength(t, "utf8"),
    });
    bySession.set(sid, arr);
  }
  return bySession;
}
