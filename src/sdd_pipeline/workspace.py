"""Inbox/outbox workspace contract (CLI-layer guard).

The pipeline operates a two-zone workspace:

* **inbox/** — every file that goes INTO the pipeline lives here (subfolders OK).
* **outbox/** — every artifact the pipeline produces lands here (subfolders OK).

This module resolves CLI path arguments against those two roots and, when
``enforce`` is on, rejects any input that is not under the inbox or any output
that is not under the outbox. It is a thin :mod:`pathlib` helper with no
pipeline dependencies, imported only by :mod:`sdd_pipeline.cli` and
:mod:`sdd_pipeline.dump` so the deterministic core modules stay untouched.

Path semantics: relative paths are interpreted relative to the current working
directory (the usual shell behaviour); absolute paths are taken as-is. The
contract is satisfied by *defaults that already point into the zones*
(``./inbox`` and ``./outbox/<sub>``) plus a containment check — not by
re-rooting whatever the user typed. Set ``PIPELINE_ENFORCE_WORKSPACE=false`` to
skip every check (used by tests and ad-hoc runs).
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Standard outbox sub-layout — one source of truth for default output homes ──
OUTBOX_INDEX = "index"  # vector store (index --output; search/tui --index)
OUTBOX_MD = "md"  # converted markdown (convert --output)
OUTBOX_CHUNKS = "chunks"  # exported chunks (export --output)
OUTBOX_REPORTS = "reports"  # convert/lint JSON reports
OUTBOX_VOCAB = "vocab"  # entity vocabulary (scan --vocab)
OUTBOX_TAXONOMY = "taxonomy"  # taxonomy + field vocabulary (scan-taxonomy)
OUTBOX_DUMP = "dump"  # dump.py diagnostic artifacts


class WorkspaceError(ValueError):
    """An input/output path violates the inbox/outbox contract.

    Subclasses :class:`ValueError` so the CLI's existing ``except (ValueError,
    ...)`` blocks degrade gracefully, but commands should catch it explicitly
    and exit 2 with the message.
    """


def _within(path: Path, root: Path) -> bool:
    """True if ``path`` is ``root`` itself or nested under it.

    Both are ``resolve()``d first so ``..`` traversal, symlinks, and (on
    Windows) the on-disk casing of existing components are normalised. For an
    output path that does not exist yet ``resolve()`` keeps the typed casing, so
    a case-insensitive string fallback covers the Windows-only mismatch.
    """
    rp = path.resolve()
    rr = root.resolve()
    if rp == rr or rp.is_relative_to(rr):
        return True
    if os.name == "nt":
        rp_s, rr_s = str(rp).casefold(), str(rr).casefold()
        return rp_s == rr_s or rp_s.startswith(rr_s + os.sep)
    return False


def resolve_input(
    user_path: str | os.PathLike[str] | None,
    *,
    inbox_dir: str | os.PathLike[str],
    enforce: bool,
    default_subpath: str | None = None,
) -> Path:
    """Resolve a CLI input argument against the inbox contract.

    ``user_path`` empty/None → the inbox root (optionally ``/ default_subpath``).
    Otherwise the path is taken as typed. Raises :class:`WorkspaceError` when
    ``enforce`` and the path is not under ``inbox_dir``.
    """
    inbox = Path(inbox_dir)
    if not user_path:
        target = inbox / default_subpath if default_subpath else inbox
    else:
        target = Path(user_path)
    if enforce and not _within(target, inbox):
        raise WorkspaceError(
            f"Input path '{target}' is outside the inbox ('{inbox}'). "
            "Place pipeline inputs under the inbox, or set "
            "PIPELINE_ENFORCE_WORKSPACE=false to bypass the workspace contract."
        )
    return target


def _resolve_output(
    user_path: str | os.PathLike[str] | None,
    *,
    outbox_dir: str | os.PathLike[str],
    enforce: bool,
    default_subpath: str,
    label: str,
) -> Path:
    outbox = Path(outbox_dir)
    target = Path(user_path) if user_path else outbox / default_subpath
    if enforce and not _within(target, outbox):
        raise WorkspaceError(
            f"{label} '{target}' is outside the outbox ('{outbox}'). "
            "Write pipeline outputs under the outbox, or set "
            "PIPELINE_ENFORCE_WORKSPACE=false to bypass the workspace contract."
        )
    return target


def resolve_output_dir(
    user_path: str | os.PathLike[str] | None,
    *,
    outbox_dir: str | os.PathLike[str],
    enforce: bool,
    default_subpath: str,
    create: bool = True,
) -> Path:
    """Resolve a CLI output-directory argument against the outbox contract.

    ``user_path`` empty/None → ``outbox_dir / default_subpath``. Creates the
    directory when ``create``. Raises :class:`WorkspaceError` when ``enforce``
    and the path is not under ``outbox_dir``.
    """
    target = _resolve_output(
        user_path,
        outbox_dir=outbox_dir,
        enforce=enforce,
        default_subpath=default_subpath,
        label="Output directory",
    )
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def resolve_output_file(
    user_path: str | os.PathLike[str] | None,
    *,
    outbox_dir: str | os.PathLike[str],
    enforce: bool,
    default_subpath: str,
    create_parent: bool = True,
) -> Path:
    """Resolve a CLI output-*file* argument (e.g. a report) against the contract.

    ``default_subpath`` is a relative file path under the outbox
    (e.g. ``"reports/quality-report.json"``). Creates the parent directory when
    ``create_parent``.
    """
    target = _resolve_output(
        user_path,
        outbox_dir=outbox_dir,
        enforce=enforce,
        default_subpath=default_subpath,
        label="Output file",
    )
    if create_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target


def resolve_index_path(
    user_path: str | os.PathLike[str] | None,
    *,
    outbox_dir: str | os.PathLike[str],
    enforce: bool,
    default_subpath: str = OUTBOX_INDEX,
) -> Path:
    """Resolve the vector-index path for ``search``/``tui``/``index``.

    The index is an *output* of ``index`` that ``search``/``tui`` read back, so
    it must live under the outbox in every role. Does not create the directory
    (a search just reads it). ``user_path`` empty/None → ``outbox/index``.
    """
    return _resolve_output(
        user_path,
        outbox_dir=outbox_dir,
        enforce=enforce,
        default_subpath=default_subpath,
        label="Index path",
    )


def ensure_inbox_exists(inbox_dir: str | os.PathLike[str], enforce: bool) -> None:
    """Raise :class:`WorkspaceError` when ``enforce`` and the inbox is missing.

    A missing inbox is a setup mistake; surfacing it here gives a clearer error
    than an empty glob ("No markdown files found"). The outbox, by contrast, is
    created on demand — a missing output directory is never a user error.
    """
    inbox = Path(inbox_dir)
    if enforce and not inbox.exists():
        raise WorkspaceError(
            f"Inbox '{inbox}' does not exist. Create it and place your source "
            "files under it, or set PIPELINE_ENFORCE_WORKSPACE=false."
        )
