---
name: gliffy-to-drawio
description: Convert a Confluence Gliffy diagram (.gliffy JSON) into a draw.io / diagrams.net document (.drawio mxGraph XML). draw.io imports .gliffy natively but only in the online app (no headless/CLI path); this gives a reproducible, testable, scriptable route with an optional round-trip fidelity check. Use when someone has .gliffy files and wants .drawio / diagrams.net diagrams, or asks to "convert gliffy to drawio". Pure standard library — no pandoc, no third-party dependency.
---

# gliffy-to-drawio — Confluence Gliffy (.gliffy) → draw.io (.drawio)

draw.io imports `.gliffy` natively, but **only in the online app** — there is no
headless or CLI path — so it cannot run in a pipeline or in CI. This skill gives a
reproducible, scriptable `.gliffy → .drawio` route: parse the Gliffy JSON into an
engine-neutral diagram model, then emit mxGraph XML.

Coverage is **best-effort basic-shape**: rectangle / rounded-rectangle / ellipse /
diamond, poly-lines with arrowheads, text labels, embedded raster/SVG. Unknown stencils
become dashed placeholders. Both formats use a y-down / top-left coordinate system, so
geometry copies straight through (no axis flip). For editable native draw.io shapes of
complex diagrams, use draw.io's own online Gliffy import.

## Requirements

**None beyond Python 3.** Pure standard library (`xml.etree`, `base64`) — no pandoc,
no pip install.

## Usage

```bash
# One diagram → sample.drawio next to it
python scripts/convert_drawio.py diagram.gliffy

# A whole folder → mirror the tree under out/
python scripts/convert_drawio.py ./attachments -o ./out

# Convert AND verify fidelity per file (exit non-zero on any mismatch)
python scripts/convert_drawio.py ./attachments -o ./out --check
```

Open the resulting `.drawio` in <https://app.diagrams.net> or the VS Code "Draw.io
Integration" extension.

## Fidelity check

`--check` runs the **round-trip oracle**: parse → emit draw.io → re-parse → compare the
two models. It proves the emitter and parser are *self-consistent* (every field written
is read back identically) and that the XML is well-formed. It does **not** prove that
draw.io-the-app renders the file (that needs a human or headless export) — that is out
of scope for an automatable check.

## Files

| Path | Role |
|---|---|
| [scripts/convert_drawio.py](scripts/convert_drawio.py) | the CLI (single file or directory, optional `--check`) |
| [scripts/drawio.py](scripts/drawio.py) | `model_to_drawio` / `drawio_to_model` (model ⇄ mxGraph XML) |
| [scripts/gliffy_to_svg.py](scripts/gliffy_to_svg.py) | `parse_gliffy` (Gliffy JSON → model) |
| [scripts/diagram_model.py](scripts/diagram_model.py) | engine-neutral `Node`/`Edge`/`DiagramModel` |
| [scripts/fidelity.py](scripts/fidelity.py) | `roundtrip_check` / `compare_models` |
| [scripts/errors.py](scripts/errors.py) | the `ConversionError` type (keeps the path dependency-free) |

## Notes

- **Programmatic use**: `from drawio import convert_gliffy_to_drawio_file` returns the
  tuple `out_path`, `xml`, `metrics`; `from fidelity import roundtrip_check` returns a
  dict with `equal` / `summary` / `diffs`.
- **Need editable SVG instead?** Use the sibling `gliffy-to-svg` skill — both share the
  same `diagram_model.py`.
- **In-repo equivalent**: inside this project the same converter is
  `sdd-pipeline convert-drawio`; these vendored scripts are the standalone counterpart.
