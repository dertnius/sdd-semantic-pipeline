"""Offline test for otelmeter.py capture_content (Copilot prompt-content capture).

Feeds a synthetic OTLP/JSON trace span carrying gen_ai.input.messages /
gen_ai.output.messages (as Copilot emits when captureContent is enabled) through
extract_spans_json + capture_content, and asserts the JSONL record is correct and
deduped. No live Copilot / network needed.

Run:  python test/otel_content_test.py   (from the extension root)
"""
import importlib.util
import json
import os
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "otelmeter.py")

spec = importlib.util.spec_from_file_location("otelmeter", SCRIPT)
om = importlib.util.module_from_spec(spec)
spec.loader.exec_module(om)

SAMPLE = {
    "resourceSpans": [
        {
            "resource": {"attributes": [{"key": "session.id", "value": {"stringValue": "win-XYZ"}}]},
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "name": "chat",
                            "startTimeUnixNano": "1781740800000000000",
                            "attributes": [
                                {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
                                {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4.1"}},
                                {"key": "gen_ai.response.id", "value": {"stringValue": "resp-1"}},
                                {
                                    "key": "gen_ai.input.messages",
                                    "value": {"stringValue": '[{"role":"user","content":"refactor the parser please"}]'},
                                },
                                {
                                    "key": "gen_ai.output.messages",
                                    "value": {"stringValue": '[{"role":"assistant","content":"done"}]'},
                                },
                                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "10"}},
                                {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "5"}},
                            ],
                        }
                    ]
                }
            ],
        }
    ]
}

failures = 0


def ok(cond, msg):
    global failures
    if cond:
        print("  ok   " + msg)
    else:
        print("  FAIL " + msg)
        failures += 1


spans = om.extract_spans_json(SAMPLE)
ok(len(spans) == 1, "extract_spans_json returns 1 span")

lock = threading.Lock()
seen = set()
tmp = os.path.join(tempfile.mkdtemp(), "otel-content.jsonl")

n = om.capture_content(spans, tmp, lock, seen)
ok(n == 1, "capture_content wrote 1 record (got %d)" % n)

n2 = om.capture_content(spans, tmp, lock, seen)
ok(n2 == 0, "second call deduped to 0 (got %d)" % n2)

with open(tmp, encoding="utf-8") as fh:
    lines = [ln for ln in fh.read().splitlines() if ln.strip()]
ok(len(lines) == 1, "file has exactly 1 line")
rec = json.loads(lines[0])
ok(rec["session"] == "win-XYZ", "session captured from resource session.id")
ok(rec["model"] == "gpt-4.1", "model captured")
ok("refactor the parser please" in rec["input"], "input prompt content captured")
ok("done" in rec["output"], "output content captured")

# a span without content is skipped
no_content = {
    "resourceSpans": [
        {
            "resource": {"attributes": [{"key": "session.id", "value": {"stringValue": "win-2"}}]},
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "name": "chat",
                            "attributes": [
                                {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
                                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "3"}},
                            ],
                        }
                    ]
                }
            ],
        }
    ]
}
ok(om.capture_content(om.extract_spans_json(no_content), tmp, lock, set()) == 0, "no-content span writes nothing")

print("\n" + ("OTEL CONTENT CAPTURE OK" if failures == 0 else "%d FAILED" % failures))
raise SystemExit(0 if failures == 0 else 1)
