#!/usr/bin/env python3
"""
otelmeter.py - read GitHub Copilot / Claude Code OpenTelemetry locally and tally
per-MODEL token usage, grouped per SESSION. Zero dependencies.

Three ways to feed it (all local, no network out):
  1) --file PATH   parse a JSON-lines file written by Copilot's OTel FILE exporter
                   (exporterType "file" + outfile). Most reliable on locked-down boxes.
  2) (default)     run as a tiny OTLP/HTTP receiver on localhost:4318 (JSON + protobuf,
                   IPv4 + IPv6). Pass --traces so Copilot's span token usage is parsed.
  3) --report J    re-render a saved aggregates file.

Sessions are grouped by the OTel `session.id` resource attribute (one per VS Code
window). The file exporter appends across every window, so use --last N, --today,
or --session <id-prefix> to scope it.

Enable Copilot's export with `--print-config`, then FULLY RESTART VS Code.

Usage:
  python otelmeter.py --file copilot.jsonl [--last 5] [--today] [--detail] [--by cost]
  python otelmeter.py [--traces] [--verbose] [--save state.json]
  python otelmeter.py --report state.json [--session 1a2b3c]
  python otelmeter.py --print-config | --demo
"""
from __future__ import annotations
import argparse, datetime as dt, gzip, json, math, os, shutil, socket, struct, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BLOCK, VLINE, GRID, CORNER, TICK, DOT = "\u2588", "\u2502", "\u250a", "\u2514", "\u2534", "\u25cf"
BR, BRL = "\u251c\u2500", "\u2514\u2500"
HLINE = "\u2500"
MID = "\u00b7"
EIGHTHS = " \u258f\u258e\u258d\u258c\u258b\u258a\u2589\u2588"

RATE_HINTS = {
    "opus": (5.0, 25.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0),
    "gpt-4o": (2.5, 10.0), "gpt-4.1": (2.0, 8.0), "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4o-mini": (0.15, 0.6), "grok-3": (3.0, 15.0), "deepseek": (1.35, 5.4),
}
# Fallback rate (USD per 1M in/out) for models with no specific hint, so cost is
# never shown as $0.00. Tune with --default-rate IN/OUT.
DEFAULT_RATE = [1.0, 3.0]
TYPE_MAP = {"input": "in", "output": "out", "cacheread": "cr", "cachecreation": "cw",
            "cache_read": "cr", "cache_creation": "cw", "cache": "cr",
            "inputcached": "cr", "prompt": "in", "completion": "out"}

# ---------- minimal protobuf reader ----------
def _varint(buf, i):
    shift = res = 0
    while True:
        b = buf[i]; i += 1
        res |= (b & 0x7F) << shift
        if not b & 0x80:
            return res, i
        shift += 7

def _flds(buf):
    out, i, n = {}, 0, len(buf)
    while i < n:
        tag, i = _varint(buf, i)
        fno, wt = tag >> 3, tag & 7
        if wt == 0:
            v, i = _varint(buf, i)
        elif wt == 1:
            v = buf[i:i+8]; i += 8
        elif wt == 2:
            ln, i = _varint(buf, i); v = buf[i:i+ln]; i += ln
        elif wt == 5:
            v = buf[i:i+4]; i += 4
        else:
            break
        out.setdefault(fno, []).append(v)
    return out

def _anyvalue(buf):
    f = _flds(buf)
    if 1 in f: return f[1][-1].decode("utf-8", "replace")
    if 3 in f: return int(f[3][-1])
    if 4 in f: return struct.unpack("<d", f[4][-1])[0]
    if 2 in f: return bool(f[2][-1])
    return None

def _kv(buf):
    f = _flds(buf)
    k = f[1][-1].decode("utf-8", "replace") if 1 in f else ""
    return k, (_anyvalue(f[2][-1]) if 2 in f else None)

def _attrs(lst):
    return {k: v for k, v in (_kv(b) for b in (lst or []))}

def _session_attr(a):
    """session.id with the standard service.instance.id fallback."""
    return a.get("session.id") or a.get("service.instance.id")

def _resource_session(rmf):
    """session.id from a ResourceMetrics/ResourceSpans field map (Resource = field 1)."""
    if 1 in rmf:
        a = _attrs(_flds(rmf[1][-1]).get(1, []))
        return str(_session_attr(a) or "")
    return ""

def _number_dp(buf):
    f = _flds(buf)
    a = _attrs(f.get(7, []))
    if 3 in f: a["_ts"] = struct.unpack("<Q", f[3][-1])[0] / 1e9
    if 4 in f: return a, struct.unpack("<d", f[4][-1])[0]
    if 6 in f: return a, struct.unpack("<q", f[6][-1])[0]
    return a, 0

def _hist_dp(buf):
    f = _flds(buf)
    a = _attrs(f.get(9, []))
    if 3 in f: a["_ts"] = struct.unpack("<Q", f[3][-1])[0] / 1e9
    return a, (struct.unpack("<d", f[5][-1])[0] if 5 in f else 0.0)

