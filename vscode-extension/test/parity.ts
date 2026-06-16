/**
 * Oracle parity checks (run: npm run test:parity).
 *
 *  1. copilotCsv.ts vs `python scripts/tok.py --copilot <fixture> --json`
 *  2. tokenize.ts (js-tiktoken o200k) vs python tiktoken o200k_base, when available,
 *     plus an encode/decode roundtrip self-check.
 *
 * Imports only the PURE data modules (no 'vscode'), so it runs under plain node+tsx.
 */
import { execFileSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { parseCopilotCsv, isParseError } from "../src/data/copilotCsv";
import { tokenize } from "../src/tokenizer/tokenize";
import { buildLiveView } from "../src/data/otelSnapshot";
import { ClaudeReader } from "../src/data/claudeReader";
import { readSessionPrompts, currentSessionId } from "../src/data/sessionIndex";
import { readCopilotPrompts } from "../src/data/copilotContent";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const fixture = path.join(here, "fixtures", "premium_requests.csv");

let failures = 0;
function ok(cond: boolean, msg: string) {
  if (cond) {
    console.log(`  ok   ${msg}`);
  } else {
    console.error(`  FAIL ${msg}`);
    failures++;
  }
}
const near = (a: number, b: number) => Math.abs((a || 0) - (b || 0)) < 1e-9;

function pythonCmd(): string[] {
  const venv = path.resolve(root, "..", ".venv", "Scripts", "python.exe");
  if (existsSync(venv)) {
    return [venv];
  }
  return ["python"];
}
const PY = pythonCmd();

function hasTiktoken(): boolean {
  try {
    execFileSync(PY[0], [...PY.slice(1), "-c", "import tiktoken"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

// ---- 1. Copilot CSV parity ----
console.log("Copilot CSV parity (tok.py --copilot --json):");
const csvText = readFileSync(fixture, "utf8");
const ts = parseCopilotCsv(csvText);
if (isParseError(ts)) {
  console.error("TS parse error:", ts.error);
  process.exit(1);
}
const pyOut = execFileSync(
  PY[0],
  [...PY.slice(1), path.join(root, "scripts", "tok.py"), "--copilot", fixture, "--json"],
  { encoding: "utf8" },
);
const py = JSON.parse(pyOut);

for (const k of ["net", "gross", "disc", "qty", "rows", "billed_qty"] as const) {
  ok(near(ts.total[k], py.total[k]), `total.${k}  ts=${ts.total[k]} py=${py.total[k]}`);
}
const tsModels = Object.keys(ts.models).sort();
const pyModels = Object.keys(py.models).sort();
ok(JSON.stringify(tsModels) === JSON.stringify(pyModels), `model keys  ${tsModels.join(",")}`);
for (const m of tsModels) {
  for (const k of ["net", "gross", "disc", "qty", "rows", "billed_qty"] as const) {
    ok(near(ts.models[m][k], py.models[m]?.[k]), `models.${m}.${k}`);
  }
}
const tsDays = Object.keys(ts.daily).sort();
const pyDays = Object.keys(py.daily).sort();
ok(JSON.stringify(tsDays) === JSON.stringify(pyDays), `daily keys  ${tsDays.join(",")}`);
for (const d of tsDays) {
  ok(near(ts.daily[d].net, py.daily[d]?.net), `daily.${d}.net`);
  ok(near(ts.daily[d].qty, py.daily[d]?.qty), `daily.${d}.qty`);
}
ok(JSON.stringify(ts.users) === JSON.stringify(py.users), `users  ${JSON.stringify(ts.users)}`);

// ---- 2. Tokenizer parity ----
console.log("\nTokenizer parity (o200k):");
const samples = [
  "Hello, world! Let's tokenize this prompt.",
  "def foo(x):\n    return x * 2  # café 🚀",
  "Multi\nline\nprompt with  double  spaces and UPPER_CASE_IDENT.",
];
const tiktokenOK = hasTiktoken();
if (!tiktokenOK) {
  console.log("  (python tiktoken not installed — skipping cross-check, roundtrip only)");
}
for (const s of samples) {
  const r = tokenize(s, "gpt-4.1");
  const roundtrip = r.tokens.map((t) => t.text).join("");
  ok(roundtrip === s, `roundtrip reconstructs input (${JSON.stringify(s.slice(0, 24))}…)`);
  if (tiktokenOK) {
    const code =
      "import tiktoken,sys;enc=tiktoken.get_encoding('o200k_base');" +
      "print(len(enc.encode(sys.stdin.read())))";
    const out = execFileSync(PY[0], [...PY.slice(1), "-c", code], { input: s, encoding: "utf8" });
    const pyCount = parseInt(out.trim(), 10);
    ok(r.count === pyCount, `o200k count ts=${r.count} py=${pyCount}`);
  }
}

// ---- 3. Live OTel transform (buildLiveView) ----
console.log("\nLive OTel transform (buildLiveView):");
const otelRaw = JSON.stringify({
  sessions: {
    "sess-aaaa-1111": {
      models: { "gpt-4.1": { in: 1000, out: 200, cr: 0, cw: 0, cost: 0 } },
      first: 1718000000,
      last: 1718000900,
    },
    "sess-bbbb-2222": {
      models: { "claude-opus-4": { in: 500, out: 100, cr: 50, cw: 0, cost: 0 } },
      first: 1718100000,
      last: 1718100500,
    },
  },
});
const g = buildLiveView(otelRaw, "global", true);
ok(g.totalTokens === 1850, `global totalTokens = 1850 (got ${g.totalTokens})`);
ok(g.sessionCount === 2, `sessionCount = 2`);
ok(g.sessions[0].id === "sess-bbbb-2222", `newest-first ordering (${g.sessions[0].id})`);
ok(g.sessions[0].costEstimated === true, `cost flagged estimated (no cost metric)`);
// gpt-4.1: 1000*2.0/1e6 + 200*8.0/1e6 = 0.0036
const gpt = g.sessions[1].models[0];
ok(near(gpt.cost, 0.0036), `gpt-4.1 est cost = 0.0036 (got ${gpt.cost})`);
const n = buildLiveView(otelRaw, "newestSession", true);
ok(n.totalTokens === 650, `newestSession totalTokens = 650 (got ${n.totalTokens})`);
ok(buildLiveView(null, "global", false).available === false, `null snapshot -> unavailable`);

// ---- 4. Claude reader parity vs tok.py --dir --json ----
void (async () => {
console.log("\nClaude reader parity (tok.py --dir --json):");
const claudeRootDir = path.join(here, "fixtures", "claude-root");
const cu = await new ClaudeReader().read(claudeRootDir);
const tokOut = execFileSync(
  PY[0],
  [...PY.slice(1), path.join(root, "scripts", "tok.py"), "--dir", claudeRootDir, "--json"],
  { encoding: "utf8" },
);
const cpy = JSON.parse(tokOut);
const tsTotalTokens = cu.total.in + cu.total.out + cu.total.cr + cu.total.cw;
const pyTotalTokens = cpy.total.in + cpy.total.out + cpy.total.cr + cpy.total.cw;
ok(tsTotalTokens === pyTotalTokens, `claude total tokens ts=${tsTotalTokens} py=${pyTotalTokens}`);
ok(near(cu.total.cost, cpy.total.cost), `claude total cost ts=${cu.total.cost} py=${cpy.total.cost}`);
const cTsModels = Object.keys(cu.models).sort();
const cPyModels = Object.keys(cpy.models).sort();
ok(JSON.stringify(cTsModels) === JSON.stringify(cPyModels), `claude model keys ${cTsModels.join(",")}`);
for (const m of cTsModels) {
  for (const k of ["in", "out", "cr", "cw"] as const) {
    ok(cu.models[m][k] === cpy.models[m]?.[k], `claude models.${m}.${k}`);
  }
  ok(near(cu.models[m].cost, cpy.models[m]?.cost), `claude models.${m}.cost`);
}
ok(cpy.sessions === cu.sessions.length, `claude session count ts=${cu.sessions.length} py=${cpy.sessions}`);

// prompt extraction + current-session mapping
const sess1 = cu.sessions.find((s) => s.id === "sess1")!;
const prompts = await readSessionPrompts(sess1.file, "sess1");
ok(prompts.length === 2, `sess1 genuine prompts = 2 (got ${prompts.length})`);
ok(
  prompts[0].text === "first prompt about widgets" && prompts[1].text === "second prompt with code",
  `prompt texts extracted (skip tool_result/command/last-prompt)`,
);
ok(
  currentSessionId(cu.sessions, "C:\\work\\proj") === "sess1",
  `currentSessionId maps cwd -> sess1`,
);
ok(currentSessionId(cu.sessions, "C:\\nope") === null, `currentSessionId no match -> null`);

// ---- 5. Copilot captured-content reader ----
console.log("\nCopilot content reader (otelmeter --capture-content output):");
const contentMap = await readCopilotPrompts(path.join(here, "fixtures", "otel-content.jsonl"));
const winA = contentMap.get("win-A") ?? [];
const winB = contentMap.get("win-B") ?? [];
ok(winA.length === 2, `win-A has 2 prompts (got ${winA.length})`);
ok(
  winA[0].text === "first copilot prompt" && winA[1].text === "plain string prompt",
  `win-A prompt texts (messages-json + plain string)`,
);
ok(winB.length === 1 && winB[0].text === "second", `win-B drops system role, keeps user "second"`);

console.log(`\n${failures === 0 ? "ALL PARITY CHECKS PASSED" : failures + " PARITY CHECK(S) FAILED"}`);
process.exit(failures === 0 ? 0 : 1);
})();
