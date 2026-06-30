---
name: gliffy-to-svg
description: Resolve a Confluence-embedded Gliffy diagram (a .gliffy JSON attachment, not an image) into a standalone, editable SVG. Prefers Gliffy's own sibling .svg export when present (exact fidelity), else renders the JSON — rectangles, rounded rectangles, ellipses, diamonds, poly-lines with arrowheads, text labels, embedded raster/SVG. Use when someone has .gliffy files from a Confluence export and wants editable SVG, or asks to "convert gliffy to svg". Pure standard library — no pandoc, no third-party dependency.
---

# gliffy-to-svg — Confluence Gliffy (.gliffy) → editable SVG

A Gliffy diagram is **JSON, not SVG**, and in a rendered Confluence HTML export it
appears only as a raster `<img>`; the editable vector data lives in a sibling page
**attachment** (`<name>.gliffy`, sometimes `<name>.svg`). This skill turns that
attachment into a real, schema-valid `.svg`.

Resolution order (highest fidelity first):

1. **Existing sibling SVG** — if Gliffy already exported `<name>.svg` next to the
   `.gliffy`, copy it verbatim (exact fidelity, already editable).
2. **Render the JSON** — walk `stage.objects` and emit SVG primitives.

Coverage is **best-effort basic-shape**: rectangle / rounded-rectangle / ellipse /
diamond, poly-lines with arrowheads, text labels, embedded raster images and embedded
SVG. Unknown stencils become dashed placeholder boxes (geometry preserved) and bump an
`unsupported` count so low-coverage diagrams are visible. For complex stencil-heavy
diagrams the high-fidelity route is Gliffy's own SVG export, or the `gliffy-to-drawio`
skill for editable native draw.io shapes.

## Requirements

**None beyond Python 3.** Pure standard library — no pandoc, no pip install.

## Usage

```bash
# One diagram → sample.svg next to it
python scripts/resolve_gliffy.py diagram.gliffy

# A whole folder → mirror the tree under out/
python scripts/resolve_gliffy.py ./attachments -o ./out

# Force re-render even when a sibling .svg exists
python scripts/resolve_gliffy.py diagram.gliffy --always-render
```

The CLI reports the method used (`existing_svg` vs `rendered`) and, when rendered,
how many objects were drawn and how many were unsupported.

## Files

| Path | Role |
|---|---|
| [scripts/resolve_gliffy.py](scripts/resolve_gliffy.py) | the CLI (single file or directory) |
| [scripts/gliffy_to_svg.py](scripts/gliffy_to_svg.py) | `render_gliffy`, `resolve_gliffy_file`, `parse_gliffy` |
| [scripts/diagram_model.py](scripts/diagram_model.py) | engine-neutral `Node`/`Edge`/`DiagramModel` (shared with `gliffy-to-drawio`) |
| [scripts/errors.py](scripts/errors.py) | the `ConversionError` type (keeps the path dependency-free) |

## Notes

- **Programmatic use**: `from gliffy_to_svg import render_gliffy` returns the pair
  `svg_text`, `metrics`; `resolve_gliffy_file` returns `out_path`, `svg`, `method`,
  `metrics`.
- **Editable output**: the SVG is well-formed, XML-escaped, single-root, and opens in
  any vector editor (Inkscape, Illustrator, browser).
- **In-repo equivalent**: inside this project the same resolver is
  `sdd-pipeline resolve-gliffy`; these vendored scripts are the standalone counterpart.
