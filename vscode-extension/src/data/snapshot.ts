/**
 * Builds the DashboardSnapshot + status-bar text.
 *
 * source=copilot: live OTel (when the sidecar has captured sessions) else the
 * imported billing snapshot. source=claude: per-session usage read from the
 * ~/.claude/projects jsonl tree (passed in as ClaudeUsage).
 */
import type {
  DashboardSnapshot,
  BillingView,
  ClaudeView,
  ClaudeSessionView,
  SessionModelLine,
  Metric,
  Scope,
} from "../panel/protocol";
import type { Store } from "./store";
import type { OtelSidecar } from "./otelSidecar";
import type { MonitorConfig } from "../config";
import type { ClaudeUsage } from "./claudeReader";
import { buildLiveView, emptyLiveView } from "./otelSnapshot";
import { currentSessionId } from "./sessionIndex";
import { humanTokens, money } from "../format";

export interface SnapshotInput {
  store: Store;
  sidecar: OtelSidecar;
  cfg: MonitorConfig;
  claudeUsage?: ClaudeUsage | null;
  workspacePath?: string;
}

export async function buildSnapshot(input: SnapshotInput): Promise<DashboardSnapshot> {
  const { store, sidecar, cfg } = input;
  const billingRec = await store.loadBilling();
  const billing: BillingView = {
    available: !!billingRec,
    importedAt: billingRec?.importedAt ?? null,
    csvName: billingRec?.csvName ?? null,
    report: billingRec?.report ?? null,
  };
  const apiUsage = await store.loadGhUsage();

  if (cfg.source === "claude") {
    const claude = buildClaudeView(input.claudeUsage ?? null, input.workspacePath, cfg.scope);
    const mode: DashboardSnapshot["mode"] = claude.available ? "claude" : "empty";
    return {
      generatedAt: new Date().toISOString(),
      source: "claude",
      scope: cfg.scope,
      mode,
      statusText: formatClaudeStatus(mode, cfg.metric, claude),
      live: emptyLiveView(),
      billing,
      claude,
      apiUsage,
    };
  }

  // copilot
  const running = await sidecar.isRunning();
  const raw = await store.readOtelSnapshotRaw();
  const live = buildLiveView(raw, cfg.scope, running);
  live.contentAvailable = await store.hasOtelContent();
  const mode: DashboardSnapshot["mode"] = live.postsSeen
    ? "live"
    : billing.available
      ? "billing"
      : "empty";
  return {
    generatedAt: new Date().toISOString(),
    source: "copilot",
    scope: cfg.scope,
    mode,
    statusText: formatCopilotStatus(mode, cfg.metric, live, billing),
    live,
    billing,
    claude: null,
    apiUsage,
  };
}

// ---- Claude view ----

function isoOf(ms: number | null): string | null {
  if (!ms) {
    return null;
  }
  try {
    return new Date(ms).toISOString();
  } catch {
    return null;
  }
}

export function buildClaudeView(
  usage: ClaudeUsage | null,
  workspacePath: string | undefined,
  scope: Scope,
): ClaudeView {
  if (!usage || usage.sessions.length === 0) {
    return {
      available: false,
      sessions: [],
      modelTotals: {},
      daily: {},
      totalTokens: 0,
      totalCost: 0,
      costEstimated: false,
      sessionCount: 0,
      currentSessionId: null,
    };
  }
  const currentId = currentSessionId(usage.sessions, workspacePath);

  const sessions: ClaudeSessionView[] = usage.sessions.map((s) => {
    const models: SessionModelLine[] = Object.entries(s.models)
      .map(([model, a]) => ({
        model,
        tokens: a.in + a.out + a.cr + a.cw,
        in: a.in,
        out: a.out,
        cr: a.cr,
        cw: a.cw,
        cost: a.cost,
        estimated: s.costEstimated,
      }))
      .sort((x, y) => y.tokens - x.tokens);
    return {
      id: s.id,
      shortId: s.id.slice(0, 8),
      cwd: s.cwd,
      gitBranch: s.gitBranch,
      last: s.last,
      lastIso: isoOf(s.last),
      tokens: s.tokens,
      cost: s.cost,
      costEstimated: s.costEstimated,
      msgs: s.msgs,
      models,
      isCurrent: s.id === currentId,
    };
  });

  const modelTotals: Record<string, { tokens: number; cost: number }> = {};
  for (const [model, a] of Object.entries(usage.models)) {
    modelTotals[model] = { tokens: a.in + a.out + a.cr + a.cw, cost: a.cost };
  }

  let totalTokens: number;
  let totalCost: number;
  if (scope === "newestSession") {
    const cur = sessions.find((s) => s.isCurrent) ?? sessions[0];
    totalTokens = cur.tokens;
    totalCost = cur.cost;
  } else {
    totalTokens = usage.total.in + usage.total.out + usage.total.cr + usage.total.cw;
    totalCost = usage.total.cost;
  }

  return {
    available: true,
    sessions,
    modelTotals,
    daily: usage.daily,
    totalTokens,
    totalCost,
    costEstimated: sessions.some((s) => s.costEstimated),
    sessionCount: sessions.length,
    currentSessionId: currentId,
  };
}

// ---- status text ----

function formatCopilotStatus(
  mode: DashboardSnapshot["mode"],
  metric: Metric,
  live: DashboardSnapshot["live"],
  billing: BillingView,
): string {
  if (mode === "live") {
    const tok = `${humanTokens(live.totalTokens)} tok`;
    const cost = `~${money(live.totalCost)}`;
    if (metric === "tokens") return tok;
    if (metric === "cost") return cost;
    return `${tok} · ${cost}`;
  }
  if (mode === "billing" && billing.report) {
    const t = billing.report.total;
    const cost = money(t.net);
    const req = `${humanTokens(t.qty)} req`;
    if (metric === "tokens") return req;
    if (metric === "cost") return cost;
    return `${cost} · ${req}`;
  }
  return "no usage data";
}

function formatClaudeStatus(
  mode: DashboardSnapshot["mode"],
  metric: Metric,
  claude: ClaudeView,
): string {
  if (mode !== "claude") {
    return "no usage data";
  }
  const tok = `${humanTokens(claude.totalTokens)} tok`;
  const cost = `${claude.costEstimated ? "~" : ""}${money(claude.totalCost)}`;
  if (metric === "tokens") return tok;
  if (metric === "cost") return cost;
  return `${tok} · ${cost}`;
}
