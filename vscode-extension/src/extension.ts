/**
 * Agent Usage Monitor — activation + orchestration.
 *
 * One Controller per VS Code window (each window has its own extension host).
 * It owns the status bar, the refresh loop (timer + file watcher), the optional
 * OTel sidecar, the dashboard panel, and all commands. A single snapshot is
 * built per refresh and pushed to both the status bar and the open dashboard.
 */
import * as vscode from "vscode";
import { readConfig, affectsStatusItemShape, affectsMonitor, MonitorConfig } from "./config";
import { StatusBar } from "./statusBar";
import { Store } from "./data/store";
import { OtelSidecar } from "./data/otelSidecar";
import { buildSnapshot } from "./data/snapshot";
import { parseCopilotCsv, isParseError } from "./data/copilotCsv";
import { ClaudeReader, ClaudeUsage } from "./data/claudeReader";
import { claudeRoot, readSessionPrompts, SessionPrompt } from "./data/sessionIndex";
import { readCopilotPrompts } from "./data/copilotContent";
import { fetchGhUsage } from "./data/ghUsage";
import { tokenize } from "./tokenizer/tokenize";
import { DashboardPanel } from "./panel/dashboardPanel";
import type { ViewMessage, PromptItem } from "./panel/protocol";
import { configInstructions, configureCopilotOtel } from "./otelConfig";

class Controller {
  private cfg: MonitorConfig;
  private readonly statusBar = new StatusBar();
  private readonly store: Store;
  private readonly sidecar: OtelSidecar;
  private readonly claudeReader = new ClaudeReader();
  private lastClaudeUsage: ClaudeUsage | null = null;
  private timer: ReturnType<typeof setInterval> | undefined;
  private watcher: vscode.FileSystemWatcher | undefined;
  private refreshing = false;
  private refreshQueued = false;

  constructor(private readonly ctx: vscode.ExtensionContext) {
    this.cfg = readConfig();
    this.store = new Store(ctx);
    this.sidecar = new OtelSidecar(ctx, this.store, () => this.cfg);
  }

  private workspacePath(): string | undefined {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  }

  private async snapshotInput() {
    if (this.cfg.source === "claude") {
      try {
        this.lastClaudeUsage = await this.claudeReader.read(claudeRoot(this.cfg.claudeConfigDir));
      } catch {
        this.lastClaudeUsage = null;
      }
    }
    return {
      store: this.store,
      sidecar: this.sidecar,
      cfg: this.cfg,
      claudeUsage: this.lastClaudeUsage,
      workspacePath: this.workspacePath(),
    };
  }

  async activate(): Promise<void> {
    await this.store.ensureDir();
    this.statusBar.create(this.cfg);
    this.registerCommands();
    this.setupWatcher();
    this.startTimer();

    this.ctx.subscriptions.push(
      vscode.workspace.onDidChangeConfiguration((e) => this.onConfigChange(e)),
    );
    this.ctx.subscriptions.push({ dispose: () => this.dispose() });

    await this.refresh();
  }

  // ---- refresh loop ----
  private startTimer(): void {
    this.stopTimer();
    this.timer = setInterval(() => void this.refresh(), this.cfg.refreshIntervalSeconds * 1000);
  }
  private stopTimer(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
  }

  private setupWatcher(): void {
    try {
      const dir = vscode.Uri.file(this.ctx.globalStorageUri.fsPath);
      const pattern = new vscode.RelativePattern(dir, "{otel.json,copilot-import.json}");
      this.watcher = vscode.workspace.createFileSystemWatcher(pattern);
      const hit = () => void this.refresh();
      this.watcher.onDidChange(hit);
      this.watcher.onDidCreate(hit);
      this.ctx.subscriptions.push(this.watcher);
    } catch {
      /* poll timer is the fallback */
    }
  }

  /** Build one snapshot; push to status bar + dashboard. Coalesces concurrent calls. */
  async refresh(): Promise<void> {
    if (this.refreshing) {
      this.refreshQueued = true;
      return;
    }
    this.refreshing = true;
    try {
      const snapshot = await buildSnapshot(await this.snapshotInput());
      this.statusBar.render(snapshot, this.cfg);
      DashboardPanel.current?.post({ type: "snapshot", payload: snapshot });
    } catch (e: any) {
      DashboardPanel.current?.post({ type: "error", message: e?.message ?? String(e) });
    } finally {
      this.refreshing = false;
      if (this.refreshQueued) {
        this.refreshQueued = false;
        void this.refresh();
      }
    }
  }

