"""
Canonical PowerShell-7 (``pwsh``) resolver — a CLI-layer discovery utility.

This is the **single** place that locates a usable PowerShell on the machine and
confirms it by *invoking* it (``$PSVersionTable``). It is deliberately
**non-intrusive**: it only *reads* the environment (``PATH``, known install
locations, an explicit ``PIPELINE_PWSH_PATH`` pin) and returns the absolute path
it discovered — it never edits the system or user ``PATH`` and never writes any
file. Stdlib only (mirrors ``convert.base.resolve_pandoc``); imported by
``cli.py`` only, so the deterministic core stays shell-agnostic.

The Python core never *needs* pwsh today (pandoc is the only subprocess). This
module powers the ``check`` diagnostic and the ``pwsh-path`` command, and is the
function any *future* pwsh-launching code routes through — pass ``min_major`` to
demand a usable version (e.g. ``resolve_pwsh(config, min_major=7)``).
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Probe command — arg-list, no shell. ``-NoProfile``/``-NoLogo`` certify the
# *install* (deterministic, CI-safe), not the caller's profile. We only ever run
# ``-Command`` here, which Windows ExecutionPolicy does not gate (that only
# blocks ``.ps1`` *files*) — a concern for a future consumer that runs scripts.
_VERSION_ARGS = ("-NoProfile", "-NoLogo", "-Command", "$PSVersionTable.PSVersion.ToString()")
_VERSION_RE = re.compile(r"^\d+\.\d+")


@dataclass(frozen=True)
class PwshInfo:
    """A discovered PowerShell candidate.

    ``path`` is the discovered/pinned absolute path — it is **not** guaranteed to
    be runnable (a broken install or a missing pin yields ``version=""`` /
    ``major=0``). Check ``usable`` (or pass ``min_major`` to ``resolve_pwsh``)
    before executing it.
    """

    path: str
    version: str  # e.g. "7.4.1"; "" if the probe could not run it
    major: int  # 7, 5, … or 0 if unknown
    source: str  # config | config-missing | which | which-preview | known-path | windows-powershell

    @property
    def is_v7(self) -> bool:
        """True when this is PowerShell 7 or newer."""
        return self.major >= 7

    @property
    def usable(self) -> bool:
        """True when the candidate actually ran and reported a version (safe to execute)."""
        return bool(self.version) and self.major >= 1


def _abspath(p: str) -> str:
    """Absolute form of *p* without resolving symlinks (keeps Store-alias shims intact)."""
    return str(Path(p).absolute())


def _is_file(p: str) -> bool:
    """True when *p* names an existing regular file."""
    return Path(p).is_file()


def known_pwsh_locations() -> list[str]:
    """Well-known absolute install paths for ``pwsh``, by OS (order-preserving, de-duped).

    Built from guarded ``os.environ`` lookups (missing vars are skipped), so it is
    safe on any platform. These are probed directly — no ``PATH`` mutation.
    """
    system = platform.system()
    paths: list[str] = []
    if system == "Windows":
        for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            base = os.environ.get(var)
            if base:
                paths.append(str(Path(base) / "PowerShell" / "7" / "pwsh.exe"))
        local = os.environ.get("LOCALAPPDATA")
        if local:  # Microsoft Store alias shim
            paths.append(str(Path(local) / "Microsoft" / "WindowsApps" / "pwsh.exe"))
    elif system == "Darwin":
        paths.extend(["/usr/local/bin/pwsh", "/opt/homebrew/bin/pwsh"])
    else:  # Linux and other POSIX
        paths.extend(
            [
                "/usr/bin/pwsh",
                "/usr/local/bin/pwsh",
                "/opt/microsoft/powershell/7/pwsh",
                "/snap/bin/pwsh",
            ]
        )
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def probe_pwsh_version(path: str, *, timeout: float = 5.0) -> str:
    """Run *path* and return its ``PSVersion`` string (e.g. ``"7.4.1"``), or ``""``.

    Any failure — missing binary, timeout, non-zero exit, unparseable output —
    collapses to ``""`` (treated as "cannot be used"). Output is ASCII version
    digits, so this is safe under a cp1252-redirected stdout.
    """
    try:
        result = subprocess.run(
            [path, *_VERSION_ARGS],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode != 0:
        return ""
    lines = (result.stdout or "").strip().splitlines()
    if not lines:
        return ""
    first = lines[0].strip()
    return first if _VERSION_RE.match(first) else ""


def _parse_major(version: str) -> int:
    """Leading integer of *version* (``"7.4.1"`` → ``7``), or ``0`` if absent."""
    m = re.match(r"^(\d+)", version)
    return int(m.group(1)) if m else 0


def _make_info(path: str, source: str, probe: bool) -> PwshInfo:
    version = probe_pwsh_version(path) if probe else ""
    return PwshInfo(path=path, version=version, major=_parse_major(version), source=source)


def _candidate_paths() -> list[tuple[str, str]]:
    """Existing auto-discovery candidates as ``(abspath, source)`` in precedence order.

    Excludes the explicit config pin (handled by ``resolve_pwsh`` first). Windows
    PowerShell 5.1 is appended **only on Windows**. De-duped by absolute path.
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def _add(candidate: str | None, source: str) -> None:
        if not candidate:
            return
        ap = _abspath(candidate)
        if ap not in seen:
            seen.add(ap)
            out.append((ap, source))

    _add(shutil.which("pwsh"), "which")
    _add(shutil.which("pwsh-preview"), "which-preview")
    for loc in known_pwsh_locations():
        if _is_file(loc):
            _add(loc, "known-path")
    if os.name == "nt":  # legacy Windows PowerShell 5.1 — Windows only
        ps = shutil.which("powershell")
        if not ps:
            sysroot = os.environ.get("SystemRoot")
            if sysroot:
                legacy = str(
                    Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
                )
                if _is_file(legacy):
                    ps = legacy
        _add(ps, "windows-powershell")
    return out


