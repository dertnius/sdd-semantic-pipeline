#!/usr/bin/env python3
"""
ctxsize.py - estimate the context-window footprint of instruction & skill files
*before* any agent loads them, chart it in the terminal, and price it.

Scans BOTH Claude and GitHub Copilot conventions and shows a labeled panel per
ecosystem present. It never sums the two baselines (you run one agent per session).

Pricing uses GitHub Models token-unit rates (docs.github.com/en/billing/reference/
costs-for-github-models). Cost = tokens x (multiplier-folded $/1M) ; token unit =
$0.00001. NOTE: GitHub Models billing is SEPARATE from GitHub Copilot billing and
this catalog has no Claude models -- it prices direct GitHub Models use. The page
also lists a cached-input rate, so the steady-state (re-sent every turn) baseline
is shown at the cheaper cached rate too.

Pure stdlib. No network. No ML weights. Deterministic. Token estimates use chars
/ --cpt (default 4.0); calibrate via /context.

Usage:
    python ctxsize.py [ROOT] [--model gpt-4.1] [--per-1m 2.00] [--turns 1000]
                      [--window 200000] [--budget 8000] [--only claude|copilot]
                      [--no-bars] [--no-list] [--color auto|always|never] [--ascii] [--json]
"""
from __future__ import annotations
import argparse, json, math, os, re, shutil, sys
from pathlib import Path

TARGETS = {
    "Claude": [
        ("startup_full", ["CLAUDE.md", ".claude/CLAUDE.md", "**/CLAUDE.md"]),
        ("skill_split",  [".claude/skills/**/SKILL.md", "**/SKILL.md", "**/*.skill.md"]),
        ("on_invoke",    [".claude/agents/**/*.md", ".claude/commands/**/*.md"]),
    ],
    "GitHub Copilot": [
        ("startup_full", ["AGENTS.md", "CLAUDE.md", "GEMINI.md",
                          ".github/copilot-instructions.md"]),
        ("conditional",  [".github/instructions/**/*.instructions.md",
                          "**/*.instructions.md", "**/AGENTS.md"]),
        ("on_invoke",    [".github/agents/**/*.agent.md", "**/*.agent.md",
                          "**/SKILL.md", "**/*.skill.md"]),
    ],
}
PRESENCE = {
    "Claude": ["CLAUDE.md", ".claude/skills/**/SKILL.md", ".claude/agents/**/*.md",
               ".claude/commands/**/*.md"],
    "GitHub Copilot": [".github/copilot-instructions.md", "AGENTS.md",
                       ".github/instructions/**/*.instructions.md", "**/*.instructions.md",
                       ".github/agents/**/*.agent.md"],
}
KIND_ORDER = {"startup_full": 0, "skill_split": 1, "conditional": 2, "on_invoke": 3}
APPLYTO_RE = re.compile(r"^\s*applyTo\s*:\s*(.+?)\s*$", re.MULTILINE)
NAME_RE = re.compile(r"^\s*name\s*:\s*(.+?)\s*$", re.MULTILINE)
EIGHTHS = " \u258f\u258e\u258d\u258c\u258b\u258a\u2589\u2588"
VLINE = "\u2502"

# GitHub Models direct rates: key -> (input $/1M, cached input $/1M or None, label).
# Source: docs.github.com/en/billing/reference/costs-for-github-models (token unit = $0.00001).
PRICES = {
    "gpt-4o":         (2.50, 1.25, "GPT-4o"),
    "gpt-4o-mini":    (0.15, 0.08, "GPT-4o mini"),
    "gpt-4.1":        (2.00, 0.50, "GPT-4.1"),
    "gpt-4.1-mini":   (0.40, 0.10, "GPT-4.1-mini"),
    "grok-3":         (3.00, None, "Grok 3"),
    "grok-3-mini":    (0.25, None, "Grok 3 Mini"),
    "deepseek-r1":    (1.35, None, "DeepSeek-R1"),
    "deepseek-v3":    (1.14, None, "DeepSeek-V3"),
    "llama-3.3-70b":  (0.71, None, "Llama-3.3-70B"),
    "llama-4-maverick": (0.25, None, "Llama 4 Maverick"),
    "phi-4":          (0.13, None, "Phi-4"),
    "phi-4-mini":     (0.08, None, "Phi-4-mini"),
}
DEFAULT_MODEL = "gpt-4.1"