def _metric(buf):
    f = _flds(buf)
    name = f[1][-1].decode("utf-8", "replace") if 1 in f else ""
    pts = []
    for g in f.get(5, []):
        for dp in _flds(g).get(1, []): pts.append(_number_dp(dp))
    for s in f.get(7, []):
        for dp in _flds(s).get(1, []): pts.append(_number_dp(dp))
    for h in f.get(9, []):
        for dp in _flds(h).get(1, []): pts.append(_hist_dp(dp))
    return name, pts

def extract_protobuf(body):
    metrics = []
    for rm in _flds(body).get(1, []):
        rmf = _flds(rm)
        sid = _resource_session(rmf)
        for sm in rmf.get(2, []):
            for m in _flds(sm).get(2, []):
                name, pts = _metric(m)
                pts = [({**a, "_session": a.get("_session") or sid or "unknown"}, v) for a, v in pts]
                metrics.append((name, pts))
    return metrics

def extract_spans_protobuf(body):
    spans = []
    for rs in _flds(body).get(1, []):
        rsf = _flds(rs)
        sid = _resource_session(rsf)
        for ss in rsf.get(2, []):
            for sp in _flds(ss).get(2, []):
                spf = _flds(sp)
                a = _attrs(spf.get(9, []))
                a["_session"] = a.get("gen_ai.conversation.id") or sid or "unknown"
                if 7 in spf: a["_ts"] = struct.unpack("<Q", spf[7][-1])[0] / 1e9
                spans.append(a)
    return spans

# ---------- OTLP/JSON ----------
def _jval(v):
    if "stringValue" in v: return v["stringValue"]
    if "intValue" in v: return int(v["intValue"])
    if "doubleValue" in v: return float(v["doubleValue"])
    if "boolValue" in v: return bool(v["boolValue"])
    return None

def _jattrs(lst):
    out = {}
    if isinstance(lst, dict):
        for k, v in lst.items():
            out[k] = _jval(v) if isinstance(v, dict) and any(
                x in v for x in ("stringValue", "intValue", "doubleValue", "boolValue")) else v
        return out
    for a in (lst or []):
        v = a.get("value")
        out[a.get("key")] = _jval(v) if isinstance(v, dict) else v
    return out

def _jsession(resource):
    a = _jattrs((resource or {}).get("attributes")) if resource else {}
    return _session_attr(a) or ""

def _jts(unixnano):
    try:
        return int(unixnano) / 1e9
    except (TypeError, ValueError):
        return None

def extract_json(obj):
    metrics = []
    for rm in obj.get("resourceMetrics", []):
        sid = _jsession(rm.get("resource"))
        def _dp_meta(dp):
            a = _jattrs(dp.get("attributes")); a["_session"] = a.get("_session") or sid or "unknown"
            ts = _jts(dp.get("timeUnixNano"))
            if ts: a["_ts"] = ts
            return a
        for sm in rm.get("scopeMetrics", []):
            for m in sm.get("metrics", []):
                name, pts = m.get("name", ""), []
                for kind in ("sum", "gauge"):
                    for dp in m.get(kind, {}).get("dataPoints", []):
                        pts.append((_dp_meta(dp),
                                    int(dp["asInt"]) if "asInt" in dp else float(dp.get("asDouble", 0))))
                for dp in m.get("histogram", {}).get("dataPoints", []):
                    pts.append((_dp_meta(dp), float(dp.get("sum", 0))))
                metrics.append((name, pts))
    return metrics

def extract_spans_json(obj):
    spans = []
    for rs in obj.get("resourceSpans", []):
        sid = _jsession(rs.get("resource"))
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                a = _jattrs(sp.get("attributes"))
                a["_session"] = a.get("gen_ai.conversation.id") or sid or "unknown"
                ts = _jts(sp.get("startTimeUnixNano") or sp.get("endTimeUnixNano"))
                if ts: a["_ts"] = ts
                spans.append(a)
    return spans

# ---------- file (JSON lines) ----------
def _flatten(o, prefix, out):
    if isinstance(o, dict):
        for k, v in o.items():
            _flatten(v, prefix + str(k) + ".", out)
    elif not isinstance(o, list):
        out[prefix[:-1]] = o
    return out

def _deep_find(o, names, depth=0):
    if depth > 8 or o is None:
        return None
    if isinstance(o, dict):
        for k, v in o.items():
            if str(k).lower() in names and not isinstance(v, (dict, list)) and v not in ("", None):
                return v
        for v in o.values():
            r = _deep_find(v, names, depth + 1)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _deep_find(v, names, depth + 1)
            if r is not None:
                return r
    return None

def _attrs_from_resource(res):
    if not isinstance(res, dict):
        return {}
    a = res.get("attributes") if res.get("attributes") is not None else res.get("_attributes")
    d = _jattrs(a) if a else {}
    raw = res.get("_rawAttributes") or res.get("_syncAttributes")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                d.setdefault(str(item[0]), item[1])
            elif isinstance(item, dict) and "key" in item:
                d.setdefault(str(item["key"]), item.get("value"))
    return d

