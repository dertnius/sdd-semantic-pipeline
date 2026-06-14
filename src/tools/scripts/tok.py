#!/usr/bin/env python3
"""
tokspend.py - a local, offline tokscale-style token & cost tracker.

Two sources, one tool:
  * Claude Code (default): parses ~/.claude/projects/**/*.jsonl, sums per-model
    token usage and cost (the message's own cost when logged, else baked Anthropic
    rates). Fully local, no network.
  * GitHub Copilot (--copilot CSV): parses GitHub's "Premium requests usage report"
    (the only export with a per-model breakdown) and sums spend per model.

GitHub Copilot writes no local per-message log, so its actuals must come from the
billing export. Download the Premium requests usage report from the billing UI
(Premium request analytics page); the metered summarized/detailed reports and the
REST /usage endpoint have no model column.

Pure standard library. No install. No OTEL.

Usage:
    python tokspend.py [--dir ~/.claude] [--by cost|tokens] [date filters] [--daily] [--json]
    python tokspend.py --copilot premium_requests.csv [--by cost|tokens] [date filters] [--daily] [--json]

Date filters: --today | --week | --month | --since YYYY-MM-DD --until YYYY-MM-DD
"""
from __future__ import annotations
import argparse, csv, datetime as dt, json, math, os, shutil, sys
from pathlib import Path

# Anthropic API rates, USD per 1M tokens: (input, output, cache_read, cache_write).
# Source: Anthropic pricing, mid-2026. cache_read ~= 0.1x input, cache_write ~= 1.25x input.
CLAUDE_RATES = {
    "opus":   (5.00, 25.00, 0.50, 6.25),
    "sonnet": (3.00, 15.00, 0.30, 3.75),
    "haiku":  (1.00, 5.00, 0.10, 1.25),
}
OPUS_LEGACY = (15.00, 75.00, 1.50, 18.75)  # Opus 4.1 and earlier
EIGHTHS = " \u258f\u258e\u258d\u258c\u258b\u258a\u2589\u2588"
BLOCK, VLINE, DOT = "\u2588", "\u2502", "\u25cf"

def rate_for(model: str):
    m = (model or "").lower()
    if "opus" in m:
        return OPUS_LEGACY if ("4-1" in m or "4.1" in m) else CLAUDE_RATES["opus"]
    if "sonnet" in m:
        return CLAUDE_RATES["sonnet"]
    if "haiku" in m:
        return CLAUDE_RATES["haiku"]
    return None

def short_model(model: str) -> str:
    return (model or "unknown").replace("claude-", "")[:26]

def nice_axis(vmax, target=7):
    if vmax <= 0:
        return 1, 1
    raw = vmax / target
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = mag
    for mlt in (1, 2, 2.5, 5, 10):
        step = mlt * mag
        if raw <= step:
            break
    return step, math.ceil(vmax / step) * step

def human(n) -> str:
    n = float(n)
    if n >= 1e6:
        return f"{n/1e6:.1f}M"
    if n >= 1e3:
        return f"{n/1e3:.1f}k"
    return str(int(round(n)))

def money(v) -> str:
    return f"${v:,.4f}" if 0 < abs(v) < 1 else f"${v:,.2f}"

def fmt(v, unit):
    if unit == "$":
        return money(v)
    return f"{human(v)} {unit}"