def est(text, cpt, enc=None):
    return len(enc.encode(text)) if enc else round(len(text) / cpt)

def split_frontmatter(text):
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    return (text[:end + 4], text[end + 4:]) if end != -1 else ("", text)

def present(root, label):
    return any(next(iter(root.glob(p)), None) for p in PRESENCE[label])

def collect(root, label):
    seen, out = set(), []
    for kind, patterns in TARGETS[label]:
        for pat in patterns:
            for p in sorted(root.glob(pat)):
                rp = p.resolve()
                if rp in seen or not p.is_file():
                    continue
                seen.add(rp); out.append((kind, p))
    return out

def analyze(root, label, cpt, enc=None):
    rows = []
    for kind, p in collect(root, label):
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, body = split_frontmatter(text)
        full = est(text, cpt, enc); startup = invoke = 0; trigger = ""
        if kind == "startup_full":
            startup = full
        elif kind == "skill_split":
            startup = est(fm, cpt, enc) if fm else est(text[:200], cpt, enc)
            invoke = est(body, cpt, enc)
            m = NAME_RE.search(fm); trigger = m.group(1).strip().strip('"') if m else p.parent.name
        elif kind == "conditional":
            invoke = full
            m = APPLYTO_RE.search(fm); trigger = m.group(1).strip().strip('"') if m else "(broad)"
        else:
            invoke = full
            m = NAME_RE.search(fm); trigger = m.group(1).strip().strip('"') if m else p.stem
        rows.append({"rel": str(p.relative_to(root)), "kind": kind, "full": full,
                     "startup": startup, "invoke": invoke, "trigger": trigger})
    return rows

def labels_for(r):
    rel, t, kind = r["rel"], r["trigger"], r["kind"]
    if kind == "startup_full":
        return rel, None
    if kind == "skill_split":
        return f"{t} \u00b7 metadata", f"{t} \u00b7 body"
    if kind == "conditional":
        return None, f"{rel.split('/')[-1]} \u00b7 {t}"
    word = "subagent" if "/agents/" in rel else "command" if "/commands/" in rel else "skill"
    return None, f"{t} \u00b7 {word}"

def manifest_row(r):
    rel, t, kind = r["rel"], r["trigger"], r["kind"]
    if kind == "startup_full":
        return "\u25cf", "teal", rel, "", [f"loads every turn \u00b7 {r['full']} tok"]
    if kind == "skill_split":
        return "\u25d0", "teal", rel, t, [f"metadata loads every turn \u00b7 {r['startup']} tok",
                                          f"body loads on invoke \u00b7 {r['invoke']} tok"]
    if kind == "conditional":
        return "\u25cb", "amber", rel, t, [f"loads when an open file matches  {t}  \u00b7 {r['invoke']} tok"]
    word = "subagent" if "/agents/" in rel else "command" if "/commands/" in rel else "skill"
    return "\u25cb", "amber", rel, t, [f"loads when the {word} is invoked \u00b7 {r['invoke']} tok"]

def nice_axis(vmax, target=7):
    if vmax <= 0:
        return 1, 1
    raw = vmax / target
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = mag
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if raw <= step:
            break
    return step, math.ceil(vmax / step) * step

def order_items(rows):
    items = []
    for r in sorted(rows, key=lambda x: KIND_ORDER[x["kind"]]):
        al, _ = labels_for(r)
        if r["startup"] > 0 and al is not None:
            items.append((al, r["startup"], "teal"))
    for r in sorted(rows, key=lambda x: KIND_ORDER[x["kind"]]):
        _, dl = labels_for(r)
        if r["invoke"] > 0 and dl is not None:
            items.append((dl, r["invoke"], "amber"))
    return items

