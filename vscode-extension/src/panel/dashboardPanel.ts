/**
 * The dashboard WebviewPanel: a CSP-locked, nonce'd webview that renders the
 * DashboardSnapshot (overview cards, per-model bar, daily trend, session list)
 * and the manual tokenizer. All vendor JS is bundled offline under media/vendor.
 */
import * as vscode from "vscode";
import { readFileSync } from "node:fs";
import * as crypto from "node:crypto";
import type { HostMessage, ViewMessage } from "./protocol";

function nonce(): string {
  return crypto.randomBytes(16).toString("hex");
}

export class DashboardPanel {
  static current: DashboardPanel | undefined;
  private readonly panel: vscode.WebviewPanel;
  private readonly disposables: vscode.Disposable[] = [];

  private constructor(
    private readonly ctx: vscode.ExtensionContext,
    private readonly onView: (msg: ViewMessage) => void,
  ) {
    this.panel = vscode.window.createWebviewPanel(
      "usageMonitor.dashboard",
      "Agent Usage",
      vscode.ViewColumn.Active,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(ctx.extensionUri, "media")],
      },
    );
    this.panel.iconPath = new vscode.ThemeIcon("graph") as unknown as vscode.Uri;
    this.panel.webview.html = this.getHtml();
    this.panel.webview.onDidReceiveMessage(
      (m: ViewMessage) => this.onView(m),
      undefined,
      this.disposables,
    );
    this.panel.onDidDispose(() => this.dispose(), undefined, this.disposables);
  }

  static show(
    ctx: vscode.ExtensionContext,
    onView: (msg: ViewMessage) => void,
  ): DashboardPanel {
    if (DashboardPanel.current) {
      DashboardPanel.current.panel.reveal(vscode.ViewColumn.Active);
      return DashboardPanel.current;
    }
    DashboardPanel.current = new DashboardPanel(ctx, onView);
    return DashboardPanel.current;
  }

  post(msg: HostMessage): void {
    void this.panel.webview.postMessage(msg);
  }

  private uri(...parts: string[]): vscode.Uri {
    return this.panel.webview.asWebviewUri(
      vscode.Uri.joinPath(this.ctx.extensionUri, "media", ...parts),
    );
  }

  private getHtml(): string {
    const w = this.panel.webview;
    const n = nonce();
    const tmplPath = vscode.Uri.joinPath(this.ctx.extensionUri, "media", "dashboard.html").fsPath;
    const tmpl = readFileSync(tmplPath, "utf8");
    return tmpl
      .replaceAll("%%CSP_SOURCE%%", w.cspSource)
      .replaceAll("%%NONCE%%", n)
      .replaceAll("%%CHARTJS%%", this.uri("vendor", "chart.umd.min.js").toString())
      .replaceAll("%%GRIDSTACK%%", this.uri("vendor", "gridstack-all.js").toString())
      .replaceAll("%%GRIDSTACK_CSS%%", this.uri("vendor", "gridstack.min.css").toString())
      .replaceAll("%%STYLE%%", this.uri("dashboard.css").toString())
      .replaceAll("%%SCRIPT%%", this.uri("dashboard.js").toString());
  }

  dispose(): void {
    DashboardPanel.current = undefined;
    this.panel.dispose();
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
  }
}
