"""
Optional ingestion: download manifest-listed files into the inbox.

This module is **fully optional** and isolated — it is imported only by the
``sdd-pipeline download`` CLI command. The deterministic core never imports it, and
nothing here runs unless the user invokes the command. ``requests`` is an optional
``[download]`` extra; only :func:`new_session` and the command touch it, so the auth
logic and file-writing below are unit-testable with a fake session and no network.

Auth model (one SiteMinder session fronts both Confluence and SharePoint):
    cookie   — pre-issued SMSESSION cookie supplied as a secret (PRIMARY; MFA-proof).
    form     — headless username/password login that yields an SMSESSION cookie.
    bearer   — Authorization: Bearer <token>.
    none     — plain GET (un-gated URLs / curl-style).

Credentials come from env/secret only (``PIPELINE_DOWNLOAD_*``), never CLI args. Errors
name the missing env var but never echo a secret's value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import PipelineConfig
from .workspace import resolve_input

_CHUNK = 1 << 16  # 64 KiB streaming reads


class DownloadError(RuntimeError):
    """A download failed: bad manifest, auth misconfiguration, or a transfer error."""


@dataclass
class DownloadEntry:
    """One file to fetch. ``dest`` is a path **relative to the inbox root**."""

    url: str
    dest: str
    labels: list[str] = field(default_factory=list)
    space: str = ""
    source_url: str = ""


@dataclass
class DownloadResult:
    url: str
    dest: str
    status: str  # "ok" | "error"
    bytes: int = 0
    error: str = ""


# ── Manifest ───────────────────────────────────────────────────────────────────


def load_manifest(path: str | os.PathLike[str]) -> list[DownloadEntry]:
    """Parse a YAML/JSON manifest into :class:`DownloadEntry` objects.

    Shape::

        entries:
          - url: https://confluence/.../export?pageId=123
            dest: confluence/page-123.html
          - url: https://sharepoint/.../spec.docx
            dest: sharepoint/spec.docx
    """
    p = Path(path)
    if not p.exists():
        raise DownloadError(f"manifest not found: {p}")
    try:
        data: Any = yaml.safe_load(p.read_text(encoding="utf-8"))  # YAML is a superset of JSON
    except yaml.YAMLError as exc:
        raise DownloadError(f"could not parse manifest {p}: {exc}") from exc

    raw_entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(raw_entries, list) or not raw_entries:
        raise DownloadError(f"manifest {p} has no 'entries' list")

    entries: list[DownloadEntry] = []
    for i, item in enumerate(raw_entries):
        if not isinstance(item, dict) or not item.get("url") or not item.get("dest"):
            raise DownloadError(f"manifest entry {i} needs both 'url' and 'dest'")
        entries.append(
            DownloadEntry(
                url=str(item["url"]),
                dest=str(item["dest"]),
                labels=list(item.get("labels", []) or []),
                space=str(item.get("space", "")),
                source_url=str(item.get("source_url", "")),
            )
        )
    return entries


# ── Auth ─────────────────────────────────────────────────────────────────────


def _require_secret(value: str, env_name: str, strategy: str) -> str:
    """Return *value* or raise naming the env var (never echoing the secret)."""
    if not value:
        raise DownloadError(
            f"download_auth={strategy!r} requires {env_name} to be set (env/secret only)."
        )
    return value


def apply_auth(session: Any, config: PipelineConfig) -> None:
    """Apply the configured SiteMinder auth strategy to *session* in place.

    Operates on any ``requests.Session``-like object (``cookies``, ``headers``, ``post``),
    so it is testable with a fake session. ``form`` performs the login round-trip.
    """
    strategy = (config.download_auth or "cookie").lower()
    if strategy == "none":
        return
    if strategy == "cookie":
        cookie = _require_secret(config.download_cookie, "PIPELINE_DOWNLOAD_COOKIE", "cookie")
        session.cookies.set(config.download_cookie_name, cookie)
    elif strategy == "bearer":
        token = _require_secret(config.download_bearer, "PIPELINE_DOWNLOAD_BEARER", "bearer")
        session.headers["Authorization"] = f"Bearer {token}"
    elif strategy == "form":
        _form_login(session, config)
    else:
        raise DownloadError(
            f"unknown download_auth {config.download_auth!r} (cookie|form|bearer|none)"
        )


def _form_login(session: Any, config: PipelineConfig) -> None:
    """Headless SiteMinder form login → captures the SMSESSION cookie in the jar."""
    if not config.download_login_url:
        raise DownloadError("download_auth='form' requires PIPELINE_DOWNLOAD_LOGIN_URL")
    user = _require_secret(config.download_username, "PIPELINE_DOWNLOAD_USERNAME", "form")
    password = _require_secret(config.download_password, "PIPELINE_DOWNLOAD_PASSWORD", "form")
    payload = {config.download_user_field: user, config.download_pass_field: password}
    resp = session.post(
        config.download_login_url,
        data=payload,
        timeout=config.download_timeout,
        allow_redirects=True,
    )
    resp.raise_for_status()
    if config.download_cookie_name not in session.cookies:
        raise DownloadError(
            f"form login did not yield a {config.download_cookie_name!r} cookie "
            "(check the login URL, field names, or MFA — MFA needs download_auth='cookie')."
        )


def new_session(config: PipelineConfig) -> Any:
    """Build a real ``requests.Session`` with auth applied (imports the optional extra)."""
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise DownloadError(
            'requests is not installed. Install the download extra: pip install ".[download]"'
        ) from exc
    session = requests.Session()
    session.verify = config.download_verify_tls
    apply_auth(session, config)
    return session


# ── Transfer ─────────────────────────────────────────────────────────────────


def download_entry(
    session: Any,
    entry: DownloadEntry,
    *,
    inbox_dir: str,
    enforce: bool,
    timeout: int,
) -> DownloadResult:
    """Fetch one entry into the inbox (atomic tmp+rename); never raises — returns a result."""
    try:
        # dest is relative to the inbox root; resolve_input enforces containment so a
        # crafted "../" dest cannot escape the inbox (exit-2-equivalent guard).
        target = resolve_input(Path(inbox_dir) / entry.dest, inbox_dir=inbox_dir, enforce=enforce)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")

        resp = session.get(entry.url, stream=True, timeout=timeout)
        resp.raise_for_status()
        written = 0
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=_CHUNK):
                if chunk:
                    fh.write(chunk)
                    written += len(chunk)
        tmp.replace(target)  # atomic within the same directory
        return DownloadResult(url=entry.url, dest=entry.dest, status="ok", bytes=written)
    except Exception as exc:  # network/auth/HTTP/IO — collected, not fatal to the batch
        return DownloadResult(url=entry.url, dest=entry.dest, status="error", error=str(exc))


def run_download(
    config: PipelineConfig,
    manifest_path: str | os.PathLike[str],
    *,
    session: Any | None = None,
) -> list[DownloadResult]:
    """Load *manifest_path*, build a session (unless injected), fetch every entry.

    Returns one :class:`DownloadResult` per entry. A bad manifest or an auth setup error
    raises :class:`DownloadError` before any transfer; per-file transfer failures are
    captured in the results so one bad URL does not abort the batch.
    """
    entries = load_manifest(manifest_path)
    sess = session if session is not None else new_session(config)
    return [
        download_entry(
            sess,
            entry,
            inbox_dir=config.inbox_dir,
            enforce=config.enforce_workspace,
            timeout=config.download_timeout,
        )
        for entry in entries
    ]
