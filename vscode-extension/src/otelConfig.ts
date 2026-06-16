/**
 * Copilot OTel configuration: the one-click auto-configure writer and the
 * human-readable setup instructions (mirrors otelmeter.py CONFIG_TEXT).
 */
import * as vscode from "vscode";

export function configInstructions(port: number): string {
  return `# Live Copilot OTel capture — setup

The Agent Usage Monitor reads GitHub Copilot's OpenTelemetry locally. Copilot only
exports when one of these is enabled, and **a window reload is NOT enough — fully
quit VS Code and reopen.**

## Option A — automatic (recommended)
Run **Usage Monitor: Set Up Live Copilot OTel (auto-configure)** from the command
palette. It writes the settings below, then prompts you to restart.

## Option B — manual (settings.json)
\`\`\`json
"github.copilot.chat.otel.enabled": true,
"github.copilot.chat.otel.exporterType": "otlp-http",
"github.copilot.chat.otel.otlpEndpoint": "http://localhost:${port}"
\`\`\`

Then **fully restart VS Code** and run **Usage Monitor: Start Live Copilot OTel
Capture**. Token usage rides on Copilot \`chat\` spans.

OTel also turns on via \`COPILOT_OTEL_ENABLED=true\` or
\`OTEL_EXPORTER_OTLP_ENDPOINT\`. The receiver is fully local (binds
\`127.0.0.1:${port}\`); nothing leaves your machine.
`;
}

/**
 * Writes the three github.copilot.chat.otel.* keys to user settings.
 * Returns null on success, or an error message (e.g. keys not registered because
 * Copilot isn't installed) so the caller can fall back to instructions.
 */
export async function configureCopilotOtel(
  port: number,
  captureContent: boolean,
): Promise<string | null> {
  try {
    const otel = vscode.workspace.getConfiguration("github.copilot.chat.otel");
    await otel.update("enabled", true, vscode.ConfigurationTarget.Global);
    await otel.update("exporterType", "otlp-http", vscode.ConfigurationTarget.Global);
    await otel.update(
      "otlpEndpoint",
      `http://localhost:${port}`,
      vscode.ConfigurationTarget.Global,
    );
    if (captureContent) {
      await otel.update("captureContent", true, vscode.ConfigurationTarget.Global);
    }
    // mirror into the extension's own setting so the sidecar passes --capture-content
    await vscode.workspace
      .getConfiguration("usageMonitor")
      .update("otel.captureContent", captureContent, vscode.ConfigurationTarget.Global);
    return null;
  } catch (e: any) {
    return e?.message ?? String(e);
  }
}
