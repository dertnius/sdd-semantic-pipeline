# Agent Usage Monitor

A VS Code status-bar consumption indicator + usage analytics dashboard for
**GitHub Copilot** and **Claude Code**, built on the `tok.py` / `otelmeter.py`
scripts in this repo. Phase 1 (Copilot): status bar, dashboard, billing-CSV
import, live OTel capture, manual tokenizer. Phase 2 (Claude + UX): Claude-Code
log reader with **automatic per-session prompt drill-down + tokenization**, and
**draggable/resizable** dashboard panels.

## What it does

- **Status bar indicator** — a small `$(graph) …` item in every window. With
  `source=copilot` it shows live OTel tokens/cost (sidecar) or the imported
  billing-CSV total; with `source=claude` it shows tokens/cost from your local
  Claude logs. Position, metric, and scope are configurable.
- **Dashboard** (click the item) — overview cards, a by-model bar chart, a
  daily/by-session chart, a recent-sessions list, and a **tokenizer** showing how
  a prompt splits into `o200k` tokens. **Drag panels by their header, resize from
  the corner; the layout is saved** (shared across windows).
- **Claude per-session drill-down** (`source=claude`) — expand a session to see
  the **actual user prompts**, each with char size + token count and a one-click
  **Tokenize** into the tokenizer panel. Current window's session is matched by
  `cwd` and badged.
- **Billing import** — `Download GitHub Billing Report` opens the billing page;
  `Import Copilot Premium-Requests CSV` parses the per-model export locally.
- **API total tile** — `Fetch GitHub Usage Total (gh api)` calls the GitHub
  billing usage REST endpoint via the `gh` CLI and shows an aggregate net-spend
  tile (+ a Copilot subtotal). **No per-model detail** (API limitation); needs a
  `gh` token with billing read.
- **Live Copilot OTel** (optional, needs Python) — runs `otelmeter.py` as a
  cross-window singleton receiver on `localhost:<port>`. With **content capture**
  enabled (`Set Up Live Copilot OTel` → "Counts + content"), Copilot's
  `gen_ai.input.messages` are captured to a local JSONL and the **Copilot session
  drill-down shows your prompts + tokenization** — the same view as Claude.

## Honest constraints

- **Copilot prompt content is opt-in** — by default its OTel/billing data is
  token *counts* and *cost* only. Copilot **can** emit full prompt/response
  content on `chat` spans when `github.copilot.chat.otel.captureContent` (or
  `COPILOT_OTEL_CAPTURE_CONTENT=true`) is set; the sidecar's `--capture-content`
  then records it locally. **Privacy: this captures your prompts and code — only
  enable in a trusted environment.**
- **GitHub has no per-model billing API** — you export the Premium-requests CSV
  from the billing UI, then import it.
- **Live OTel needs a full VS Code restart** after enabling Copilot's OTel
  settings (a window reload is not enough), plus Python on PATH for the sidecar.
- **Claude's tokenizer is not public** — the tokenizer uses `o200k` (the GPT
  encoding) and labels Claude results as an estimate.

## Settings

| Key | Default | Meaning |
|---|---|---|
| `usageMonitor.statusBar.alignment` | `right` | `left` / `right` |
| `usageMonitor.statusBar.priority` | `100` | higher = nearer the edge |
| `usageMonitor.statusBar.metric` | `both` | `cost` / `tokens` / `both` |
| `usageMonitor.statusBar.scope` | `global` | `global` / `newestSession` |
| `usageMonitor.refreshIntervalSeconds` | `30` | status-bar poll interval |
| `usageMonitor.source` | `copilot` | primary source (`claude` = Phase 2) |
| `usageMonitor.pythonPath` | `` | python for the OTel sidecar (auto-detect if empty) |
| `usageMonitor.otel.endpointPort` | `4318` | OTLP receiver port |

## Develop

```powershell
npm install
npm run watch            # esbuild --watch  → press F5 (Extension Dev Host)
npm run typecheck        # tsc --noEmit
npm run lint
npm run test:parity      # TS ports vs python scripts/tok.py + tiktoken oracle
```

## Package / install

```powershell
npx @vscode/vsce package           # → agent-usage-monitor-0.1.0.vsix
code --install-extension .\agent-usage-monitor-0.1.0.vsix
```

The core (status bar, dashboard, CSV import, tokenizer) runs with **zero
Python**; only live OTel capture needs a Python interpreter.