def num(s):
    try:
        return float(str(s).replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0

# ---------- Claude Code (local session logs) ----------
def parse_claude(root: Path, since, until):
    seen = set(); agg = {}; daily = {}; sessions = set()
    total = {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "msgs": 0}
    proj = root / "projects"
    if not proj.exists():
        return None
    for f in sorted(proj.rglob("*.jsonl")):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or '"usage"' not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage") or {}
            if not usage:
                continue
            mid = msg.get("id"); reqid = rec.get("requestId") or rec.get("request_id")
            key = (mid, reqid)
            if mid and key in seen:
                continue
            if mid:
                seen.add(key)
            model = msg.get("model") or rec.get("model") or "unknown"
            if model in ("<synthetic>", "synthetic"):
                continue
            tin = int(usage.get("input_tokens", 0) or 0)
            tout = int(usage.get("output_tokens", 0) or 0)
            tcr = int(usage.get("cache_read_input_tokens", 0) or 0)
            tcw = int(usage.get("cache_creation_input_tokens", 0) or 0)
            if tin + tout + tcr + tcw == 0:
                continue
            day = str(rec.get("timestamp") or msg.get("timestamp") or "")[:10]
            if (since and day and day < since) or (until and day and day > until):
                continue
            cost = rec.get("costUSD")
            if cost is None:
                cost = msg.get("costUSD")
            if cost is None:
                r = rate_for(model)
                cost = ((tin*r[0] + tout*r[1] + tcr*r[2] + tcw*r[3]) / 1e6) if r else 0.0
            cost = float(cost)
            a = agg.setdefault(model, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "msgs": 0})
            for k, v in (("cost", cost), ("in", tin), ("out", tout), ("cr", tcr), ("cw", tcw), ("msgs", 1)):
                a[k] += v; total[k] += v
            d = daily.setdefault(day or "?", {"cost": 0.0, "tokens": 0})
            d["cost"] += cost; d["tokens"] += tin + tout + tcr + tcw
            sessions.add(rec.get("sessionId") or f.stem)
    return {"models": agg, "daily": daily, "sessions": sessions, "total": total}

# ---------- GitHub Copilot (Premium requests usage report CSV) ----------
def parse_copilot(path: Path, since, until):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = {(c or "").strip().lower(): c for c in (reader.fieldnames or [])}
        if "model" not in cols:
            return {"error": "no 'model' column - this looks like a metered usage report. "
                    "Download the *Premium requests usage report* (per-model) instead.",
                    "headers": list(cols)}
        def g(row, key):
            c = cols.get(key)
            return row.get(c, "") if c else ""
        agg = {}; daily = {}; users = set()
        total = {"net": 0.0, "gross": 0.0, "disc": 0.0, "qty": 0.0, "rows": 0, "billed_qty": 0.0}
        for row in reader:
            model = (g(row, "model") or "unknown").strip()
            day = str(g(row, "date"))[:10]
            if (since and day and day < since) or (until and day and day > until):
                continue
            qty = num(g(row, "quantity"))
            gross = num(g(row, "gross_amount")); disc = num(g(row, "discount_amount"))
            net = num(g(row, "net_amount"))
            billed = str(g(row, "exceeds_quota")).strip().upper() == "TRUE"
            user = (g(row, "username") or "").strip()
            if user:
                users.add(user)
            a = agg.setdefault(model, {"net": 0.0, "gross": 0.0, "disc": 0.0, "qty": 0.0,
                                       "rows": 0, "billed_qty": 0.0})
            a["net"] += net; a["gross"] += gross; a["disc"] += disc; a["qty"] += qty
            a["rows"] += 1; a["billed_qty"] += qty if billed else 0
            total["net"] += net; total["gross"] += gross; total["disc"] += disc
            total["qty"] += qty; total["rows"] += 1; total["billed_qty"] += qty if billed else 0
            d = daily.setdefault(day or "?", {"net": 0.0, "qty": 0.0})
            d["net"] += net; d["qty"] += qty
    return {"models": agg, "daily": daily, "users": users, "total": total}

# ---------- shared rendering ----------
def chart(items, unit, c, cols, ascii_mode):
    if not items:
        return []
    lbl_w = min(26, max(len(l) for l, _ in items))
    cells = max(12, min(44, cols - lbl_w - 16))
    vmax = max(v for _, v in items) or 1
    step, axis_max = nice_axis(vmax)
    ticks, k = [], 0
    while k * step <= axis_max + 1e-9:
        ticks.append(k * step); k += 1
    tcols = {round(t / axis_max * cells): t for t in ticks}
    out = []
    for label, val in items:
        units = val / axis_max * cells
        full = int(units); rem = round((units - full) * 8)
        fill = "\u2588" * full + (EIGHTHS[rem] if rem and full < cells else "")
        if val > 0 and not fill:
            fill = EIGHTHS[1]
        tail = "".join("\u250a" if i in tcols else " " for i in range(len(fill), cells)) \
            if not ascii_mode else " " * (cells - len(fill))
        bar = (fill + tail) if ascii_mode else c("teal", fill) + c("dim", tail)
        out.append(label.rjust(lbl_w) + " " + c("dim", VLINE) + bar + "  " + fmt(val, unit))
    axis = "\u2514" + "".join("\u2534" if (i in tcols and i > 0) else "\u2500" for i in range(cells))
    out.append(" " * (lbl_w + 1) + c("dim", axis))
    width = lbl_w + 2 + cells + 12
    trow = [" "] * width
    for col, t in sorted(tcols.items()):
        s = (f"${t:g}" if unit == "$" else human(t))
        start = lbl_w + 2 + col
        for j, ch in enumerate(s):
            if 0 <= start + j < width:
                trow[start + j] = ch
    out.append(c("dim", "".join(trow).rstrip()))
    return out