def resolve_pwsh(config=None, *, min_major: int = 0, probe: bool = True) -> PwshInfo | None:
    """Resolve a PowerShell executable non-intrusively (no ``PATH`` edits).

    Precedence (first candidate that exists **and** satisfies ``min_major`` wins):

    1. **Pin** — ``config.pwsh_path`` / ``PIPELINE_PWSH_PATH``. *Sticky*: if set,
       resolution commits to it. A valid file is probed (``source="config"``); a
       set-but-missing pin returns ``source="config-missing"`` (``major=0``) and
       **stops** — it never silently falls through to a different pwsh.
    2. ``shutil.which("pwsh")`` → ``which``.
    3. ``shutil.which("pwsh-preview")`` → ``which-preview``.
    4. first existing :func:`known_pwsh_locations` entry → ``known-path``.
    5. Windows PowerShell 5.1 (**Windows only**) → ``windows-powershell``.

    ``min_major`` *filters* (skip-and-continue), it does not merely annotate:
    ``0`` returns the first candidate that exists at all (so ``check`` can report a
    broken/old/5.1 install); ``7`` returns only PowerShell 7+; ``1`` returns the
    first *usable* candidate of any version. Returns ``None`` when nothing
    satisfies the floor (with no pin, that also means nothing was discovered).
    Satisfying ``min_major > 0`` requires ``probe=True``.
    """
    pin = (getattr(config, "pwsh_path", "") or "").strip()
    if pin:
        if _is_file(pin):
            info = _make_info(_abspath(pin), "config", probe)
        else:
            info = PwshInfo(path=_abspath(pin), version="", major=0, source="config-missing")
        return info if info.major >= min_major else None

    for path, source in _candidate_paths():
        info = _make_info(path, source, probe)
        if info.major >= min_major:
            return info
    return None
