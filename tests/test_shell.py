"""Tests for the PowerShell-7 resolver (``sdd_pipeline.shell``).

Model-free and OS-free: ``shutil.which``, the ``_is_file`` probe, ``os.name`` and
the version probe are all monkeypatched, so the same cases run on Windows dev
boxes and Linux CI. ``_abspath`` is patched to identity in the resolver fixture so
path assertions are platform-neutral.
"""

from __future__ import annotations

import types

import pytest

from sdd_pipeline import shell

# ── PwshInfo properties ──────────────────────────────────────────────────────


class TestPwshInfo:
    def test_v7_is_usable(self):
        info = shell.PwshInfo("/usr/bin/pwsh", "7.4.1", 7, "which")
        assert info.is_v7 is True
        assert info.usable is True

    def test_five_one_usable_but_not_v7(self):
        info = shell.PwshInfo("/win/powershell.exe", "5.1.19041.1", 5, "windows-powershell")
        assert info.is_v7 is False
        assert info.usable is True

    def test_unprobed_is_not_usable(self):
        info = shell.PwshInfo("/missing", "", 0, "config-missing")
        assert info.is_v7 is False
        assert info.usable is False


# ── known_pwsh_locations ─────────────────────────────────────────────────────


class TestKnownLocations:
    def test_windows_skips_missing_env_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shell.platform, "system", lambda: "Windows")
        for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
        locs = shell.known_pwsh_locations()
        # Missing Program* vars are skipped (no crash); the store-alias path survives.
        assert any("WindowsApps" in p for p in locs)
        assert all("PowerShell" not in p for p in locs)  # the Program*\PowerShell\7 entries

    def test_linux_locations(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shell.platform, "system", lambda: "Linux")
        locs = shell.known_pwsh_locations()
        assert "/usr/bin/pwsh" in locs
        assert "/opt/microsoft/powershell/7/pwsh" in locs

    def test_order_preserving_dedup(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shell.platform, "system", lambda: "Windows")
        same = r"C:\Program Files"
        monkeypatch.setenv("ProgramFiles", same)
        monkeypatch.setenv("ProgramW6432", same)  # identical on 64-bit → one entry
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        locs = shell.known_pwsh_locations()
        assert len(locs) == len(set(locs))
        assert len(locs) == 1


# ── probe_pwsh_version ───────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


class TestProbe:
    def test_parses_version(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: _FakeResult(0, "7.4.1\n"))
        assert shell.probe_pwsh_version("/fake/pwsh") == "7.4.1"

    def test_five_one_long_version(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            shell.subprocess, "run", lambda *a, **k: _FakeResult(0, "5.1.19041.4170\n")
        )
        assert shell.probe_pwsh_version("/fake/powershell.exe") == "5.1.19041.4170"

    def test_nonzero_exit_is_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: _FakeResult(1, "boom"))
        assert shell.probe_pwsh_version("/fake/pwsh") == ""

    def test_unparseable_is_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            shell.subprocess, "run", lambda *a, **k: _FakeResult(0, "not a version\n")
        )
        assert shell.probe_pwsh_version("/fake/pwsh") == ""

    def test_missing_binary_is_empty(self, monkeypatch: pytest.MonkeyPatch):
        def boom(*a, **k):
            raise FileNotFoundError

        monkeypatch.setattr(shell.subprocess, "run", boom)
        assert shell.probe_pwsh_version("/missing/pwsh") == ""

    def test_timeout_is_empty(self, monkeypatch: pytest.MonkeyPatch):
        def boom(*a, **k):
            raise shell.subprocess.TimeoutExpired(cmd="pwsh", timeout=5)

        monkeypatch.setattr(shell.subprocess, "run", boom)
        assert shell.probe_pwsh_version("/slow/pwsh") == ""


# ── resolve_pwsh ─────────────────────────────────────────────────────────────


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    which: dict[str, str] | None = None,
    known: list[str] | None = None,
    isfile: set[str] | None = None,
    versions: dict[str, str] | None = None,
    os_name: str = "posix",
) -> None:
    """Wire up a deterministic, platform-neutral resolver environment."""
    which = which or {}
    known = list(known or [])
    isfile_set = set(isfile or [])
    versions = versions or {}
    monkeypatch.setattr(shell, "_abspath", lambda p: p)  # identity → portable asserts
    monkeypatch.setattr(shell.shutil, "which", lambda name: which.get(name))
    monkeypatch.setattr(shell, "known_pwsh_locations", lambda: list(known))
    monkeypatch.setattr(shell, "_is_file", lambda p: p in isfile_set)
    monkeypatch.setattr(shell.os, "name", os_name)
    monkeypatch.setattr(shell, "probe_pwsh_version", lambda path, **kw: versions.get(path, ""))