  private onConfigChange(e: vscode.ConfigurationChangeEvent): void {
    if (!affectsMonitor(e)) {
      return;
    }
    const recreate = affectsStatusItemShape(e);
    this.cfg = readConfig();
    if (recreate) {
      this.statusBar.create(this.cfg);
    }
    this.startTimer();
    void this.refresh();
  }

  // ---- dashboard ----
  private openDashboard(): void {
    const panel = DashboardPanel.show(this.ctx, (m) => this.onView(m));
    void (async () => {
      const layout = await this.store.loadLayout();
      if (layout) {
        panel.post({ type: "layout", grid: layout });
      }
      panel.post({ type: "snapshot", payload: await buildSnapshot(await this.snapshotInput()) });
      // file-mode Copilot: refresh from the file-exporter output on open
      if (this.cfg.source === "copilot" && this.sidecar.resolveCopilotFile()) {
        await this.parseCopilotFile(true);
      }
    })();
  }

  private onView(m: ViewMessage): void {
    switch (m.type) {
      case "ready":
        void this.sendLayout();
        void this.refresh();
        break;
      case "refresh":
        void this.refresh();
        break;
      case "tokenize": {
        const result = tokenize(m.text, m.model);
        DashboardPanel.current?.post({ type: "tokenized", payload: result });
        break;
      }
      case "requestPrompts":
        void this.sendPrompts(m.sessionId);
        break;
      case "saveLayout":
        void this.store.saveLayout(m.grid);
        break;
      case "runCommand":
        void vscode.commands.executeCommand(`usageMonitor.${m.command}`);
        break;
    }
  }

  private async sendLayout(): Promise<void> {
    const layout = await this.store.loadLayout();
    if (layout) {
      DashboardPanel.current?.post({ type: "layout", grid: layout });
    }
  }

  private async sendPrompts(sessionId: string): Promise<void> {
    let raw: SessionPrompt[] = [];
    let model = "";
    if (this.cfg.source === "claude") {
      const session = this.lastClaudeUsage?.sessions.find((s) => s.id === sessionId);
      if (session) {
        raw = await readSessionPrompts(session.file, sessionId);
        model = Object.keys(session.models)[0] ?? "";
      }
    } else {
      // copilot: prompts come from captured OTel content (if enabled)
      const map = await readCopilotPrompts(this.store.otelContentPath());
      raw = map.get(sessionId) ?? [];
      model = "gpt-4.1";
    }
    const items: PromptItem[] = raw.map((p) => ({
      ...p,
      tokenCount: tokenize(p.text, model).count,
    }));
    DashboardPanel.current?.post({ type: "prompts", sessionId, items });
  }

  // ---- commands ----
  private registerCommands(): void {
    const reg = (id: string, fn: () => unknown) =>
      this.ctx.subscriptions.push(vscode.commands.registerCommand(id, fn));

    reg("usageMonitor.openDashboard", () => this.openDashboard());
    reg("usageMonitor.refresh", () => void this.refresh());
    reg("usageMonitor.downloadBilling", () => this.downloadBilling());
    reg("usageMonitor.importCsv", () => this.importCsv());
    reg("usageMonitor.setupOtel", () => this.setupOtel());
    reg("usageMonitor.startOtel", () => this.startOtel());
    reg("usageMonitor.stopOtel", () => this.stopOtel());
    reg("usageMonitor.printOtelConfig", () => this.printOtelConfig());
    reg("usageMonitor.fetchUsageApi", () => this.fetchUsageApi());
    reg("usageMonitor.parseCopilotFile", () => this.parseCopilotFile());
  }