def setup_color(mode):
    on = (mode == "always" or (mode == "auto" and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None))
    C = {} if not on else {"teal": "\x1b[38;2;29;158;117m", "amber": "\x1b[38;2;239;159;39m",
                           "dim": "\x1b[2m", "bold": "\x1b[1m", "reset": "\x1b[0m"}
    def c(k, s): return f"{C.get(k,'')}{s}{C['reset']}" if k in C else s
    return c

def render_claude(data, args, c, cols):
    models, total, daily = data["models"], data["total"], data["daily"]
    days = sorted(d for d in daily if d != "?")
    span = f"{days[0]} \u2192 {days[-1]}" if days else "all time"
    by_tokens = args.by == "tokens"
    rows = sorted(models.items(),
                  key=lambda kv: -(kv[1]["in"]+kv[1]["out"]+kv[1]["cr"]+kv[1]["cw"] if by_tokens else kv[1]["cost"]))
    out = ["", c("dim", f"token spend \u00b7 Claude Code \u00b7 {args.dir}"),
           f"{c('bold', money(total['cost']))} total   "
           f"{human(total['in']+total['out']+total['cr']+total['cw'])} tokens   "
           f"{total['msgs']} msgs   {len(data['sessions'])} sessions   {c('dim', span)}", ""]
    items = [(short_model(m), (a["in"]+a["out"]+a["cr"]+a["cw"]) if by_tokens else a["cost"])
             for m, a in rows[: args.top]]
    out += [c("dim", f"by {args.by}")] + chart(items, "tok" if by_tokens else "$", c, cols, args.ascii)
    out += ["", c("bold", "per model") + c("dim", "   cost \u00b7 in / out / cache-read / cache-write")]
    for m, a in rows:
        out.append("  " + c("teal", DOT) + " " + short_model(m))
        out.append("      " + c("dim", f"{money(a['cost'])}  \u00b7  {a['msgs']} msgs  \u00b7  "
                    f"{human(a['in'])} in / {human(a['out'])} out / {human(a['cr'])} cR / {human(a['cw'])} cW"))
    if args.daily and days:
        out += ["", c("bold", "by day")]
        dmax = max(daily[d]["cost"] for d in days) or 1
        for d in days:
            n = round(daily[d]["cost"] / dmax * 24)
            seg = c("amber", BLOCK * n) if not args.ascii else "#" * n
            out.append(f"  {d}  {seg}  {money(daily[d]['cost'])}")
    out += ["", c("dim", "cost from each message's logged value when present, else Anthropic "
            "rates (Sonnet $3/$15, Opus $5/$25, Haiku $1/$5; cache-read ~10% in) \u00b7 fully local")]
    return out

