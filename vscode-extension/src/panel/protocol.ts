/**
 * Shared data contracts between the extension host and the webview.
 *
 * The webview script (media/dashboard.js) is hand-written plain JS and mirrors
 * these shapes by convention; the host imports them as real types.
 */

// ---- Config-derived unions (kept here so pure data modules avoid importing config/vscode) ----

export type Scope = "global" | "newestSession";
export type Metric = "cost" | "tokens" | "both";

// ---- Copilot billing CSV (mirrors tok.py parse_copilot --json) ----

export interface CopilotModelAgg {
  net: number;
  gross: number;
  disc: number;
  qty: number;
  rows: number;
  billed_qty: number;
}

export interface CopilotDaily {
  net: number;
  qty: number;
}

export interface CopilotReport {
  source: "copilot";
  csv?: string;
  since: string | null;
  until: string | null;
  total: CopilotModelAgg;
  users: string[];
  models: Record<string, CopilotModelAgg>;
  daily: Record<string, CopilotDaily>;
}

// ---- Live OTel snapshot (mirrors otelmeter.py --save) ----

export interface OtelModelAgg {
  in: number;
  out: number;
  cr: number;
  cw: number;
  cost: number;
}

export interface OtelSession {
  models: Record<string, OtelModelAgg>;
  first: number | null;
  last: number | null;
}

export interface OtelSnapshot {
  sessions: Record<string, OtelSession>;
}

// ---- Derived view models ----

export interface SessionModelLine {
  model: string;
  tokens: number;
  in: number;
  out: number;
  cr: number;
  cw: number;
  cost: number;
  estimated: boolean;
}

export interface SessionSummary {
  id: string;
  shortId: string;
  last: number | null;
  lastIso: string | null;
  tokens: number;
  cost: number;
  costEstimated: boolean;
  models: SessionModelLine[];
}

export interface LiveView {
  available: boolean;
  running: boolean;
  postsSeen: boolean;
  contentAvailable: boolean;
  sessions: SessionSummary[];
  totalTokens: number;
  totalCost: number;
  sessionCount: number;
}

export interface BillingView {
  available: boolean;
  importedAt: string | null;
  csvName: string | null;
  report: CopilotReport | null;
}

// ---- Claude (from ~/.claude/projects/**/*.jsonl) ----

export interface ClaudeSessionView {
  id: string;
  shortId: string;
  cwd: string | null;
  gitBranch: string | null;
  last: number | null;
  lastIso: string | null;
  tokens: number;
  cost: number;
  costEstimated: boolean;
  msgs: number;
  models: SessionModelLine[];
  isCurrent: boolean;
}

export interface ClaudeView {
  available: boolean;
  sessions: ClaudeSessionView[];
  modelTotals: Record<string, { tokens: number; cost: number }>;
  daily: Record<string, { cost: number; tokens: number }>;
  totalTokens: number;
  totalCost: number;
  costEstimated: boolean;
  sessionCount: number;
  currentSessionId: string | null;
}

export interface PromptItem {
  promptId: string;
  iso: string | null;
  text: string;
  chars: number;
  bytes: number;
  tokenCount: number;
}

export interface GhUsageSummary {
  fetchedAt: string;
  scope: "user" | "org";
  account: string;
  period: string;
  totalNet: number;
  totalGross: number;
  copilotNet: number;
  copilotGross: number;
  byProduct: Record<string, { net: number; gross: number }>;
  itemCount: number;
}

export interface DashboardSnapshot {
  generatedAt: string;
  source: "copilot" | "claude";
  scope: "global" | "newestSession";
  mode: "live" | "billing" | "claude" | "empty";
  statusText: string;
  live: LiveView;
  billing: BillingView;
  claude: ClaudeView | null;
  apiUsage: GhUsageSummary | null;
}

// ---- Tokenizer ----

export interface TokenChunk {
  id: number;
  text: string;
  start: number;
  end: number;
  /** how many BPE tokens this visual chunk spans (>1 only when a codepoint splits across tokens) */
  merged?: number;
}

export interface TokenizeResult {
  tokens: TokenChunk[];
  count: number;
  chars: number;
  bytes: number;
  encoder: "o200k" | "heuristic";
  model: string;
  note?: string;
}

// ---- Messages ----

export type HostMessage =
  | { type: "snapshot"; payload: DashboardSnapshot }
  | { type: "tokenized"; payload: TokenizeResult }
  | { type: "prompts"; sessionId: string; items: PromptItem[] }
  | { type: "layout"; grid: unknown }
  | { type: "error"; message: string };

export type ViewCommand =
  | "downloadBilling"
  | "importCsv"
  | "setupOtel"
  | "startOtel"
  | "stopOtel"
  | "printOtelConfig";

export type ViewMessage =
  | { type: "ready" }
  | { type: "refresh" }
  | { type: "tokenize"; text: string; model: string }
  | { type: "requestPrompts"; sessionId: string }
  | { type: "saveLayout"; grid: unknown }
  | { type: "runCommand"; command: ViewCommand };