  private async parseCopilotFile(silent = false): Promise<void> {
    const run = async () => {
      const r = await this.sidecar.parseFile();
      if (!r.ok) {
        if (!silent) {
          void vscode.window.showWarningMessage(`Parse Copilot OTel file: ${r.reason}`);
        }
      }
      await this.refresh();
    };
    if (silent) {
      await run();
    } else {
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Parsing Copilot OTel file…" },
        run,
      );
    }
  }

  private async fetchUsageApi(): Promise<void> {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Fetching GitHub usage total…" },
      async () => {
        try {
          const summary = await fetchGhUsage({
            ghPath: this.cfg.ghPath,
            org: this.cfg.githubOrg,
          });
          await this.store.saveGhUsage(summary);
          void vscode.window.showInformationMessage(
            `GitHub usage (${summary.period}, ${summary.scope}): total net $${summary.totalNet.toFixed(2)} · ` +
              `Copilot $${summary.copilotNet.toFixed(2)} (aggregate — no model detail).`,
          );
          await this.refresh();
        } catch (e: any) {
          void vscode.window.showWarningMessage(e?.message ?? String(e));
        }
      },
    );
  }

  private async downloadBilling(): Promise<void> {
    await vscode.env.openExternal(vscode.Uri.parse("https://github.com/settings/billing"));
    void vscode.window.showInformationMessage(
      "Opened GitHub billing. Go to Billing → Usage → Premium request analytics → export the " +
        "Premium requests usage report (CSV), then run 'Usage Monitor: Import Copilot Premium-Requests CSV'.",
    );
  }

  private async importCsv(): Promise<void> {
    const picks = await vscode.window.showOpenDialog({
      canSelectMany: false,
      filters: { CSV: ["csv"] },
      title: "Select the Copilot Premium-Requests CSV",
    });
    if (!picks || picks.length === 0) {
      return;
    }
    const uri = picks[0];
    let text: string;
    try {
      text = Buffer.from(await vscode.workspace.fs.readFile(uri)).toString("utf8");
    } catch (e: any) {
      void vscode.window.showErrorMessage(`Could not read CSV: ${e?.message ?? e}`);
      return;
    }
    const parsed = parseCopilotCsv(text);
    if (isParseError(parsed)) {
      void vscode.window.showErrorMessage(parsed.error);
      return;
    }
    const name = uri.path.split("/").pop() ?? "report.csv";
    await this.store.saveBilling(parsed, name);
    void vscode.window.showInformationMessage(
      `Imported ${name}: ${Object.keys(parsed.models).length} models, ${parsed.total.rows} rows.`,
    );
    await this.refresh();
  }

  private async setupOtel(): Promise<void> {
    const choice = await vscode.window.showInformationMessage(
      "Write the github.copilot.chat.otel.* settings to enable live capture? " +
        "You will need to fully restart VS Code afterward.\n\n" +
        "'Counts + content' also captures your prompt/response TEXT locally " +
        "(gen_ai.input.messages) — enable only in a trusted environment.",
      { modal: true },
      "Counts only",
      "Counts + content",
    );
    if (choice !== "Counts only" && choice !== "Counts + content") {
      return;
    }
    const captureContent = choice === "Counts + content";
    const err = await configureCopilotOtel(this.cfg.otelPort, captureContent);
    if (err) {
      void vscode.window.showWarningMessage(
        "Could not write the settings automatically (Copilot may not be installed). Showing manual instructions.",
      );
      await this.printOtelConfig();
      return;
    }
    void vscode.window.showInformationMessage(
      "Copilot OTel configured. FULLY QUIT and reopen VS Code (a reload is not enough), then run " +
        "'Usage Monitor: Start Live Copilot OTel Capture'.",
      { modal: true },
      "OK",
    );
  }

  private async startOtel(): Promise<void> {
    const r = await this.sidecar.start();
    if (!r.ok) {
      void vscode.window.showWarningMessage(`Live OTel not started: ${r.reason}`);
    } else if (r.mode === "reader") {
      void vscode.window.showInformationMessage(
        "Another VS Code window already runs the OTel receiver — reading its shared data.",
      );
    } else {
      void vscode.window.showInformationMessage(
        `Live OTel receiver running on http://localhost:${this.cfg.otelPort} (python: ${r.python}). ` +
          "If you haven't yet, run 'Set Up Live Copilot OTel' and fully restart VS Code.",
      );
    }
    await this.refresh();
  }

  private async stopOtel(): Promise<void> {
    await this.sidecar.stop();
    void vscode.window.showInformationMessage("Live OTel capture stopped (for sessions this window owns).");
    await this.refresh();
  }

  private async printOtelConfig(): Promise<void> {
    const doc = await vscode.workspace.openTextDocument({
      content: configInstructions(this.cfg.otelPort),
      language: "markdown",
    });
    await vscode.window.showTextDocument(doc, { preview: true });
  }

  dispose(): void {
    this.stopTimer();
    this.watcher?.dispose();
    this.statusBar.dispose();
    this.sidecar.dispose();
  }
}

let controller: Controller | undefined;

export async function activate(ctx: vscode.ExtensionContext): Promise<void> {
  controller = new Controller(ctx);
  await controller.activate();
}

export function deactivate(): void {
  controller?.dispose();
  controller = undefined;
}
