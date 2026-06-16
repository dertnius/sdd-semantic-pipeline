/** Number/money formatting ported from tok.py (human / money). */

export function humanTokens(n: number): string {
  const v = Number(n) || 0;
  if (v >= 1e6) {
    return `${(v / 1e6).toFixed(1)}M`;
  }
  if (v >= 1e3) {
    return `${(v / 1e3).toFixed(1)}k`;
  }
  return String(Math.round(v));
}

export function money(v: number): string {
  const n = Number(v) || 0;
  if (n > 0 && Math.abs(n) < 1) {
    return `$${n.toFixed(4)}`;
  }
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
