/**
 * Manages the optional Python OTel sidecar (otelmeter.py) as a cross-window
 * singleton.
 *
 * Coordination: a lock file in globalStorage records the owning window's pid +
 * port. The first window to create it (exclusive 'wx' write) spawns the sidecar;
 * other windows become readers that just poll the shared otel.json. A stale lock
 * (owner pid no longer alive) is reclaimed. The sidecar is launched with
 * PYTHONUTF8=1 to dodge the Windows cp1252 console hazard.
 */
import * as vscode from "vscode";
import { spawn, ChildProcess } from "node:child_process";
import { promises as fs, existsSync } from "node:fs";
import * as path from "node:path";
import type { Store } from "./store";
import type { MonitorConfig } from "../config";

export type SidecarMode = "owner" | "reader" | "stopped";

export interface StartResult {
  mode: SidecarMode;
  ok: boolean;
  reason?: string;
  python?: string;
}

interface LockData {
  pid: number;
  port: number;
  startedAt: string;
}

function isPidAlive(pid: number): boolean {
  if (!pid || pid <= 0) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch (e: any) {
    return e?.code === "EPERM"; // exists but not signalable -> still alive
  }
}

export class OtelSidecar {
  private child: ChildProcess | null = null;
  private mode: SidecarMode = "stopped";
  private stderrTail: string[] = [];
  private resolvedPython: string[] | null = null;

  constructor(
    private readonly ctx: vscode.ExtensionContext,
    private readonly store: Store,
    private readonly getConfig: () => MonitorConfig,
  ) {}

  private scriptPath(): string {
    return path.join(this.ctx.extensionUri.fsPath, "scripts", "otelmeter.py");
  }

  /** Resolve a python launcher argv prefix, e.g. ["py","-3"] or ["python"]. */
  async discoverPython(): Promise<string[] | null> {
    if (this.resolvedPython) {
      return this.resolvedPython;
    }
    const cfg = this.getConfig();
    const candidates: string[][] = [];
    if (cfg.pythonPath) {
      candidates.push([cfg.pythonPath]);
    }
    // ms-python.python active interpreter, if available
    const py = vscode.extensions.getExtension("ms-python.python");
    if (py) {
      try {
        await py.activate();
        const p = py.exports?.environments?.getActiveEnvironmentPath?.();
        if (p?.path) {
          candidates.push([p.path]);
        }
      } catch {
        /* ignore */
      }
    }
    candidates.push(["py", "-3"], ["python"], ["python3"]);
    for (const argv of candidates) {
      if (await this.testPython(argv)) {
        this.resolvedPython = argv;
        return argv;
      }
    }
    return null;
  }

  private testPython(argv: string[]): Promise<boolean> {
    return new Promise((resolve) => {
      try {
        const p = spawn(argv[0], [...argv.slice(1), "--version"], {
          stdio: "ignore",
          shell: false,
        });
        p.on("error", () => resolve(false));
        p.on("exit", (code) => resolve(code === 0));
      } catch {
        resolve(false);
      }
    });
  }

  private async readLock(): Promise<LockData | null> {
    try {
      return JSON.parse(await fs.readFile(this.store.otelLockPath(), "utf8")) as LockData;
    } catch {
      return null;
    }
  }

  /** True when a sidecar is alive somewhere (this window's child or a live lock). */
  async isRunning(): Promise<boolean> {
    if (this.child && !this.child.killed && this.child.exitCode === null) {
      return true;
    }
    const lock = await this.readLock();
    return !!lock && isPidAlive(lock.pid);
  }

  async ownsLock(): Promise<boolean> {
    const lock = await this.readLock();
    return !!lock && lock.pid === process.pid;
  }

