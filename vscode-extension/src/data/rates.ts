/**
 * Cost-rate tables ported from the Python scripts.
 *
 * OTEL_RATE_HINTS + estOtelCost mirror otelmeter.py (USD per 1M tokens, in/out)
 * and are applied when a session's `cost` is 0 (no cost metric was emitted).
 */
import type { OtelModelAgg } from "../panel/protocol";

// otelmeter.py RATE_HINTS / DEFAULT_RATE
const OTEL_RATE_HINTS: Array<[string, [number, number]]> = [
  ["opus", [5.0, 25.0]],
  ["sonnet", [3.0, 15.0]],
  ["haiku", [1.0, 5.0]],
  ["gpt-4o", [2.5, 10.0]],
  ["gpt-4.1", [2.0, 8.0]],
  ["gpt-4.1-mini", [0.4, 1.6]],
  ["gpt-4o-mini", [0.15, 0.6]],
  ["grok-3", [3.0, 15.0]],
  ["deepseek", [1.35, 5.4]],
];
const OTEL_DEFAULT_RATE: [number, number] = [1.0, 3.0];

/**
 * Port of otelmeter.py est_cost(model, a). Returns [cost, estimated].
 * If an authoritative cost metric was captured (a.cost > 0) it is used as-is.
 */
export function estOtelCost(model: string, a: OtelModelAgg): [number, boolean] {
  if (a.cost) {
    return [a.cost, false];
  }
  const m = (model || "").toLowerCase();
  const hint = OTEL_RATE_HINTS.find(([key]) => m.includes(key));
  const rate = hint ? hint[1] : OTEL_DEFAULT_RATE;
  const cost = ((a.in + a.cr + a.cw) * rate[0]) / 1e6 + (a.out * rate[1]) / 1e6;
  return [cost, true];
}

// ---- Claude (tok.py CLAUDE_RATES / OPUS_LEGACY / rate_for) ----
// USD per 1M tokens: [input, output, cache_read, cache_write]
const CLAUDE_RATES: Record<string, [number, number, number, number]> = {
  opus: [5.0, 25.0, 0.5, 6.25],
  sonnet: [3.0, 15.0, 0.3, 3.75],
  haiku: [1.0, 5.0, 0.1, 1.25],
};
const OPUS_LEGACY: [number, number, number, number] = [15.0, 75.0, 1.5, 18.75];

/** Port of tok.py rate_for(model). Returns the rate tuple, or null for unknown models. */
export function rateForClaude(model: string): [number, number, number, number] | null {
  const m = (model || "").toLowerCase();
  if (m.includes("opus")) {
    return m.includes("4-1") || m.includes("4.1") ? OPUS_LEGACY : CLAUDE_RATES.opus;
  }
  if (m.includes("sonnet")) {
    return CLAUDE_RATES.sonnet;
  }
  if (m.includes("haiku")) {
    return CLAUDE_RATES.haiku;
  }
  return null;
}

/**
 * Cost for a Claude message. Mirrors tok.py: prefer the logged costUSD when
 * present, else compute from the rate table. Returns [cost, estimated].
 */
export function claudeCost(
  model: string,
  tin: number,
  tout: number,
  tcr: number,
  tcw: number,
  loggedCost: number | null | undefined,
): [number, boolean] {
  if (loggedCost !== null && loggedCost !== undefined) {
    return [Number(loggedCost), false];
  }
  const r = rateForClaude(model);
  if (!r) {
    return [0, true];
  }
  return [(tin * r[0] + tout * r[1] + tcr * r[2] + tcw * r[3]) / 1e6, true];
}
