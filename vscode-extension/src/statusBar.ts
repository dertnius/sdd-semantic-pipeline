/**
 * The status-bar consumption indicator. Created via the API (not a manifest
 * contribution) so alignment + priority can come from settings; the item is
 * disposed and recreated when those shape settings change. Rendering is driven
 * centrally from extension.ts (one snapshot, pushed to bar + dashboard).
 */
import * as vscode from "vscode";
import type { DashboardSnapshot } from "./panel/protocol";
import type { MonitorConfig } from "./config";
import { humanTokens, money } from "./format";

const ITEM_ID = "usageMonitor.indicator";

export class StatusBar {
  private item: vscode.StatusBarItem | undefined;
  private last: DashboardSnapshot | undefined;

  create(cfg: MonitorConfig): void {
    this.item?.dispose();
    const alignment =
      cfg.alignment === "left"
        ? vscode.StatusBarAlignment.Left
        : vscode.StatusBarAlignment.Right;
    this.item = vscode.window.createStatusBarItem(ITEM_ID, alignment, cfg.priority);
    this.item.name = "Agent Usage";
    this.item.command = "usageMonitor.openDashboard";
    this.item.text = "$(graph) usage …";
    this.item.show();
    if (this.last) {
      this.render(this.last, cfg);
    }
  }

  render(snapshot: DashboardSnapshot, cfg: MonitorConfig): void {
    this.last = snapshot;
    if (!this.item) {
      return;
    }
    this.item.text = `$(graph) ${snapshot.statusText}`;
    this.item.tooltip = this.buildTooltip(snapshot, cfg);
  }

  private buildTooltip(s: DashboardSnapshot, cfg: MonitorConfig): vscode.MarkdownString {
    const md = new vscode.MarkdownString(undefined, true);
    md.supportThemeIcons = true;
    md.appendMarkdown(`**Agent Usage Monitor** — _${cfg.source}_\n\n`);

    if (s.mode === "claude" && s.claude) {
      md.appendMarkdown(
        `$(comment-discussion) **Claude Code** · scope: \`${cfg.scope}\` · ${s.claude.sessionCount} session(s)\n\n`,
      );
      md.appendMarkdown(
        `Tokens: **${humanTokens(s.claude.totalTokens)}** · Cost: **${s.claude.costEstimated ? "~" : ""}${money(s.claude.totalCost)}**\n\n`,
      );
      const top = s.claude.sessions.slice(0, 4);
      if (top.length) {
        md.appendMarkdown(`| session | tokens | ${s.claude.costEstimated ? "~$" : "$"} |\n|---|--:|--:|\n`);
        for (const ss of top) {
          md.appendMarkdown(
            `| \`${ss.shortId}\`${ss.isCurrent ? " ◀" : ""} | ${humanTokens(ss.tokens)} | ${money(ss.cost)} |\n`,
          );
        }
        md.appendMarkdown(`\n`);
      }
    } else if (s.mode === "live") {
      md.appendMarkdown(
        `$(pulse) **Live OTel** · scope: \`${cfg.scope}\` · ${s.live.sessionCount} session(s)\n\n`,
      );
      md.appendMarkdown(
        `Tokens: **${humanTokens(s.live.totalTokens)}** · Est. cost: **~${money(s.live.totalCost)}**\n\n`,
      );
      const top = s.live.sessions.slice(0, 4);
      if (top.length) {
        md.appendMarkdown(`| session | tokens | ~$ |\n|---|--:|--:|\n`);
        for (const ss of top) {
          md.appendMarkdown(
            `| \`${ss.shortId}\` | ${humanTokens(ss.tokens)} | ~${money(ss.cost)} |\n`,
          );
        }
        md.appendMarkdown(`\n`);
      }
    } else if (s.mode === "billing" && s.billing.report) {
      const t = s.billing.report.total;
      md.appendMarkdown(`$(database) **Imported billing CSV**`);
      if (s.billing.importedAt) {
        md.appendMarkdown(` · ${new Date(s.billing.importedAt).toLocaleString()}`);
      }
      md.appendMarkdown(`\n\n`);
      md.appendMarkdown(
        `Billed: **${money(t.net)}** · Gross: ${money(t.gross)} · Requests: **${humanTokens(t.qty)}**\n\n`,
      );
      md.appendMarkdown(`_Static snapshot — re-import to update._\n\n`);
    } else {
      md.appendMarkdown(
        `_No usage data yet._\n\nImport a Copilot billing CSV, or start live OTel capture.\n\n`,
      );
    }
    md.appendMarkdown(`$(graph) Click to open the dashboard.`);
    return md;
  }

  dispose(): void {
    this.item?.dispose();
    this.item = undefined;
  }
}
