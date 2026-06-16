/**
 * Reads Claude Code per-message logs (the `<root>/projects` jsonl tree) into a
 * global aggregate + per-session summaries. Port of tok.py parse_claude, with
 * per-session grouping and a per-file (mtime,size) cache so repeated status-bar
 * refreshes only re-parse files that changed.
 *
 * Dedup is per-file by (message.id, requestId); in practice a given message id
 * lives in exactly one session file, so this matches tok.py's global dedup.
 */
import { promises as fs } from "node:fs";
import * as path from "node:path";
import { claudeCost } from "./rates";

export interface ClaudeModelAgg {
  in: number;
  out: number;
  cr: number;
  cw: number;
  cost: number;
  msgs: number;
}
export interface ClaudeDaily {
  cost: number;
  tokens: number;
}
export interface ClaudeSessionSummary {
  id: string;
  file: string;
  cwd: string | null;
  gitBranch: string | null;
  slug: string | null;
  first: number | null; // epoch ms
  last: number | null; // epoch ms
  models: Record<string, ClaudeModelAgg>;
  tokens: number;
  cost: number;
  costEstimated: boolean;
  msgs: number;
}
export interface ClaudeUsage {
  total: ClaudeModelAgg;
  models: Record<string, ClaudeModelAgg>;
  daily: Record<string, ClaudeDaily>;
  sessions: ClaudeSessionSummary[];
}

interface RawSession {
  file: string;
  cwd: string | null;
  gitBranch: string | null;
  slug: string | null;
  first: number | null;
  last: number | null;
  msgs: number;
  costEstimated: boolean;
  models: Record<string, ClaudeModelAgg>;
  daily: Record<string, ClaudeDaily>;
}
interface FileParse {
  sessions: Record<string, RawSession>;
}

const blankAgg = (): ClaudeModelAgg => ({ in: 0, out: 0, cr: 0, cw: 0, cost: 0, msgs: 0 });
const intOf = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? Math.trunc(n) : 0;
};

function parseFileText(file: string, text: string): FileParse {
  const sessions: Record<string, RawSession> = {};
  const seen = new Set<string>();
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line || !line.includes('"usage"')) {
      continue;
    }
    let rec: any;
    try {
      rec = JSON.parse(line);
    } catch {
      continue;
    }
    const msg = rec.message ?? {};
    const usage = msg.usage ?? null;
    if (!usage) {
      continue;
    }
    const mid: string | undefined = msg.id;
    const reqid: string | undefined = rec.requestId ?? rec.request_id;
    const key = `${mid}|${reqid}`;
    if (mid && seen.has(key)) {
      continue;
    }
    if (mid) {
      seen.add(key);
    }
    const model: string = msg.model ?? rec.model ?? "unknown";
    if (model === "<synthetic>" || model === "synthetic") {
      continue;
    }
    const tin = intOf(usage.input_tokens);
    const tout = intOf(usage.output_tokens);
    const tcr = intOf(usage.cache_read_input_tokens);
    const tcw = intOf(usage.cache_creation_input_tokens);
    if (tin + tout + tcr + tcw === 0) {
      continue;
    }
    const tsStr: string = String(rec.timestamp ?? msg.timestamp ?? "");
    const day = tsStr.slice(0, 10) || "?";
    const ms = tsStr ? Date.parse(tsStr) : NaN;
    const ts = Number.isFinite(ms) ? ms : null;
    const logged = rec.costUSD ?? msg.costUSD ?? null;
    const [cost, estimated] = claudeCost(model, tin, tout, tcr, tcw, logged);

    const sid: string = rec.sessionId ?? path.basename(file, ".jsonl");
    const S = (sessions[sid] ??= {
      file,
      cwd: null,
      gitBranch: null,
      slug: null,
      first: null,
      last: null,
      msgs: 0,
      costEstimated: false,
      models: {},
      daily: {},
    });
    if (rec.cwd) S.cwd = rec.cwd;
    if (rec.gitBranch) S.gitBranch = rec.gitBranch;
    if (rec.slug) S.slug = rec.slug;
    if (ts !== null) {
      S.first = S.first === null ? ts : Math.min(S.first, ts);
      S.last = S.last === null ? ts : Math.max(S.last, ts);
    }
    S.msgs += 1;
    S.costEstimated = S.costEstimated || estimated;
    const a = (S.models[model] ??= blankAgg());
    a.in += tin;
    a.out += tout;
    a.cr += tcr;
    a.cw += tcw;
    a.cost += cost;
    a.msgs += 1;
    const d = (S.daily[day] ??= { cost: 0, tokens: 0 });
    d.cost += cost;
    d.tokens += tin + tout + tcr + tcw;
  }
  return { sessions };
}