def chart_lines(items, c, cols, ascii_mode):
    if not items:
        return []
    lbl_w = min(28, max(len(l) for l, _, _ in items))
    cells = max(12, min(46, cols - lbl_w - 4))
    vmax = max(v for _, v, _ in items)
    step, axis_max = nice_axis(vmax)
    tickvals, k = [], 0
    while k * step <= axis_max + 1e-9:
        tickvals.append(k * step); k += 1
    tickcols = {round(tv / axis_max * cells): tv for tv in tickvals}
    out = []
    for label, val, colk in items:
        units = val / axis_max * cells
        full = int(units); rem = round((units - full) * 8)
        fill = "\u2588" * full + (EIGHTHS[rem] if rem and full < cells else "")
        if val > 0 and not fill:
            fill = EIGHTHS[1]
        tail = "".join("\u250a" if i in tickcols else " " for i in range(len(fill), cells)) \
            if not ascii_mode else " " * (cells - len(fill))
        lab = label if len(label) <= lbl_w else label[:lbl_w - 1] + "\u2026"
        bar = (fill + tail) if ascii_mode else c(colk, fill) + c("dim", tail)
        out.append(lab.rjust(lbl_w) + " " + c("dim", VLINE) + bar + f"  {val} tok")
    axis = "\u2514" + "".join("\u2534" if (i in tickcols and i > 0) else "\u2500" for i in range(cells))
    out.append(" " * (lbl_w + 1) + c("dim", axis))
    width = lbl_w + 2 + cells + 8
    trow = [" "] * width
    for col, tv in sorted(tickcols.items()):
        s = str(int(round(tv)))
        start = lbl_w + 2 + col
        for j, ch in enumerate(s):
            if 0 <= start + j < width:
                trow[start + j] = ch
    out.append(c("dim", "".join(trow).rstrip() + " tok"))
    return out

def manifest_lines(rows, c, cols):
    n_full = sum(1 for r in rows if r["startup"] > 0 and r["invoke"] == 0)
    n_split = sum(1 for r in rows if r["startup"] > 0 and r["invoke"] > 0)
    n_dem = sum(1 for r in rows if r["startup"] == 0)
    out = [c("bold", "manifest") + c("dim", f"   {len(rows)} files \u00b7 {n_full} always-on "
           f"\u00b7 {n_split} split \u00b7 {n_dem} on-demand"),
           c("dim", "  \u25cf every turn    \u25d0 metadata now, body on invoke    \u25cb on demand"), ""]
    for r in sorted(rows, key=lambda x: (KIND_ORDER[x["kind"]], x["rel"])):
        mark, col, rel, trig, lines = manifest_row(r)
        head = f"  {c(col, mark)} {rel}"
        if trig:
            head += "   " + c("dim", f"[{trig}]")
        out.append(head)
        for ln in lines:
            out.append("      " + c("dim", ln))
    return out

def panel(label, rows, args, c, cols):
    items = order_items(rows)
    baseline = sum(r["startup"] for r in rows)
    grand = sum(r["full"] for r in rows)
    pct = round(100 * baseline / grand) if grand else 0
    out = ["", c("bold", f"\u2550\u2550 {label} \u2550\u2550") +
           f"   {c('bold', f'{baseline} tok')}/turn \u00b7 {grand} peak \u00b7 {pct}% always-on", ""]
    if not args.no_bars:
        out += chart_lines(items, c, cols, args.ascii)
    if not args.no_list:
        out += [""] + manifest_lines(rows, c, cols)
    in_pt = baseline * args._in / 1e6
    ca_pt = baseline * args._cached / 1e6
    n = args.turns or 1000
    cost = f"~${in_pt:.4f}/turn"
    if args._cached < args._in:
        cost += f" (\u2193${ca_pt:.4f} cached)"
    cost += f" \u00b7 ~${in_pt*n:,.2f}/{n} turns \u00b7 {args._label} @ ${args._in:.2f}/1M in"
    extra = [cost]
    if args.window:
        extra.insert(0, f"{100*baseline/args.window:.1f}% of {args.window} window")
    out += ["", c("dim", "  " + "   \u00b7   ".join(extra))]
    over = False
    if args.budget:
        over = baseline > args.budget
        msg = f"  budget: {baseline} / {args.budget} \u2192 {'OK' if not over else 'OVER'}"
        out.append(msg if not over else c("red", msg))
    return out, over