def render_copilot(data, args, c, cols):
    models, total, daily = data["models"], data["total"], data["daily"]
    days = sorted(d for d in daily if d != "?")
    span = f"{days[0]} \u2192 {days[-1]}" if days else "all time"
    # default bar metric is $ billed; if nothing billable, fall back to request count
    by_req = args.by == "tokens" or (args.by == "cost" and total["net"] == 0)
    note = ""
    if by_req and args.by == "cost":
        note = "  (all usage within included quota \u2014 charting request count)"
    rows = sorted(models.items(), key=lambda kv: -(kv[1]["qty"] if by_req else kv[1]["net"]))
    out = ["", c("dim", f"premium-request spend \u00b7 GitHub Copilot \u00b7 {args.copilot}"),
           f"{c('bold', money(total['net']))} billed   {money(total['gross'])} gross   "
           f"{human(total['qty'])} requests   {len(data['users'])} users   {c('dim', span)}", ""]
    items = [((m[:26]), (a["qty"] if by_req else a["net"])) for m, a in rows[: args.top]]
    out += [c("dim", ("by requests" if by_req else "by net $ billed") + note)]
    out += chart(items, "req" if by_req else "$", c, cols, args.ascii)
    out += ["", c("bold", "per model") + c("dim", "   net $ \u00b7 gross $ \u00b7 requests (billed / included)")]
    for m, a in rows:
        incl = a["qty"] - a["billed_qty"]
        out.append("  " + c("teal", DOT) + " " + m)
        out.append("      " + c("dim", f"{money(a['net'])} billed  \u00b7  {money(a['gross'])} gross  \u00b7  "
                    f"{human(a['qty'])} req ({human(a['billed_qty'])} billed / {human(incl)} included)"))
    if args.daily and days:
        out += ["", c("bold", "by day")]
        dmax = max(daily[d]["net"] for d in days) or max((daily[d]["qty"] for d in days), default=1) or 1
        usev = "net" if total["net"] else "qty"
        for d in days:
            n = round(daily[d][usev] / dmax * 24)
            val = money(daily[d]["net"]) if usev == "net" else f"{human(daily[d]['qty'])} req"
            seg = c("amber", BLOCK * n) if not args.ascii else "#" * n
            out.append(f"  {d}  {seg}  {val}")
    out += ["", c("dim", "net_amount = billed after included-quota discount \u00b7 quantity = premium requests "
            "(model multipliers applied) \u00b7 authoritative server-side billing data")]
    return out

def main(argv=None):
    ap = argparse.ArgumentParser(description="Local offline token & cost tracker (Claude Code + GitHub Copilot).")
    default_dir = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    ap.add_argument("--dir", default=default_dir, help="Claude config dir (default ~/.claude)")
    ap.add_argument("--copilot", metavar="CSV", help="parse a GitHub Copilot Premium requests usage report CSV")
    ap.add_argument("--by", choices=["cost", "tokens"], default="cost",
                    help="chart metric (Copilot: cost=net $, tokens=request count)")
    ap.add_argument("--since"); ap.add_argument("--until")
    ap.add_argument("--today", action="store_true"); ap.add_argument("--week", action="store_true")
    ap.add_argument("--month", action="store_true"); ap.add_argument("--daily", action="store_true")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    ap.add_argument("--ascii", action="store_true"); ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    today = dt.date.today(); since, until = args.since, args.until
    if args.today:
        since = until = today.isoformat()
    elif args.week:
        since = (today - dt.timedelta(days=6)).isoformat()
    elif args.month:
        since = today.replace(day=1).isoformat()

    c = setup_color(args.color)
    cols = shutil.get_terminal_size((80, 24)).columns

    if args.copilot:
        p = Path(args.copilot).expanduser()
        if not p.exists():
            print(f"no such file: {p}", file=sys.stderr); return 2
        data = parse_copilot(p, since, until)
        if data.get("error"):
            print(data["error"]); print("headers found: " + ", ".join(data["headers"])); return 1
        if args.json:
            print(json.dumps({"source": "copilot", "csv": str(p), "since": since, "until": until,
                              "total": data["total"], "users": sorted(data["users"]),
                              "models": data["models"], "daily": data["daily"]}, indent=2)); return 0
        if not data["models"]:
            print("no premium-request usage in range."); return 0
        print("\n".join(render_copilot(data, args, c, cols)) + "\n"); return 0

    root = Path(args.dir).expanduser()
    data = parse_claude(root, since, until)
    if data is None:
        print(f"no Claude Code sessions found under {root}/projects (set --dir or CLAUDE_CONFIG_DIR)."); return 0
    if args.json:
        print(json.dumps({"source": "claude", "dir": str(root), "since": since, "until": until,
                          "total": data["total"], "sessions": len(data["sessions"]),
                          "models": data["models"], "daily": data["daily"]}, indent=2)); return 0
    if not data["models"]:
        print("no usage in range."); return 0
    print("\n".join(render_claude(data, args, c, cols)) + "\n"); return 0

if __name__ == "__main__":
    sys.exit(main())