/**
 * Pure transform: the JSON that `otelmeter.py --save` writes -> a LiveView the
 * status bar and dashboard consume. Applies the same cost estimation as
 * otelmeter.py (estOtelCost) so the numbers match `python otelmeter.py --report`.
 */
import type {
  OtelSnapshot,
  OtelSession,
  LiveView,
  SessionSummary,
  SessionModelLine,
  Scope,
} from "../panel/protocol";
import { estOtelCost } from "./rates";

export function emptyLiveView(): LiveView {
  return {
    available: false,
    running: false,
    postsSeen: false,
    contentAvailable: false,
    sessions: [],
    totalTokens: 0,
    totalCost: 0,
    sessionCount: 0,
  };
}

function tsToIso(ts: number | null): string | null {
  if (!ts) {
    return null;
  }
  // otelmeter normalizes to seconds, but guard against ms just in case.
  const ms = ts > 1e12 ? ts : ts * 1000;
  try {
    return new Date(ms).toISOString();
  } catch {
    return null;
  }
}

function summarizeSession(id: string, s: OtelSession): SessionSummary {
  const lines: SessionModelLine[] = [];
  let tokens = 0;
  let cost = 0;
  let anyEstimated = false;
  for (const [model, a] of Object.entries(s.models ?? {})) {
    const mt = a.in + a.out + a.cr + a.cw;
    const [c, estimated] = estOtelCost(model, a);
    tokens += mt;
    cost += c;
    anyEstimated = anyEstimated || estimated;
    lines.push({
      model,
      tokens: mt,
      in: a.in,
      out: a.out,
      cr: a.cr,
      cw: a.cw,
      cost: c,
      estimated,
    });
  }
  lines.sort((x, y) => y.tokens - x.tokens);
  return {
    id,
    shortId: id.slice(0, 12),
    last: s.last ?? null,
    lastIso: tsToIso(s.last ?? null),
    tokens,
    cost,
    costEstimated: anyEstimated,
    models: lines,
  };
}

/**
 * @param raw  contents of otel.json (or null if absent)
 * @param scope global -> totals over all sessions; newestSession -> newest only
 * @param running whether the sidecar process/owner is currently alive
 */
export function buildLiveView(
  raw: string | null,
  scope: Scope,
  running: boolean,
): LiveView {
  const view = emptyLiveView();
  view.running = running;
  if (!raw) {
    return view;
  }
  let snap: OtelSnapshot;
  try {
    snap = JSON.parse(raw) as OtelSnapshot;
  } catch {
    return view;
  }
  const sessions = Object.entries(snap.sessions ?? {}).map(([id, s]) =>
    summarizeSession(id, s),
  );
  sessions.sort((a, b) => (b.last ?? 0) - (a.last ?? 0));

  view.available = true;
  view.postsSeen = sessions.length > 0;
  view.sessions = sessions;
  view.sessionCount = sessions.length;

  const scoped = scope === "newestSession" ? sessions.slice(0, 1) : sessions;
  view.totalTokens = scoped.reduce((acc, s) => acc + s.tokens, 0);
  view.totalCost = scoped.reduce((acc, s) => acc + s.cost, 0);
  return view;
}
