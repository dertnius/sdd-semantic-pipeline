import * as vscode from "vscode";

export type Alignment = "left" | "right";
export type Metric = "cost" | "tokens" | "both";
export type Scope = "global" | "newestSession";
export type Source = "copilot" | "claude";

export interface MonitorConfig {
  alignment: Alignment;
  priority: number;
  metric: Metric;
  scope: Scope;
  refreshIntervalSeconds: number;
  source: Source;
  pythonPath: string;
  claudeConfigDir: string;
  otelPort: number;
  ghPath: string;
  githubOrg: string;
  captureContent: boolean;
  copilotOtelFile: string;
}

const SECTION = "usageMonitor";

export function readConfig(): MonitorConfig {
  const c = vscode.workspace.getConfiguration(SECTION);
  return {
    alignment: c.get<Alignment>("statusBar.alignment", "right"),
    priority: c.get<number>("statusBar.priority", 100),
    metric: c.get<Metric>("statusBar.metric", "both"),
    scope: c.get<Scope>("statusBar.scope", "global"),
    refreshIntervalSeconds: Math.max(5, c.get<number>("refreshIntervalSeconds", 30)),
    source: c.get<Source>("source", "copilot"),
    pythonPath: c.get<string>("pythonPath", "").trim(),
    claudeConfigDir: c.get<string>("claudeConfigDir", "").trim(),
    otelPort: c.get<number>("otel.endpointPort", 4318),
    ghPath: c.get<string>("ghPath", "").trim(),
    githubOrg: c.get<string>("githubOrg", "").trim(),
    captureContent: c.get<boolean>("otel.captureContent", false),
    copilotOtelFile: c.get<string>("otel.copilotFile", "").trim(),
  };
}

/** True when a config change touches a key that requires recreating the status item. */
export function affectsStatusItemShape(e: vscode.ConfigurationChangeEvent): boolean {
  return (
    e.affectsConfiguration(`${SECTION}.statusBar.alignment`) ||
    e.affectsConfiguration(`${SECTION}.statusBar.priority`)
  );
}

export function affectsMonitor(e: vscode.ConfigurationChangeEvent): boolean {
  return e.affectsConfiguration(SECTION);
}