def _record_session(obj):
    ra = _attrs_from_resource(obj.get("resource") if isinstance(obj, dict) else None)
    s = _session_attr(ra)
    if s:
        return str(s)
    s = _deep_find(obj, {"session.id", "sessionid"})
    return str(s) if s else ""

def _record_trace(obj):
    sc = obj.get("spanContext") if isinstance(obj, dict) else None
    if isinstance(sc, dict) and sc.get("traceId"):
        return str(sc["traceId"])
    t = _deep_find(obj, {"traceid", "trace_id"})
    return str(t) if t else ""

def _hrtime(v):
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return float(v[0]) + float(v[1]) / 1e9
    return None

def _record_ts(obj):
    if not isinstance(obj, dict):
        return None
    for key in ("hrTime", "hrTimeObserved", "startTime", "endTime"):
        t = _hrtime(obj.get(key))
        if t:
            return t
    ts = _jts(obj.get("startTimeUnixNano") or obj.get("timeUnixNano") or obj.get("endTimeUnixNano"))
    if ts:
        return ts
    for key in ("startTime", "timestamp", "time"):
        v = obj.get(key)
        if isinstance(v, (int, float)):
            if v > 1e17: return v / 1e9
            if v > 1e14: return v / 1e6
            if v > 1e11: return v / 1e3
            if v > 1e8:  return float(v)
    return None

def _model_fallback(obj, attrs):
    if _model(attrs) != "unknown":
        return
    m = _deep_find(obj, {"gen_ai.request.model", "gen_ai.response.model", "request.model",
                         "response.model", "model", "model_id"})
    if m:
        attrs["model"] = str(m)

def _span_record(src, parent_sid=""):
    """Build a span attribute dict from a file-format record (its own attributes)."""
    a = _jattrs(src["attributes"])
    a["_session"] = a.get("gen_ai.conversation.id") or _record_session(src) or parent_sid or "unknown"
    a["_trace"] = _record_trace(src)
    ts = _record_ts(src)
    if ts: a["_ts"] = ts
    _model_fallback(src, a)
    return a

def collect_file_obj(obj, metrics, spans):
    if not isinstance(obj, dict):
        return
    matched = False
    if "resourceMetrics" in obj:
        metrics.extend(extract_json(obj)); matched = True
    if "resourceSpans" in obj:
        spans.extend(extract_spans_json(obj)); matched = True
    if "scopeMetrics" in obj:
        metrics.extend(extract_json({"resourceMetrics": [obj]})); matched = True
    if "scopeSpans" in obj:
        spans.extend(extract_spans_json({"resourceSpans": [obj]})); matched = True
    parent_sid = _record_session(obj)
    for sp in (obj.get("spans") or []):
        if isinstance(sp, dict) and "attributes" in sp:
            spans.append(_span_record(sp, parent_sid)); matched = True
    if not matched and "attributes" in obj:
        spans.append(_span_record(obj)); matched = True
    if not matched:
        flat = _flatten(obj, "", {})
        if any(str(k).lower().endswith(("input_tokens", "output_tokens")) for k in flat):
            flat["_session"] = _record_session(obj) or "unknown"
            flat["_trace"] = _record_trace(obj)
            ts = _record_ts(obj)
            if ts: flat["_ts"] = ts
            spans.append(flat)

