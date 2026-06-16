/**
 * Best-effort aggregate spend via the GitHub CLI (`gh api`) against the billing
 * usage REST endpoint:
 *   GET /users/{username}/settings/billing/usage
 *   GET /organizations/{org}/settings/billing/usage
 *
 * The endpoint returns `usageItems[]` with per-line `netAmount`/`product`/`sku`
 * but NO per-model breakdown for Copilot premium requests — so this yields a
 * total (+ a Copilot subtotal by product/sku match) only. For per-model detail,
 * import the Premium-requests CSV instead. Requires `gh` authenticated with
 * billing read access; many tokens lack it (403) — surfaced as a clear error.
 */
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { GhUsageSummary } from "../panel/protocol";

const pexec = promisify(execFile);

interface UsageItem {
  product?: string;
  sku?: string;
  grossAmount?: number;
  discountAmount?: number;
  netAmount?: number;
}

async function runGh(ghPath: string, args: string[]): Promise<string> {
  const { stdout } = await pexec(ghPath, args, { maxBuffer: 64 * 1024 * 1024 });
  return stdout;
}

export async function ghAvailable(ghPath: string): Promise<boolean> {
  try {
    await runGh(ghPath, ["--version"]);
    return true;
  } catch {
    return false;
  }
}

const isCopilot = (s: string) => /copilot/i.test(s || "");

export async function fetchGhUsage(opts: {
  ghPath?: string;
  org?: string;
  year?: number;
  month?: number;
}): Promise<GhUsageSummary> {
  const ghPath = opts.ghPath?.trim() || "gh";
  if (!(await ghAvailable(ghPath))) {
    throw new Error(
      "GitHub CLI (`gh`) not found. Install it and run `gh auth login`, or set usageMonitor.ghPath.",
    );
  }

  let scope: "user" | "org";
  let account: string;
  let apiPath: string;
  if (opts.org && opts.org.trim()) {
    scope = "org";
    account = opts.org.trim();
    apiPath = `/organizations/${account}/settings/billing/usage`;
  } else {
    scope = "user";
    account = (await runGh(ghPath, ["api", "user", "--jq", ".login"])).trim();
    apiPath = `/users/${account}/settings/billing/usage`;
  }

  const now = new Date();
  const year = opts.year ?? now.getUTCFullYear();
  const month = opts.month ?? now.getUTCMonth() + 1;
  const query = `?year=${year}&month=${String(month).padStart(2, "0")}`;

  let raw: string;
  try {
    raw = await runGh(ghPath, ["api", "-H", "Accept: application/vnd.github+json", apiPath + query]);
  } catch (e: any) {
    const msg = String(e?.stderr || e?.message || e);
    throw new Error(
      `gh api failed for ${apiPath}. The billing usage API needs a token with billing read ` +
        `(fine-grained PAT with "Plan" read, or org owner). Use CSV import for per-model detail.\n${msg.slice(0, 400)}`,
    );
  }

  let parsed: { usageItems?: UsageItem[] };
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("gh api returned non-JSON output.");
  }
  const items = parsed.usageItems ?? [];

  let totalNet = 0;
  let totalGross = 0;
  let copilotNet = 0;
  let copilotGross = 0;
  const byProduct: Record<string, { net: number; gross: number }> = {};
  for (const it of items) {
    const net = Number(it.netAmount) || 0;
    const gross = Number(it.grossAmount) || 0;
    totalNet += net;
    totalGross += gross;
    const product = it.product || "unknown";
    const bp = (byProduct[product] ??= { net: 0, gross: 0 });
    bp.net += net;
    bp.gross += gross;
    if (isCopilot(product) || isCopilot(it.sku || "")) {
      copilotNet += net;
      copilotGross += gross;
    }
  }

  return {
    fetchedAt: new Date().toISOString(),
    scope,
    account,
    period: `${year}-${String(month).padStart(2, "0")}`,
    totalNet,
    totalGross,
    copilotNet,
    copilotGross,
    byProduct,
    itemCount: items.length,
  };
}