def main(argv=None):
    ap = argparse.ArgumentParser(description="Estimate, chart, and price instruction/skill context (Claude + Copilot).")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--cpt", type=float, default=4.0)
    ap.add_argument("--model", choices=list(PRICES), default=DEFAULT_MODEL,
                    help=f"GitHub Models model for pricing (default {DEFAULT_MODEL})")
    ap.add_argument("--per-1m", type=float, default=None, dest="per_1m",
                    help="override the model rate with a custom USD per 1M input tokens")
    ap.add_argument("--turns", type=int, default=0, help="project cost over this many turns (default 1000)")
    ap.add_argument("--window", type=int, default=0)
    ap.add_argument("--budget", type=int, default=0)
    ap.add_argument("--only", choices=["claude", "copilot"], help="restrict to one ecosystem")
    ap.add_argument("--no-bars", action="store_true")
    ap.add_argument("--no-list", action="store_true")
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    ap.add_argument("--ascii", action="store_true")
    ap.add_argument("--exact", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.per_1m is not None:
        args._in, args._cached, args._label = args.per_1m, args.per_1m, "custom rate"
    else:
        inp, cached, label = PRICES[args.model]
        args._in, args._cached, args._label = inp, (cached if cached is not None else inp), label

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"no such path: {root}", file=sys.stderr); return 2
    enc = None
    if args.exact:
        try:
            import tiktoken; enc = tiktoken.get_encoding("o200k_base")
        except Exception as e:
            print(f"(exact unavailable: {e}; using heuristic)", file=sys.stderr)

    wanted = {"claude": "Claude", "copilot": "GitHub Copilot"}
    labels = [wanted[args.only]] if args.only else ["Claude", "GitHub Copilot"]
    panels = [(lbl, analyze(root, lbl, args.cpt, enc)) for lbl in labels if present(root, lbl)]

    if args.json:
        blob = {"root": str(root), "cpt": args.cpt, "model": args._label,
                "input_rate_per_1m": args._in, "cached_rate_per_1m": args._cached,
                "token_unit_usd": 1e-5, "ecosystems": {}}
        rc = 0
        for lbl, rows in panels:
            base = sum(r["startup"] for r in rows)
            blob["ecosystems"][lbl] = {"baseline_tokens": base,
                                       "max_tokens": sum(r["full"] for r in rows),
                                       "usd_per_turn": round(base * args._in / 1e6, 6),
                                       "usd_per_turn_cached": round(base * args._cached / 1e6, 6),
                                       "files": rows}
            if args.budget and base > args.budget:
                rc = 1
        print(json.dumps(blob, indent=2)); return rc

    if not panels:
        print("no Claude or Copilot instruction/skill files found."); return 0

    color_on = (args.color == "always" or
                (args.color == "auto" and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None))
    C = {} if not color_on else {
        "teal": "\x1b[38;2;29;158;117m", "amber": "\x1b[38;2;239;159;39m",
        "dim": "\x1b[2m", "bold": "\x1b[1m", "red": "\x1b[38;2;226;75;74m", "reset": "\x1b[0m"}
    def c(k, s): return f"{C.get(k,'')}{s}{C['reset']}" if k in C else s
    cols = shutil.get_terminal_size((80, 24)).columns

    out = ["", c("dim", f"context footprint \u00b7 cpt {args.cpt} \u00b7 {root}"),
           c("teal", "\u2588") + " loaded every turn    " + c("amber", "\u2588") + " loads on demand"]
    rc = 0
    for lbl, rows in panels:
        plines, over = panel(lbl, rows, args, c, cols)
        out += plines
        rc = rc or (1 if over else 0)
    if len(panels) > 1:
        out += ["", c("dim", "two baselines shown separately \u2014 you pay one per session, "
                "not the sum (CLAUDE.md is read by both)")]
    cached_note = f", ${args._cached:.2f}/1M cached" if args._cached < args._in else ""
    out += ["", c("dim", f"GitHub Models pricing \u00b7 {args._label} ${args._in:.2f}/1M input{cached_note} "
            f"\u00b7 token unit = $0.00001 \u00b7 separate from Copilot AI-Credit billing \u00b7 "
            "switch with --model, override --per-1m")]
    out.append("")
    print("\n".join(out))
    return rc

if __name__ == "__main__":
    sys.exit(main())