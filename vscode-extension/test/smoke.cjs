/**
 * Offline activation smoke test — loads the bundled extension host against a
 * stubbed `vscode` module. Verifies activate() wires the status bar + commands,
 * the webview HTML renders, and (with source=claude over a fixture log tree) the
 * snapshot reaches "claude" mode and the prompt drill-down returns prompts.
 *
 *   node test/smoke.cjs   (run from the extension root)
 */
const Module = require("module");
const path = require("path");
const os = require("os");
const fs = require("fs");

const FIXTURE_ROOT = path.resolve("test/fixtures/claude-root");
const WORKSPACE = "C:\\work\\proj"; // matches sess1 cwd in the fixture

function makeUri(fsPath) {
  return {
    fsPath,
    path: String(fsPath).replace(/\\/g, "/"),
    scheme: "file",
    toString() {
      return "file://" + this.path;
    },
  };
}

// flat settings map keyed by "<section>.<key>"
const settings = {
  "usageMonitor.source": "claude",
  "usageMonitor.claudeConfigDir": FIXTURE_ROOT,
};

const registered = {};
const posted = []; // messages the host posts to the webview
let viewHandler = null; // captured webview onDidReceiveMessage callback

const vscode = {
  StatusBarAlignment: { Left: 1, Right: 2 },
  ViewColumn: { Active: -1 },
  ConfigurationTarget: { Global: 1 },
  ThemeIcon: class {
    constructor(id) {
      this.id = id;
    }
  },
  MarkdownString: class {
    constructor() {
      this.value = "";
      this.supportThemeIcons = false;
    }
    appendMarkdown(s) {
      this.value += s;
      return this;
    }
  },
  Uri: {
    file: (p) => makeUri(p),
    parse: (s) => makeUri(s),
    joinPath: (base, ...parts) => makeUri(path.join(base.fsPath, ...parts)),
  },
  RelativePattern: class {
    constructor(base, pattern) {
      this.base = base;
      this.pattern = pattern;
    }
  },
  window: {
    createStatusBarItem: () => ({ show() {}, dispose() {}, text: "", tooltip: undefined, name: "", command: "" }),
    createWebviewPanel: () => ({
      webview: {
        asWebviewUri: (u) => u,
        cspSource: "vscode-resource:",
        html: "",
        postMessage(m) {
          posted.push(m);
        },
        onDidReceiveMessage(cb) {
          viewHandler = cb;
        },
      },
      reveal() {},
      onDidDispose() {},
      dispose() {},
      iconPath: undefined,
    }),
    showInformationMessage: async () => undefined,
    showWarningMessage: async () => undefined,
    showErrorMessage: async () => undefined,
    showOpenDialog: async () => undefined,
    showTextDocument: async () => undefined,
  },
  workspace: {
    workspaceFolders: [{ uri: makeUri(WORKSPACE) }],
    getConfiguration: (section) => ({
      get: (k, d) => {
        const full = section ? `${section}.${k}` : k;
        return full in settings ? settings[full] : d;
      },
      update: async () => {},
    }),
    onDidChangeConfiguration: () => ({ dispose() {} }),
    createFileSystemWatcher: () => ({ onDidChange() {}, onDidCreate() {}, dispose() {} }),
    openTextDocument: async () => ({}),
    fs: { readFile: async () => Buffer.from("") },
  },
  commands: {
    registerCommand(id, fn) {
      registered[id] = fn;
      return { dispose() {} };
    },
    executeCommand: async (id, ...a) => (registered[id] ? registered[id](...a) : undefined),
  },
  extensions: { getExtension: () => undefined },
  env: { openExternal: async () => true },
};

const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === "vscode") {
    return vscode;
  }
  return origLoad.call(this, request, parent, isMain);
};

function assert(cond, msg) {
  if (!cond) {
    throw new Error("assertion failed: " + msg);
  }
  console.log("  ok   " + msg);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const ext = require(path.resolve("dist/extension.js"));
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "um-smoke-"));
  const ctx = {
    subscriptions: [],
    extensionUri: vscode.Uri.file(process.cwd()),
    globalStorageUri: vscode.Uri.file(tmp),
  };

  await ext.activate(ctx);

  assert(Object.keys(registered).length === 10, "10 commands registered");
  for (const c of [
    "openDashboard",
    "refresh",
    "downloadBilling",
    "importCsv",
    "setupOtel",
    "startOtel",
    "stopOtel",
    "printOtelConfig",
    "fetchUsageApi",
    "parseCopilotFile",
  ]) {
    assert(typeof registered["usageMonitor." + c] === "function", "command " + c);
  }

  await registered["usageMonitor.refresh"]();
  assert(true, "refresh (claude source over fixture) - no throw");

  await registered["usageMonitor.openDashboard"]();
  await sleep(150);
  const snap = [...posted].reverse().find((m) => m.type === "snapshot");
  assert(!!snap, "dashboard received a snapshot");
  assert(snap.payload.mode === "claude", "snapshot mode = claude (got " + snap.payload.mode + ")");
  assert(snap.payload.claude && snap.payload.claude.sessionCount === 2, "claude view has 2 sessions");
  assert(snap.payload.claude.currentSessionId === "sess1", "current session mapped by cwd -> sess1");

  assert(typeof viewHandler === "function", "webview message handler captured");
  viewHandler({ type: "requestPrompts", sessionId: "sess1" });
  await sleep(150);
  const pr = [...posted].reverse().find((m) => m.type === "prompts" && m.sessionId === "sess1");
  assert(!!pr, "prompts message posted for sess1");
  assert(pr.items.length === 2, "2 genuine prompts returned (got " + pr.items.length + ")");
  assert(pr.items[0].tokenCount > 0, "prompt carries a token count");

  // layout round-trip
  viewHandler({ type: "saveLayout", grid: [{ id: "overview", x: 0, y: 0, w: 6, h: 2 }] });
  await sleep(80);
  assert(fs.existsSync(path.join(tmp, "dashboard-layout.json")), "layout persisted to globalStorage");

  ext.deactivate();
  assert(true, "deactivate");

  console.log("\nSMOKE OK");
  process.exit(0);
})().catch((e) => {
  console.error("\nSMOKE FAIL:", e && e.stack ? e.stack : e);
  process.exit(1);
});