def parse_otel_file(path):
    metrics, spans, lines = [], [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            lines += 1
            collect_file_obj(obj, metrics, spans)
    return metrics, spans, lines

def inspect_file(path, c, n=60000):
    from collections import Counter
    tok = with_sid = with_ts = 0
    sample_with = sample_without = None
    shapes = Counter()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            shapes[" ".join(sorted(obj)[:10])] += 1
            flat = _flatten(obj, "", {})
            if not any(str(k).lower().endswith(("input_tokens", "output_tokens")) for k in flat):
                continue
            tok += 1
            sid = _record_session(obj); ts = _record_ts(obj)
            if sid: with_sid += 1
            if ts: with_ts += 1
            if sid and sample_with is None: sample_with = (obj, flat)
            if not sid and sample_without is None: sample_without = (obj, flat)
    out = ["", c("bold", "line shapes (top-level key sets / count):")]
    for sig, cnt in shapes.most_common(10):
        out.append(f"  {cnt:>7}  {sig}")
    out += ["", c("bold", "token-bearing records") +
            f"  {tok} total {MID} {with_sid} with session.id {MID} {with_ts} with a timestamp", ""]

    def dump(label, pair):
        if not pair:
            out.append(c("dim", label + ": (none found)")); out.append(""); return
        obj, flat = pair
        out.append(c("bold", label))
        out.append(c("dim", "  top-level keys: " + ", ".join(str(k) for k in list(obj)[:14])))
        for k in sorted(flat):
            v = str(flat[k])
            if len(v) > 46:
                v = v[:46] + "..."
            out.append("  " + k + " = " + v)
        out.append("")

    dump("RECORD WITHOUT session.id  (this is the 'unknown / no time' bucket)", sample_without)
    dump("record WITH session.id  (for comparison)", sample_with)
    out.append(c("dim", "paste the line-shapes list + the WITHOUT-session block; that pins down the fix."))
    return out

# ---------- aggregation (per session -> per model) ----------
def _model(attrs):
    for k in ("gen_ai.request.model", "gen_ai.response.model", "model", "gen_ai.model", "llm.model_name"):
        if attrs.get(k):
            return str(attrs[k])
    for k, v in attrs.items():
        if str(k).lower().endswith("model") and v:
            return str(v)
    return "unknown"

def _ttype(attrs):
    for k in ("gen_ai.token.type", "type", "token.type", "gen_ai.usage.token_type"):
        if attrs.get(k):
            return str(attrs[k]).lower().replace(" ", "").replace(".", "")
    return ""

def _ablank():
    return {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0}

def _sblank():
    return {"models": {}, "first": None, "last": None}

def _touch(S, ts):
    if not ts:
        return
    if S["first"] is None or ts < S["first"]: S["first"] = ts
    if S["last"] is None or ts > S["last"]: S["last"] = ts

def _group_key(attrs, mode):
    if mode == "session":
        return attrs.get("_session") or "unknown"
    if mode == "trace":
        return attrs.get("_trace") or "no trace"
    ts = attrs.get("_ts")
    if mode in ("day", "hour"):
        if not ts:
            return "no date"
        return time.strftime("%Y-%m-%d" if mode == "day" else "%Y-%m-%d %H:00", time.localtime(ts))
    return attrs.get("_session") or "unknown"

def ingest(metrics, sessions, lock, skip_genai_tokens=False, group="day"):
    pts = 0
    with lock:
        for name, points in metrics:
            ln = name.lower()
            is_cost, is_tok = "cost" in ln, "token" in ln
            if not (is_cost or is_tok):
                continue
            if is_tok and skip_genai_tokens and ln.startswith("gen_ai"):
                continue
            for attrs, val in points:
                pts += 1
                S = sessions.setdefault(_group_key(attrs, group), _sblank())
                _touch(S, attrs.get("_ts"))
                a = S["models"].setdefault(_model(attrs), _ablank())
                if is_cost:
                    a["cost"] += float(val)
                else:
                    a[TYPE_MAP.get(_ttype(attrs), "in")] += int(val)
    return pts

def _exact(attrs, *keys):
    low = {str(k).lower(): v for k, v in attrs.items()}
    for k in keys:
        v = low.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    pass
    return 0

def ingest_spans(spans, sessions, lock, group="day", seen=None):
    seen = set() if seen is None else seen
    used = 0
    with lock:
        for attrs in spans:
            if str(attrs.get("gen_ai.operation.name", "")).lower() == "invoke_agent":
                continue  # session-total span; skip to avoid double-counting per-call usage
            rid = attrs.get("gen_ai.response.id") or attrs.get("gen_ai.response_id")
            if rid is not None:
                if rid in seen:
                    continue
                seen.add(rid)
            tin = _exact(attrs, "gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "prompt_tokens", "input_tokens")
            tout = _exact(attrs, "gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens", "completion_tokens", "output_tokens")
            tcr = _exact(attrs, "gen_ai.usage.cache_read.input_tokens", "gen_ai.usage.cache_read_input_tokens", "cache_read_input_tokens")
            tcw = _exact(attrs, "gen_ai.usage.cache_creation.input_tokens", "gen_ai.usage.cache_creation_input_tokens", "cache_creation_input_tokens")
            if tin or tout or tcr or tcw:
                S = sessions.setdefault(_group_key(attrs, group), _sblank())
                _touch(S, attrs.get("_ts"))
                a = S["models"].setdefault(_model(attrs), _ablank())
                a["in"] += tin; a["out"] += tout; a["cr"] += tcr; a["cw"] += tcw
                used += 1
    return used

def _content_first(attrs, *keys):
    low = {str(k).lower(): v for k, v in attrs.items()}
    for k in keys:
        v = low.get(k)
        if v not in (None, ""):
            return v
    return None

def capture_content(spans, path, lock, seen):
    """Append prompt/response content from spans to a JSONL file when Copilot's
    captureContent is on (gen_ai.input.messages / gen_ai.output.messages). Off by
    default; never affects token aggregation. Deduped by (response id, timestamp)."""
    recs = []
    for attrs in spans:
        if str(attrs.get("gen_ai.operation.name", "")).lower() == "invoke_agent":
            continue
        inp = _content_first(attrs, "gen_ai.input.messages", "gen_ai.prompt", "gen_ai.request.messages")
        outp = _content_first(attrs, "gen_ai.output.messages", "gen_ai.completion", "gen_ai.response.messages")
        sysm = _content_first(attrs, "gen_ai.system_instructions", "gen_ai.system.instructions")
        if inp is None and outp is None:
            continue
        rid = attrs.get("gen_ai.response.id") or attrs.get("gen_ai.response_id") or attrs.get("_trace")
        key = (str(rid), str(attrs.get("_ts")))
        if rid is not None:
            if key in seen:
                continue
            seen.add(key)
        rec = {"session": attrs.get("_session") or "unknown", "ts": attrs.get("_ts"),
               "model": _model(attrs), "response_id": rid}
        if inp is not None: rec["input"] = inp
        if outp is not None: rec["output"] = outp
        if sysm is not None: rec["system"] = sysm
        recs.append(rec)
    if not recs:
        return 0
    n = 0
    with lock:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                for rec in recs:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); n += 1
        except OSError:
            return 0
    return n

def flat_models(sessions):
    agg = {}
    for S in sessions.values():
        for m, a in S["models"].items():
            t = agg.setdefault(m, _ablank())
            for k in ("in", "out", "cr", "cw"): t[k] += a[k]
            t["cost"] += a["cost"]
    return agg

# ---------- rendering ----------
def nice_axis(vmax, target=7):
    if vmax <= 0: return 1, 1
    raw = vmax / target
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = mag
    for mlt in (1, 2, 2.5, 5, 10):
        step = mlt * mag
        if raw <= step: break
    return step, math.ceil(vmax / step) * step

def human(n):
    n = float(n)
    return f"{n/1e6:.1f}M" if n >= 1e6 else f"{n/1e3:.1f}k" if n >= 1e3 else str(int(round(n)))

def money(v):
    return f"${v:,.4f}" if 0 < abs(v) < 1 else f"${v:,.2f}"

def est_cost(model, a):
    if a["cost"]:
        return a["cost"], False
    rate = next((r for key, r in RATE_HINTS.items() if key in model.lower()), DEFAULT_RATE)
    return (a["in"] + a["cr"] + a["cw"]) * rate[0] / 1e6 + a["out"] * rate[1] / 1e6, True

def _bars(items, unit, c, cols, ascii_mode):
    out = []
    lbl_w = min(30, max(len(l) for l, _ in items))
    cells = max(12, min(40, cols - lbl_w - 16))
    vmax = max(v for _, v in items) or 1
    step, amax = nice_axis(vmax)
    ticks, k = [], 0
    while k * step <= amax + 1e-9:
        ticks.append(k * step); k += 1
    tcols = {round(t / amax * cells): t for t in ticks}
    for label, val in items:
        u = val / amax * cells; full = int(u); rem = round((u - full) * 8)
        fill = BLOCK * full + (EIGHTHS[rem] if rem and full < cells else "")
        if val > 0 and not fill:
            fill = EIGHTHS[1]
        tail = "".join(GRID if i in tcols else " " for i in range(len(fill), cells)) \
            if not ascii_mode else " " * (cells - len(fill))
        bar = (fill + tail) if ascii_mode else c("teal", fill) + c("dim", tail)
        v = human(val) + " tok" if unit == "tokens" else money(val)
        out.append(label.rjust(lbl_w) + " " + c("dim", VLINE) + bar + "  " + v)
    axis = CORNER + "".join(TICK if (i in tcols and i > 0) else HLINE for i in range(cells))
    out.append(" " * (lbl_w + 1) + c("dim", axis))
    trow = [" "] * (lbl_w + 2 + cells + 12)
    for col, t in sorted(tcols.items()):
        s = (f"${t:g}" if unit == "$" else human(t)); start = lbl_w + 2 + col
        for j, ch in enumerate(s):
            if 0 <= start + j < len(trow): trow[start + j] = ch
    out.append(c("dim", "".join(trow).rstrip()))
    return out

def render_models(agg, by, c, cols, ascii_mode, heading="totals across all sessions"):
    if not agg:
        return [c("dim", "no per-model token data captured yet.")]
    rows = sorted(agg.items(),
                  key=lambda kv: -(kv[1]["in"]+kv[1]["out"]+kv[1]["cr"]+kv[1]["cw"] if by == "tokens"
                                   else est_cost(kv[0], kv[1])[0]))
    tot_tok = sum(a["in"]+a["out"]+a["cr"]+a["cw"] for _, a in rows)
    tot_cost = sum(est_cost(m, a)[0] for m, a in rows)
    out = ["", c("bold", human(tot_tok) + " tokens") + "   ~" + money(tot_cost) + f"   {len(rows)} models", "",
           c("dim", heading + " " + MID + " by " + ("tokens" if by == "tokens" else "estimated $"))]
    out += _bars([(m[:30], (a["in"]+a["out"]+a["cr"]+a["cw"] if by == "tokens" else est_cost(m, a)[0]))
                  for m, a in rows], "tokens" if by == "tokens" else "$", c, cols, ascii_mode)
    out += ["", c("bold", "per model") + c("dim", "   in / out / cacheR / cacheW " + MID + " ~cost")]
    for m, a in rows:
        cc, estd = est_cost(m, a)
        out.append("  " + c("teal", DOT) + " " + m[:40])
        out.append("      " + c("dim", f"{human(a['in'])} in / {human(a['out'])} out / {human(a['cr'])} cR / "
                    f"{human(a['cw'])} cW  " + MID + "  ~" + money(cc) + (" (est)" if estd else "")))
    return out

def _stoks(S):
    return sum(a["in"]+a["out"]+a["cr"]+a["cw"] for a in S["models"].values())

def _scost(S):
    return sum(est_cost(m, a)[0] for m, a in S["models"].items())

def _ftime(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "no time"

def render_tree(sessions, args, c, cols):
    if not sessions:
        return [c("dim", "no per-model token data captured yet.")]
    items = []
    for sid, S in sessions.items():
        if args.session and not str(sid).startswith(args.session):
            continue
        if args.since or args.until:
            d = time.strftime("%Y-%m-%d", time.localtime(S["last"])) if S["last"] else None
            if d is None or (args.since and d < args.since) or (args.until and d > args.until):
                continue
        items.append((sid, S))
    if not items:
        return [c("dim", "no sessions match the filter.")]
    items.sort(key=lambda kv: (kv[1]["last"] or 0), reverse=True)
    if args.last and args.last > 0:
        items = items[: args.last]
    by = args.by
    g = args.group
    noun = {"session": "sessions", "day": "days", "hour": "hours", "trace": "traces"}.get(g, "groups")
    tot_tok = sum(_stoks(S) for _, S in items); tot_cost = sum(_scost(S) for _, S in items)
    out = ["", c("bold", f"{len(items)} {noun}") + "   " + human(tot_tok) + " tokens   ~" + money(tot_cost), ""]
    if args.bars:
        out += [c("dim", noun + ", most recent first " + MID + " by " + ("tokens" if by == "tokens" else "estimated $"))]
        out += _bars([((_ftime(S["last"]) + "  " + str(sid)[:8]) if g == "session" else str(sid),
                       (_stoks(S) if by == "tokens" else _scost(S))) for sid, S in items],
                     "tokens" if by == "tokens" else "$", c, cols, args.ascii)
        out += [""]
    for sid, S in items:
        toks = _stoks(S); cost = _scost(S)
        head = (c("bold", _ftime(S["last"])) + c("dim", "  " + str(sid)[:12])) if g == "session" else c("bold", str(sid))
        out.append(c("teal", DOT) + " " + head + "   " + human(toks) + " tok   ~" + money(cost))
        mods = sorted(S["models"].items(), key=lambda kv: -(kv[1]["in"]+kv[1]["out"]+kv[1]["cr"]+kv[1]["cw"]))
        for i, (m, a) in enumerate(mods):
            conn = BRL if i == len(mods) - 1 else BR
            mt = a["in"] + a["out"] + a["cr"] + a["cw"]; cc, estd = est_cost(m, a)
            extra = (f" / cR {human(a['cr'])}" if a["cr"] else "") + (f" / cW {human(a['cw'])}" if a["cw"] else "")
            out.append("  " + c("dim", conn) + " " + m[:30].ljust(30) +
                       c("dim", f" {human(mt)} tok  in {human(a['in'])} / out {human(a['out'])}" + extra +
                         f"  ~{money(cc)}" + (" est" if estd else "")))
    out += ["", c("dim", f"{len(items)} {noun} {MID} grouped by --group {g} {MID} "
            "--group session/day/hour/trace " + MID + " --last N / --today to scope " + MID + " --by-model for a flat total")]
    out += [c("dim", "deduped by gen_ai.response.id " + MID +
              " tokens authoritative; $ estimated unless a cost metric is present " + MID + " fully local")]
    return out

def setup_color(mode):
    on = (mode == "always" or (mode == "auto" and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None))
    C = {} if not on else {"teal": "\x1b[38;2;29;158;117m", "dim": "\x1b[2m", "bold": "\x1b[1m", "reset": "\x1b[0m"}
    def c(k, s): return f"{C.get(k,'')}{s}{C['reset']}" if k in C else s
    return c

CONFIG_TEXT = """\
EASIEST (no HTTP) - Copilot writes signals to a local file you then parse:
  VS Code settings.json:
    "github.copilot.chat.otel.enabled": true,
    "github.copilot.chat.otel.exporterType": "file",
    "github.copilot.chat.otel.outfile": "C:\\\\temp\\\\copilot-otel.jsonl"
  ...FULLY RESTART VS Code, send a Copilot message, then:
    python otelmeter.py --file C:\\temp\\copilot-otel.jsonl --last 5

LIVE (this receiver, IPv4+IPv6):
  VS Code settings.json:
    "github.copilot.chat.otel.enabled": true,
    "github.copilot.chat.otel.exporterType": "otlp-http",
    "github.copilot.chat.otel.otlpEndpoint": "http://localhost:4318"
  ...FULLY RESTART VS Code, then run:  python otelmeter.py --traces

OTel only turns on when one of these is set: github.copilot.chat.otel.enabled=true,
COPILOT_OTEL_ENABLED=true, or OTEL_EXPORTER_OTLP_ENDPOINT. A window reload is NOT
enough - quit VS Code completely and reopen. Token usage rides on `chat` spans.
"""

class _DualStack(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        super().server_bind()

def make_handler(sessions, lock, args, stats):
    seen = set()
    content_seen = set()
    class H(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            return
        def _ok(self, ctype):
            body = b"{}" if "json" in ctype else b""
            self.send_response(200)
            self.send_header("Content-Type", ctype if "json" in ctype else "application/x-protobuf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body: self.wfile.write(body)
        def do_GET(self):
            with lock:
                toks = sum(_stoks(S) for S in sessions.values()); nses = len(sessions)
            seen = ", ".join(f"{p}={n}" for p, n in stats["paths"].items()) or "(none yet)"
            page = (
                "otelmeter is running.\n\n"
                "OTLP/HTTP ingest endpoint: POST to /v1/metrics or /v1/traces, not browser GETs.\n\n"
                f"posts total   : {stats['posts']}   (metrics {stats['metrics']}, traces {stats['traces']}, "
                f"logs {stats['logs']}, other {stats['other']})\n"
                f"spans parsed  : {stats['spans']}   datapoints: {stats['datapoints']}\n"
                f"paths seen    : {seen}\n"
                f"sessions      : {nses}\n"
                f"tokens so far : {human(toks)}\n"
                f"last POST     : {stats['last'] or '-'}\n\n"
                "posts total still 0 -> Copilot is NOT exporting. Set\n"
                '  "github.copilot.chat.otel.enabled": true  and FULLY restart VS Code,\n'
                "or use the file exporter + --file (see --print-config).\n"
                "traces > 0 but spans 0 -> run this with --traces.\n")
            body = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            ln = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(ln) if ln else b""
            if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
                try: body = gzip.decompress(body)
                except OSError: pass
            ctype = (self.headers.get("Content-Type") or "").lower()
            path = self.path.rstrip("/")
            is_json = "json" in ctype
            stats["posts"] += 1
            stats["paths"][path] = stats["paths"].get(path, 0) + 1
            if args.verbose:
                sys.stderr.write(f"\n[recv] POST {self.path}  type={ctype or '?'}  bytes={len(body)}\n")
            try:
                if path.endswith("/v1/metrics"):
                    stats["metrics"] += 1
                    m = extract_json(json.loads(body)) if is_json else extract_protobuf(body)
                    stats["datapoints"] += ingest(m, sessions, lock, skip_genai_tokens=args.traces, group=args.group)
                elif path.endswith("/v1/traces"):
                    stats["traces"] += 1
                    if args.traces:
                        sp = extract_spans_json(json.loads(body)) if is_json else extract_spans_protobuf(body)
                        stats["spans"] += ingest_spans(sp, sessions, lock, group=args.group, seen=seen)
                        if getattr(args, "capture_content", None):
                            capture_content(sp, args.capture_content, lock, content_seen)
                elif path.endswith("/v1/logs"):
                    stats["logs"] += 1
                else:
                    stats["other"] += 1
                stats["last"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if args.save: _save(sessions, lock, args.save)
                sys.stderr.write(f"\r[otelmeter] posts:{stats['posts']} "
                                 f"(m:{stats['metrics']} t:{stats['traces']} l:{stats['logs']} o:{stats['other']}) "
                                 f"{MID} {len(sessions)} sessions {MID} "
                                 f"{human(sum(_stoks(S) for S in sessions.values()))} tok   ")
                sys.stderr.flush()
            except Exception as e:
                sys.stderr.write(f"\n[otelmeter] parse error on {path}: {e}\n")
            self._ok(ctype)
    return H

def _save(sessions, lock, path):
    with lock:
        snap = json.dumps({"sessions": sessions}, indent=2)
    try:
        with open(path, "w") as f: f.write(snap)
    except OSError:
        pass

def main(argv=None):
    ap = argparse.ArgumentParser(description="Local per-session, per-model token usage from Copilot / Claude Code OTel.")
    ap.add_argument("--file", metavar="JSONL", help="parse Copilot's OTel file-exporter output")
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=4318)
    ap.add_argument("--traces", action="store_true", help="also extract token usage from trace spans")
    ap.add_argument("--verbose", action="store_true", help="log every incoming request")
    ap.add_argument("--by", choices=["tokens", "cost"], default="tokens")
    ap.add_argument("--by-model", action="store_true", dest="by_model",
                    help="show totals per model across all sessions instead of per session")
    ap.add_argument("--group", choices=["session", "day", "hour", "trace"], default="day",
                    help="bucket usage by day (default), hour, trace id, or session.id")
    ap.add_argument("--detail", action="store_true", help="(kept for compatibility; tree always shows models)")
    ap.add_argument("--bars", action="store_true", help="also show the session overview bar chart")
    ap.add_argument("--last", type=int, default=0, help="show only the N most recent sessions (0 = all)")
    ap.add_argument("--session", metavar="PREFIX", help="only sessions whose id starts with PREFIX")
    ap.add_argument("--since"); ap.add_argument("--until")
    ap.add_argument("--today", action="store_true"); ap.add_argument("--week", action="store_true")
    ap.add_argument("--month", action="store_true")
    ap.add_argument("--save", metavar="JSON"); ap.add_argument("--report", metavar="JSON")
    ap.add_argument("--capture-content", metavar="JSONL", dest="capture_content",
                    help="append span prompt/response content to a JSONL file (needs Copilot "
                         "captureContent; privacy-sensitive). Implies --traces.")
    ap.add_argument("--interval", type=int, default=0)
    ap.add_argument("--rate", action="append", default=[], metavar="MODEL=IN/OUT")
    ap.add_argument("--default-rate", metavar="IN/OUT",
                    help="USD per 1M in/out for models with no known rate (default 1/3)")
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    ap.add_argument("--ascii", action="store_true")
    ap.add_argument("--print-config", action="store_true"); ap.add_argument("--demo", action="store_true")
    ap.add_argument("--inspect", action="store_true", help="dump the --file structure to adapt the parser")
    args = ap.parse_args(argv)

    for r in args.rate:
        try:
            name, io = r.split("=", 1); i, o = io.split("/")
            RATE_HINTS[name.lower()] = (float(i), float(o))
        except ValueError:
            print(f"bad --rate {r!r}, want MODEL=IN/OUT", file=sys.stderr); return 2
    if args.default_rate:
        try:
            i, o = args.default_rate.split("/")
            DEFAULT_RATE[0], DEFAULT_RATE[1] = float(i), float(o)
        except ValueError:
            print(f"bad --default-rate {args.default_rate!r}, want IN/OUT", file=sys.stderr); return 2

    if args.capture_content:
        args.traces = True  # content rides on trace spans

    today = dt.date.today()
    if args.today: args.since = args.until = today.isoformat()
    elif args.week: args.since = (today - dt.timedelta(days=6)).isoformat()
    elif args.month: args.since = today.replace(day=1).isoformat()

    c = setup_color(args.color)
    cols = shutil.get_terminal_size((80, 24)).columns
    lock = threading.Lock()

    def show(sessions):
        if args.by_model:
            return render_models(flat_models(sessions), args.by, c, cols, args.ascii)
        return render_tree(sessions, args, c, cols)

    if args.print_config:
        print(CONFIG_TEXT); return 0
    if args.inspect:
        if not args.file:
            print("use --inspect together with --file PATH", file=sys.stderr); return 2
        if not os.path.exists(args.file):
            print(f"no such file: {args.file}", file=sys.stderr); return 2
        print("\n".join(inspect_file(args.file, c)) + "\n"); return 0
    if args.report:
        try:
            blob = json.load(open(args.report))
        except OSError as e:
            print(f"cannot read {args.report}: {e}", file=sys.stderr); return 2
        sessions = blob.get("sessions") or ({"all": {"models": blob["models"], "first": None, "last": None}}
                                            if "models" in blob else {})
        print("\n".join(show(sessions)) + "\n"); return 0
    if args.file:
        if not os.path.exists(args.file):
            print(f"no such file: {args.file}", file=sys.stderr); return 2
        metrics, spans, lines = parse_otel_file(args.file)
        sessions = {}
        ingest(metrics, sessions, lock, skip_genai_tokens=bool(spans), group=args.group)
        used = ingest_spans(spans, sessions, lock, group=args.group, seen=set())
        if args.capture_content:
            capture_content(spans, args.capture_content, lock, set())
        if args.save:
            _save(sessions, lock, args.save)
        print(c("dim", f"parsed {lines} json lines {MID} {len(spans)} spans ({used} with tokens) {MID} "
                f"{len(sessions)} sessions {MID} {args.file}"))
        print("\n".join(show(sessions)) + "\n")
        if not sessions:
            print(c("dim", "No token data found. If the file has content, paste one line and I can fit the parser."))
        return 0
    if args.demo:
        sample = {"resourceSpans": [{"resource": {"attributes": [
            {"key": "session.id", "value": {"stringValue": "win-A1B2C3D4"}}]}, "scopeSpans": [{"spans": [
            {"name": "chat", "startTimeUnixNano": "1781740800000000000", "attributes": [
                {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
                {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4.1"}},
                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "240000"}},
                {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "9000"}}]}]}]}]}
        sessions = {}; ingest_spans(extract_spans_json(sample), sessions, lock, group=args.group, seen=set())
        print("\n".join(show(sessions)) + "\n"); return 0

    sessions = {}
    stats = {"posts": 0, "metrics": 0, "traces": 0, "logs": 0, "other": 0,
             "datapoints": 0, "spans": 0, "last": "", "paths": {}}
    handler = make_handler(sessions, lock, args, stats)
    srv, shown = None, args.host
    if args.host in ("127.0.0.1", "localhost", "::"):
        try:
            srv = _DualStack(("::", args.port), handler); shown = "localhost"
        except OSError:
            srv = None
    if srv is None:
        srv = ThreadingHTTPServer((args.host, args.port), handler)
    mode = "metrics + span tokens" if args.traces else "metrics only (add --traces for span tokens)"
    print(c("dim", f"otelmeter listening on http://{shown}:{args.port}  "
            f"(POST /v1/metrics, /v1/traces) {MID} {mode} {MID} Ctrl-C for report"))
    stop = threading.Event()
    if args.interval:
        def ticker():
            while not stop.wait(args.interval):
                sys.stderr.write("\n" + "\n".join(show(sessions)) + "\n")
        threading.Thread(target=ticker, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        stop.set()
        print("\n" + "\n".join(show(sessions)) + "\n")
        if args.save: _save(sessions, lock, args.save)
    return 0

if __name__ == "__main__":
    sys.exit(main())
