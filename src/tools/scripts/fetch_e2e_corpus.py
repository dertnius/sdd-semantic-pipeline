#!/usr/bin/env python
"""
Fetch the e2e corpus — the ONLY networked code in this project.

Reads ``src/tools/eval/e2e_sources.yaml`` and downloads each pinned URL into the gitignored
``src/tools/eval/e2e_corpus/``. HTML sources are converted to Markdown via the pipeline's
converter; Markdown sources are saved as-is. Pipeline code itself never touches the
network — this script is run manually before the (slow, skip-if-absent) e2e test.

    python src/tools/scripts/fetch_e2e_corpus.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "eval" / "e2e_corpus"
SOURCES = REPO / "eval" / "e2e_sources.yaml"


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "sdd-pipeline-e2e/1.0"})
    # URLs are pinned https sources from src/tools/eval/e2e_sources.yaml.
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main() -> int:
    sys.path.insert(0, str(REPO / "src"))
    import yaml

    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    CORPUS.mkdir(parents=True, exist_ok=True)

    for doc in sources["docs"]:
        url, dest, fmt = doc["url"], doc["dest"], doc.get("format", "md")
        print(f"Fetching {doc['name']} <- {url}")
        raw = _download(url)
        out = CORPUS / dest
        if fmt == "html":
            from sdd_pipeline.convert import convert_file

            tmp = CORPUS / f"{dest}.src.html"
            tmp.write_bytes(raw)
            convert_file(tmp, out, add_toc=False)
            tmp.unlink()
        else:
            out.write_bytes(raw)
        print(f"  -> {out.relative_to(REPO).as_posix()}  [{doc.get('license', '?')}]")

    print(f"\nDone. {len(sources['docs'])} docs in {CORPUS.relative_to(REPO).as_posix()}/")
    print("Run: PYTHONUTF8=1 pytest tests/test_e2e_real_docs.py -q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