  /** Acquire ownership or fall back to reader. */
  private async acquire(port: number): Promise<SidecarMode> {
    await this.store.ensureDir();
    const lockPath = this.store.otelLockPath();
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const data: LockData = {
          pid: process.pid,
          port,
          startedAt: new Date().toISOString(),
        };
        await fs.writeFile(lockPath, JSON.stringify(data), { flag: "wx" });
        return "owner";
      } catch (e: any) {
        if (e?.code !== "EEXIST") {
          throw e;
        }
        const lock = await this.readLock();
        if (lock && isPidAlive(lock.pid)) {
          return "reader";
        }
        // stale lock -> remove and retry
        try {
          await fs.rm(lockPath, { force: true });
        } catch {
          /* ignore */
        }
      }
    }
    return "reader";
  }

  private async releaseLockIfOwner(): Promise<void> {
    const lock = await this.readLock();
    if (lock && lock.pid === process.pid) {
      try {
        await fs.rm(this.store.otelLockPath(), { force: true });
      } catch {
        /* ignore */
      }
    }
  }

  async start(): Promise<StartResult> {
    if (await this.isRunning()) {
      // already running somewhere; make sure we're at least a reader
      this.mode = (await this.ownsLock()) ? "owner" : "reader";
      return { mode: this.mode, ok: true, reason: "already running" };
    }
    const python = await this.discoverPython();
    if (!python) {
      return {
        mode: "stopped",
        ok: false,
        reason:
          "No Python interpreter found. Set usageMonitor.pythonPath, or install Python on PATH. " +
          "Live OTel capture is the only feature that needs Python.",
      };
    }
    const cfg = this.getConfig();
    const mode = await this.acquire(cfg.otelPort);
    this.mode = mode;
    if (mode === "reader") {
      return { mode, ok: true, reason: "another window owns the sidecar", python: python.join(" ") };
    }
    // owner: spawn the receiver
    const args = [
      ...python.slice(1),
      this.scriptPath(),
      "--traces",
      "--host",
      "127.0.0.1",
      "--port",
      String(cfg.otelPort),
      "--save",
      this.store.otelSavePath(),
    ];
    if (cfg.captureContent) {
      args.push("--capture-content", this.store.otelContentPath());
    }
    try {
      const child = spawn(python[0], args, {
        stdio: ["ignore", "ignore", "pipe"],
        shell: false,
        env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
      });
      this.child = child;
      this.stderrTail = [];
      child.stderr?.on("data", (b: Buffer) => {
        this.stderrTail.push(b.toString());
        if (this.stderrTail.length > 40) {
          this.stderrTail.shift();
        }
      });
      child.on("exit", () => {
        this.child = null;
        this.mode = "stopped";
        void this.releaseLockIfOwner();
      });
      // surface an immediate bind failure (port already taken by a manual run)
      const early = await new Promise<string | null>((resolve) => {
        const t = setTimeout(() => resolve(null), 700);
        child.once("exit", (code) => {
          clearTimeout(t);
          resolve(`sidecar exited early (code ${code}): ${this.stderrTail.join("").slice(-400)}`);
        });
        child.once("error", (err) => {
          clearTimeout(t);
          resolve(`failed to launch python: ${err.message}`);
        });
      });
      if (early) {
        await this.releaseLockIfOwner();
        return { mode: "stopped", ok: false, reason: early, python: python.join(" ") };
      }
      return { mode: "owner", ok: true, python: python.join(" ") };
    } catch (e: any) {
      await this.releaseLockIfOwner();
      return { mode: "stopped", ok: false, reason: `spawn error: ${e?.message ?? e}` };
    }
  }

  /**
   * Resolve the Copilot OTel file-exporter output: the usageMonitor.copilotFile
   * override, else github.copilot.chat.otel.outfile when exporterType is "file".
   */
  resolveCopilotFile(): string | null {
    const cfg = this.getConfig();
    if (cfg.copilotOtelFile) {
      return cfg.copilotOtelFile;
    }
    const otel = vscode.workspace.getConfiguration("github.copilot.chat.otel");
    const type = otel.get<string>("exporterType");
    const out = otel.get<string>("outfile");
    if (type === "file" && out) {
      return out;
    }
    return null;
  }

  /**
   * One-shot: parse Copilot's OTel file-exporter output into the shared otel.json
   * (so file-mode users get data without the HTTP receiver / a restart).
   */
  async parseFile(): Promise<{ ok: boolean; reason?: string; file?: string }> {
    const file = this.resolveCopilotFile();
    if (!file) {
      return {
        ok: false,
        reason:
          "No Copilot OTel file found. Set github.copilot.chat.otel.exporterType=\"file\" + outfile, " +
          "or usageMonitor.otel.copilotFile.",
      };
    }
    if (!existsSync(file)) {
      return { ok: false, reason: `Copilot OTel file not found: ${file}` };
    }
    const python = await this.discoverPython();
    if (!python) {
      return { ok: false, reason: "Python not found (needed to parse the OTel file)." };
    }
    const cfg = this.getConfig();
    await this.store.ensureDir();
    const args = [
      ...python.slice(1),
      this.scriptPath(),
      "--file",
      file,
      "--traces",
      "--group",
      "session",
      "--color",
      "never",
      "--save",
      this.store.otelSavePath(),
    ];
    if (cfg.captureContent) {
      args.push("--capture-content", this.store.otelContentPath());
    }
    return new Promise((resolve) => {
      try {
        const child = spawn(python[0], args, {
          stdio: ["ignore", "ignore", "pipe"],
          shell: false,
          env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
        });
        let err = "";
        child.stderr?.on("data", (b: Buffer) => {
          err += b.toString();
        });
        child.on("error", (e) => resolve({ ok: false, reason: e.message }));
        child.on("exit", (code) =>
          resolve(code === 0 ? { ok: true, file } : { ok: false, reason: err.slice(-400) || `exit ${code}` }),
        );
      } catch (e: any) {
        resolve({ ok: false, reason: e?.message ?? String(e) });
      }
    });
  }

  async stop(): Promise<void> {
    if (this.child) {
      try {
        this.child.kill();
      } catch {
        /* ignore */
      }
      this.child = null;
    }
    await this.releaseLockIfOwner();
    this.mode = "stopped";
  }

  dispose(): void {
    // best-effort synchronous-ish cleanup on window close
    if (this.child) {
      try {
        this.child.kill();
      } catch {
        /* ignore */
      }
    }
    void this.releaseLockIfOwner();
  }
}