class TestResolve:
    def test_found_on_path(self, monkeypatch: pytest.MonkeyPatch):
        _setup(monkeypatch, which={"pwsh": "/fake/pwsh"}, versions={"/fake/pwsh": "7.4.1"})
        info = shell.resolve_pwsh()
        assert info is not None
        assert (info.source, info.path, info.major) == ("which", "/fake/pwsh", 7)
        assert info.is_v7 and info.usable

    def test_found_via_known_location(self, monkeypatch: pytest.MonkeyPatch):
        _setup(
            monkeypatch,
            which={},
            known=["/opt/ms/pwsh"],
            isfile={"/opt/ms/pwsh"},
            versions={"/opt/ms/pwsh": "7.4.1"},
        )
        info = shell.resolve_pwsh()
        assert info is not None
        assert info.source == "known-path"
        assert info.path == "/opt/ms/pwsh"

    def test_explicit_pin_wins_over_path(self, monkeypatch: pytest.MonkeyPatch):
        pin = "/custom/pwsh"
        _setup(
            monkeypatch,
            which={"pwsh": "/fake/pwsh"},
            isfile={pin},
            versions={pin: "7.3.0", "/fake/pwsh": "7.4.1"},
        )
        info = shell.resolve_pwsh(types.SimpleNamespace(pwsh_path=pin))
        assert info is not None
        assert (info.source, info.path, info.version) == ("config", pin, "7.3.0")

    def test_sticky_pin_missing_never_falls_through(self, monkeypatch: pytest.MonkeyPatch):
        pin = "/missing/pwsh"
        _setup(monkeypatch, isfile=set(), versions={})

        def _which_must_not_run(name):  # pragma: no cover - asserts it is never called
            raise AssertionError("which must not be consulted when a pin is set")

        monkeypatch.setattr(shell.shutil, "which", _which_must_not_run)
        info = shell.resolve_pwsh(types.SimpleNamespace(pwsh_path=pin))
        assert info is not None
        assert info.source == "config-missing"
        assert info.path == pin
        assert info.version == "" and info.major == 0 and info.usable is False

    def test_pin_below_floor_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        pin = "/old/pwsh"
        _setup(monkeypatch, isfile={pin}, versions={pin: "5.1.0"})
        assert shell.resolve_pwsh(types.SimpleNamespace(pwsh_path=pin), min_major=7) is None

    def test_not_found(self, monkeypatch: pytest.MonkeyPatch):
        _setup(monkeypatch)
        assert shell.resolve_pwsh() is None

    def test_min_major_skips_old_candidate_and_continues(self, monkeypatch: pytest.MonkeyPatch):
        _setup(
            monkeypatch,
            which={"pwsh": "/fake/pwsh6"},
            known=["/opt/pwsh7"],
            isfile={"/opt/pwsh7"},
            versions={"/fake/pwsh6": "6.2.0", "/opt/pwsh7": "7.4.1"},
        )
        info = shell.resolve_pwsh(min_major=7)
        assert info is not None
        assert (info.source, info.path, info.major) == ("known-path", "/opt/pwsh7", 7)
        # No floor → the PATH pwsh (6.x), what a bare `pwsh` would run, wins.
        no_floor = shell.resolve_pwsh()
        assert no_floor is not None
        assert no_floor.source == "which" and no_floor.major == 6

    def test_min_major_one_skips_broken_keeps_usable(self, monkeypatch: pytest.MonkeyPatch):
        # Broken pwsh on PATH (probe failed) + a working 5.1 — underpins --allow-any.
        _setup(
            monkeypatch,
            which={"pwsh": "/broken/pwsh"},
            known=["/ok/ps"],
            isfile={"/ok/ps"},
            versions={"/broken/pwsh": "", "/ok/ps": "5.1.0"},
        )
        usable = shell.resolve_pwsh(min_major=1)
        assert usable is not None
        assert usable.path == "/ok/ps" and usable.major == 5
        # No floor surfaces the broken PATH pwsh first (for the `check` diagnostic).
        diag = shell.resolve_pwsh()
        assert diag is not None
        assert diag.path == "/broken/pwsh" and diag.usable is False

    def test_windows_powershell_only_on_windows(self, monkeypatch: pytest.MonkeyPatch):
        _setup(
            monkeypatch,
            which={"powershell": "/fake/powershell.exe"},
            versions={"/fake/powershell.exe": "5.1.19041.1"},
            os_name="nt",
        )
        info = shell.resolve_pwsh()
        assert info is not None
        assert info.source == "windows-powershell"
        assert info.major == 5 and info.is_v7 is False and info.usable is True

    def test_no_windows_powershell_on_posix(self, monkeypatch: pytest.MonkeyPatch):
        _setup(
            monkeypatch,
            which={"powershell": "/fake/powershell.exe"},
            versions={"/fake/powershell.exe": "5.1.19041.1"},
            os_name="posix",
        )
        assert shell.resolve_pwsh() is None

    def test_windows_powershell_systemroot_fallback(self, monkeypatch: pytest.MonkeyPatch):
        # `powershell` not on PATH → fall back to the System32 v1.0 path.
        _setup(monkeypatch, os_name="nt")  # which/known empty, _is_file False, no versions
        monkeypatch.setenv("SystemRoot", r"C:\Windows")
        # The constructed legacy path is the only file that "exists" and runs.
        monkeypatch.setattr(shell, "_is_file", lambda p: "powershell.exe" in p)
        monkeypatch.setattr(shell, "probe_pwsh_version", lambda p, **k: "5.1.0")
        info = shell.resolve_pwsh()
        assert info is not None
        assert info.source == "windows-powershell" and info.major == 5

    def test_config_none_is_safe(self, monkeypatch: pytest.MonkeyPatch):
        _setup(monkeypatch, which={"pwsh": "/fake/pwsh"}, versions={"/fake/pwsh": "7.4.1"})
        assert shell.resolve_pwsh(None) is not None  # getattr(None, "pwsh_path", "") → ""
