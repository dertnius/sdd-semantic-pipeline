/**
 * Persistent cache in the extension's globalStorage — shared across all VS Code
 * windows of the same install. Holds the imported Copilot billing report, plus
 * the canonical paths the OTel sidecar uses (save file + ownership lock).
 */
import * as vscode from "vscode";
import { promises as fs } from "node:fs";
import * as path from "node:path";
import type { CopilotReport, GhUsageSummary } from "../panel/protocol";

export interface BillingRecord {
  importedAt: string;
  csvName: string;
  report: CopilotReport;
}

const BILLING_FILE = "copilot-import.json";
const OTEL_SAVE_FILE = "otel.json";
const OTEL_LOCK_FILE = "otel.lock";
const LAYOUT_FILE = "dashboard-layout.json";
const GH_USAGE_FILE = "gh-usage.json";
const OTEL_CONTENT_FILE = "otel-content.jsonl";

export class Store {
  constructor(private readonly ctx: vscode.ExtensionContext) {}

  private get dir(): string {
    return this.ctx.globalStorageUri.fsPath;
  }

  async ensureDir(): Promise<void> {
    await fs.mkdir(this.dir, { recursive: true });
  }

  billingPath(): string {
    return path.join(this.dir, BILLING_FILE);
  }

  otelSavePath(): string {
    return path.join(this.dir, OTEL_SAVE_FILE);
  }

  otelLockPath(): string {
    return path.join(this.dir, OTEL_LOCK_FILE);
  }

  async saveBilling(report: CopilotReport, csvName: string): Promise<BillingRecord> {
    await this.ensureDir();
    const rec: BillingRecord = {
      importedAt: new Date().toISOString(),
      csvName,
      report,
    };
    await atomicWrite(this.billingPath(), JSON.stringify(rec, null, 2));
    return rec;
  }

  async loadBilling(): Promise<BillingRecord | null> {
    try {
      const raw = await fs.readFile(this.billingPath(), "utf8");
      return JSON.parse(raw) as BillingRecord;
    } catch {
      return null;
    }
  }

  async readOtelSnapshotRaw(): Promise<string | null> {
    try {
      return await fs.readFile(this.otelSavePath(), "utf8");
    } catch {
      return null;
    }
  }

  async saveLayout(grid: unknown): Promise<void> {
    await this.ensureDir();
    await atomicWrite(path.join(this.dir, LAYOUT_FILE), JSON.stringify(grid));
  }

  async loadLayout(): Promise<unknown | null> {
    try {
      return JSON.parse(await fs.readFile(path.join(this.dir, LAYOUT_FILE), "utf8"));
    } catch {
      return null;
    }
  }

  async saveGhUsage(summary: GhUsageSummary): Promise<void> {
    await this.ensureDir();
    await atomicWrite(path.join(this.dir, GH_USAGE_FILE), JSON.stringify(summary, null, 2));
  }

  async loadGhUsage(): Promise<GhUsageSummary | null> {
    try {
      return JSON.parse(await fs.readFile(path.join(this.dir, GH_USAGE_FILE), "utf8")) as GhUsageSummary;
    } catch {
      return null;
    }
  }

  otelContentPath(): string {
    return path.join(this.dir, OTEL_CONTENT_FILE);
  }

  async hasOtelContent(): Promise<boolean> {
    try {
      const st = await fs.stat(this.otelContentPath());
      return st.size > 0;
    } catch {
      return false;
    }
  }
}

/** tmp + rename so a concurrent reader never sees a half-written file. */
async function atomicWrite(target: string, contents: string): Promise<void> {
  const tmp = `${target}.${process.pid}.tmp`;
  await fs.writeFile(tmp, contents, "utf8");
  await fs.rename(tmp, target);
}