async function walkJsonl(dir: string): Promise<string[]> {
  const out: string[] = [];
  let entries: import("node:fs").Dirent[];
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      out.push(...(await walkJsonl(full)));
    } else if (e.isFile() && e.name.endsWith(".jsonl")) {
      out.push(full);
    }
  }
  return out;
}

export class ClaudeReader {
  private cache = new Map<string, { mtimeMs: number; size: number; parse: FileParse }>();

  async read(root: string): Promise<ClaudeUsage> {
    const projDir = path.join(root, "projects");
    const files = await walkJsonl(projDir);
    const parses: FileParse[] = [];
    for (const file of files) {
      try {
        const st = await fs.stat(file);
        const hit = this.cache.get(file);
        if (hit && hit.mtimeMs === st.mtimeMs && hit.size === st.size) {
          parses.push(hit.parse);
          continue;
        }
        const text = await fs.readFile(file, "utf8");
        const parse = parseFileText(file, text);
        this.cache.set(file, { mtimeMs: st.mtimeMs, size: st.size, parse });
        parses.push(parse);
      } catch {
        /* skip unreadable file */
      }
    }
    return merge(parses);
  }
}

function mergeAgg(dst: ClaudeModelAgg, src: ClaudeModelAgg): void {
  dst.in += src.in;
  dst.out += src.out;
  dst.cr += src.cr;
  dst.cw += src.cw;
  dst.cost += src.cost;
  dst.msgs += src.msgs;
}

function merge(parses: FileParse[]): ClaudeUsage {
  const total = blankAgg();
  const models: Record<string, ClaudeModelAgg> = {};
  const daily: Record<string, ClaudeDaily> = {};
  // Group sessions by sessionId GLOBALLY (a logical session can span files —
  // e.g. sidechains), matching tok.py's distinct-sessionId count.
  const bySid = new Map<string, ClaudeSessionSummary>();

  for (const p of parses) {
    for (const [sid, S] of Object.entries(p.sessions)) {
      for (const [model, a] of Object.entries(S.models)) {
        mergeAgg((models[model] ??= blankAgg()), a);
        mergeAgg(total, a);
      }
      for (const [day, d] of Object.entries(S.daily)) {
        const gd = (daily[day] ??= { cost: 0, tokens: 0 });
        gd.cost += d.cost;
        gd.tokens += d.tokens;
      }
      let M = bySid.get(sid);
      if (!M) {
        M = {
          id: sid,
          file: S.file,
          cwd: null,
          gitBranch: null,
          slug: null,
          first: null,
          last: null,
          models: {},
          tokens: 0,
          cost: 0,
          costEstimated: false,
          msgs: 0,
        };
        bySid.set(sid, M);
      }
      // representative file for prompt drill-down: prefer the file named by sid
      const stem = path.basename(S.file, ".jsonl");
      if (stem === sid || (M.file !== `${sid}.jsonl` && (S.last ?? 0) > (M.last ?? 0))) {
        M.file = S.file;
      }
      if (!M.cwd && S.cwd) M.cwd = S.cwd;
      if (!M.gitBranch && S.gitBranch) M.gitBranch = S.gitBranch;
      if (!M.slug && S.slug) M.slug = S.slug;
      if (S.first !== null) M.first = M.first === null ? S.first : Math.min(M.first, S.first);
      if (S.last !== null) M.last = M.last === null ? S.last : Math.max(M.last, S.last);
      M.msgs += S.msgs;
      M.costEstimated = M.costEstimated || S.costEstimated;
      for (const [model, a] of Object.entries(S.models)) {
        mergeAgg((M.models[model] ??= blankAgg()), a);
      }
    }
  }

  const sessions = [...bySid.values()].map((M) => {
    let tokens = 0;
    let cost = 0;
    for (const a of Object.values(M.models)) {
      tokens += a.in + a.out + a.cr + a.cw;
      cost += a.cost;
    }
    M.tokens = tokens;
    M.cost = cost;
    return M;
  });
  sessions.sort((a, b) => (b.last ?? 0) - (a.last ?? 0));
  return { total, models, daily, sessions };
}
