"""
Stage 2: Generate Pandoc JSON AST from Confluence markdown files.

Wraps the pandoc CLI; requires pandoc >= 3.0 on PATH.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def generate_ast(
    md_path: Path,
    from_format: str = "gfm",
) -> dict:
    """
    Run pandoc on *md_path* and return the parsed JSON AST.

    Args:
        md_path:     Path to a markdown file.
        from_format: Pandoc --from format string (default ``gfm``).

    Returns:
        Parsed pandoc JSON AST as a Python dict.

    Raises:
        FileNotFoundError:          If pandoc is not on PATH.
        subprocess.CalledProcessError: If pandoc exits non-zero.
    """
    result = subprocess.run(
        [
            "pandoc",
            str(md_path),
            f"--from={from_format}",
            "--to=json",
            "--standalone",  # include meta block even when no frontmatter
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data: dict = json.loads(result.stdout)
    return data


def generate_ast_batch(
    md_paths: list[Path],
    from_format: str = "gfm",
    output_dir: Path | None = None,
) -> dict[Path, dict]:
    """
    Generate JSON ASTs for a list of markdown files.

    Args:
        md_paths:    Markdown files to process.
        from_format: Pandoc --from format string.
        output_dir:  If provided, write each AST as ``<stem>.ast.json`` there.

    Returns:
        Mapping from input path to parsed AST dict.
    """
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[Path, dict] = {}
    for path in md_paths:
        ast = generate_ast(path, from_format)
        if output_dir is not None:
            out = output_dir / f"{path.stem}.ast.json"
            out.write_text(json.dumps(ast, indent=2, ensure_ascii=False), encoding="utf-8")
        results[path] = ast
    return results


def pandoc_version() -> str:
    """Return the pandoc version string, or raise FileNotFoundError if missing."""
    result = subprocess.run(
        ["pandoc", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split("\n")[0]
