/**
 * TypeScript port of tok.py `parse_copilot` — parses a GitHub Copilot
 * "Premium requests usage report" CSV into the same --json aggregate shape.
 *
 * Kept faithful to the Python so `test/parity.ts` can assert byte-equivalence
 * against `python scripts/tok.py --copilot <csv> --json`.
 */
import type { CopilotModelAgg, CopilotReport, CopilotDaily } from "../panel/protocol";

export interface CopilotParseError {
  error: string;
  headers: string[];
}

/** num(s): strip $ and , , tolerate junk -> 0.0  (tok.py num) */
function num(s: string): number {
  const cleaned = String(s ?? "")
    .replace(/\$/g, "")
    .replace(/,/g, "")
    .trim();
  if (cleaned === "") {
    return 0.0;
  }
  const v = Number(cleaned);
  return Number.isFinite(v) ? v : 0.0;
}

function blankAgg(): CopilotModelAgg {
  return { net: 0, gross: 0, disc: 0, qty: 0, rows: 0, billed_qty: 0 };
}

/**
 * Minimal RFC-4180-ish CSV reader: handles quoted fields, escaped quotes (""),
 * embedded commas/newlines, and CRLF. Strips a leading UTF-8 BOM.
 */
export function parseCsvRows(text: string): string[][] {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;
  let i = 0;
  // strip BOM (utf-8-sig)
  if (text.charCodeAt(0) === 0xfeff) {
    i = 1;
  }
  const pushField = () => {
    row.push(field);
    field = "";
  };
  const pushRow = () => {
    pushField();
    rows.push(row);
    row = [];
  };
  for (; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      pushField();
    } else if (ch === "\n") {
      pushRow();
    } else if (ch === "\r") {
      // swallow; \n handler (if present) makes the row, else CR alone ends row
      if (text[i + 1] !== "\n") {
        pushRow();
      }
    } else {
      field += ch;
    }
  }
  // trailing field/row (no final newline)
  if (field.length > 0 || row.length > 0) {
    pushRow();
  }
  return rows;
}

export function isParseError(r: CopilotReport | CopilotParseError): r is CopilotParseError {
  return (r as CopilotParseError).error !== undefined;
}

/**
 * @param since/until inclusive YYYY-MM-DD string bounds (lexical compare, like tok.py)
 */
export function parseCopilotCsv(
  text: string,
  since: string | null = null,
  until: string | null = null,
): CopilotReport | CopilotParseError {
  const rows = parseCsvRows(text);
  if (rows.length === 0) {
    return { error: "empty CSV", headers: [] };
  }
  const header = rows[0];
  // cols: normalized(lower/strip) -> column index
  const cols = new Map<string, number>();
  header.forEach((c, idx) => {
    cols.set((c ?? "").trim().toLowerCase(), idx);
  });
  if (!cols.has("model")) {
    return {
      error:
        "no 'model' column - this looks like a metered usage report. " +
        "Download the *Premium requests usage report* (per-model) instead.",
      headers: [...cols.keys()],
    };
  }
  const g = (row: string[], key: string): string => {
    const idx = cols.get(key);
    return idx !== undefined && idx < row.length ? (row[idx] ?? "") : "";
  };

  const agg: Record<string, CopilotModelAgg> = {};
  const daily: Record<string, CopilotDaily> = {};
  const users = new Set<string>();
  const total: CopilotModelAgg = blankAgg();

  for (let r = 1; r < rows.length; r++) {
    const row = rows[r];
    // csv.DictReader skips fully-empty lines
    if (row.length === 0 || (row.length === 1 && row[0] === "")) {
      continue;
    }
    const model = (g(row, "model") || "unknown").trim();
    const day = String(g(row, "date")).slice(0, 10);
    if ((since && day && day < since) || (until && day && day > until)) {
      continue;
    }
    const qty = num(g(row, "quantity"));
    const gross = num(g(row, "gross_amount"));
    const disc = num(g(row, "discount_amount"));
    const net = num(g(row, "net_amount"));
    const billed = String(g(row, "exceeds_quota")).trim().toUpperCase() === "TRUE";
    const user = (g(row, "username") || "").trim();
    if (user) {
      users.add(user);
    }
    const a = (agg[model] ??= blankAgg());
    a.net += net;
    a.gross += gross;
    a.disc += disc;
    a.qty += qty;
    a.rows += 1;
    a.billed_qty += billed ? qty : 0;
    total.net += net;
    total.gross += gross;
    total.disc += disc;
    total.qty += qty;
    total.rows += 1;
    total.billed_qty += billed ? qty : 0;
    const dkey = day || "?";
    const d = (daily[dkey] ??= { net: 0, qty: 0 });
    d.net += net;
    d.qty += qty;
  }

  return {
    source: "copilot",
    since,
    until,
    total,
    users: [...users].sort(),
    models: agg,
    daily,
  };
}
