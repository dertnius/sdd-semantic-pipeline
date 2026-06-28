"""Tests for sdd_pipeline.download — manifest, auth strategies, and transfer.

No network and no `requests`: a fake session stands in for ``requests.Session`` so the
auth logic and atomic file-write are fully unit-tested. Secrets must never appear in error
messages — only the env-var name.
"""

from __future__ import annotations

import json

import pytest

from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.download import (
    DownloadEntry,
    DownloadError,
    apply_auth,
    download_entry,
    load_manifest,
    run_download,
)

# ── fakes ──────────────────────────────────────────────────────────────────────


class _FakeCookies(dict):
    def set(self, name, value, **kw):
        self[name] = value


class _FakeResponse:
    def __init__(self, content=b"data", ok=True):
        self._content = content
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("HTTP 500")

    def iter_content(self, chunk_size=1):
        yield self._content


class _FakeSession:
    def __init__(self, *, login_sets_cookie=True, get_content=b"hello", get_ok=True):
        self.cookies = _FakeCookies()
        self.headers: dict = {}
        self.verify = True
        self.posts: list = []
        self.gets: list = []
        self._login_sets_cookie = login_sets_cookie
        self._get_content = get_content
        self._get_ok = get_ok

    def post(self, url, data=None, timeout=None, allow_redirects=True):
        self.posts.append((url, data))
        if self._login_sets_cookie:
            self.cookies.set("SMSESSION", "session-token")
        return _FakeResponse()

    def get(self, url, stream=False, timeout=None):
        self.gets.append(url)
        return _FakeResponse(self._get_content, self._get_ok)


# ── manifest ───────────────────────────────────────────────────────────────────


def _write(p, text):
    p.write_text(text, encoding="utf-8")
    return p


class TestManifest:
    def test_parses_yaml_entries(self, tmp_path):
        m = _write(
            tmp_path / "m.yaml",
            "entries:\n"
            "  - url: https://cf/export?pageId=1\n"
            "    dest: confluence/p1.html\n"
            "  - url: https://sp/spec.docx\n"
            "    dest: sharepoint/spec.docx\n"
            "    space: PLATFORM\n",
        )
        entries = load_manifest(m)
        assert [e.dest for e in entries] == ["confluence/p1.html", "sharepoint/spec.docx"]
        assert entries[1].space == "PLATFORM"

    def test_parses_json(self, tmp_path):
        m = _write(
            tmp_path / "m.json",
            json.dumps({"entries": [{"url": "https://x/a", "dest": "a.html"}]}),
        )
        assert load_manifest(m)[0].url == "https://x/a"

    def test_missing_file(self, tmp_path):
        with pytest.raises(DownloadError, match="not found"):
            load_manifest(tmp_path / "nope.yaml")

    def test_no_entries(self, tmp_path):
        m = _write(tmp_path / "m.yaml", "entries: []\n")
        with pytest.raises(DownloadError, match="no 'entries'"):
            load_manifest(m)

    def test_entry_requires_url_and_dest(self, tmp_path):
        m = _write(tmp_path / "m.yaml", "entries:\n  - url: https://x/a\n")
        with pytest.raises(DownloadError, match="needs both 'url' and 'dest'"):
            load_manifest(m)


# ── auth strategies ─────────────────────────────────────────────────────────────


class TestApplyAuth:
    def test_cookie_sets_session_cookie(self):
        cfg = PipelineConfig(download_auth="cookie", download_cookie="SECRET-SMSESSION")
        sess = _FakeSession()
        apply_auth(sess, cfg)
        assert sess.cookies["SMSESSION"] == "SECRET-SMSESSION"

    def test_bearer_sets_header(self):
        cfg = PipelineConfig(download_auth="bearer", download_bearer="tok123")
        sess = _FakeSession()
        apply_auth(sess, cfg)
        assert sess.headers["Authorization"] == "Bearer tok123"

    def test_none_is_noop(self):
        sess = _FakeSession()
        apply_auth(sess, PipelineConfig(download_auth="none"))
        assert sess.cookies == {} and sess.headers == {}

    def test_form_login_posts_and_captures_cookie(self):
        cfg = PipelineConfig(
            download_auth="form",
            download_login_url="https://sso/login",
            download_username="svc",
            download_password="pw",
            download_user_field="USER",
            download_pass_field="PASSWORD",
        )
        sess = _FakeSession(login_sets_cookie=True)
        apply_auth(sess, cfg)
        assert sess.posts == [("https://sso/login", {"USER": "svc", "PASSWORD": "pw"})]
        assert "SMSESSION" in sess.cookies

    def test_form_login_without_cookie_fails(self):
        cfg = PipelineConfig(
            download_auth="form",
            download_login_url="https://sso/login",
            download_username="svc",
            download_password="pw",
        )
        sess = _FakeSession(login_sets_cookie=False)
        with pytest.raises(DownloadError, match="did not yield"):
            apply_auth(sess, cfg)

    def test_unknown_strategy(self):
        with pytest.raises(DownloadError, match="unknown download_auth"):
            apply_auth(_FakeSession(), PipelineConfig(download_auth="kerberos"))

    @pytest.mark.parametrize(
        "cfg_kwargs, env_name",
        [
            ({"download_auth": "cookie"}, "PIPELINE_DOWNLOAD_COOKIE"),
            ({"download_auth": "bearer"}, "PIPELINE_DOWNLOAD_BEARER"),
            (
                {
                    "download_auth": "form",
                    "download_login_url": "https://sso",
                    "download_username": "u",
                },
                "PIPELINE_DOWNLOAD_PASSWORD",
            ),
        ],
    )
    def test_missing_secret_names_env_var(self, cfg_kwargs, env_name):
        # The error tells the operator which env var to set (it never has a value to echo).
        with pytest.raises(DownloadError) as exc:
            apply_auth(_FakeSession(), PipelineConfig(**cfg_kwargs))
        assert env_name in str(exc.value)

    def test_set_secret_value_is_never_echoed(self):
        # A bearer token set, but form login required and its password missing → the error
        # must not leak the unrelated secret that *was* provided.
        cfg = PipelineConfig(
            download_auth="form",
            download_login_url="https://sso",
            download_username="u",
            download_bearer="SUPER-SECRET-TOKEN",
        )
        with pytest.raises(DownloadError) as exc:
            apply_auth(_FakeSession(), cfg)
        assert "SUPER-SECRET-TOKEN" not in str(exc.value)


# ── transfer ────────────────────────────────────────────────────────────────────


class TestDownloadEntry:
    def test_writes_file_into_inbox(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        sess = _FakeSession(get_content=b"<html>page</html>")
        result = download_entry(
            sess,
            DownloadEntry(url="https://x/a", dest="confluence/a.html"),
            inbox_dir=str(inbox),
            enforce=True,
            timeout=10,
        )
        assert result.status == "ok"
        assert (inbox / "confluence" / "a.html").read_bytes() == b"<html>page</html>"
        assert not list(inbox.rglob("*.part")), "temp file must be renamed away"

    def test_http_error_is_captured_not_raised(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        sess = _FakeSession(get_ok=False)
        result = download_entry(
            sess,
            DownloadEntry(url="https://x/a", dest="a.html"),
            inbox_dir=str(inbox),
            enforce=True,
            timeout=10,
        )
        assert result.status == "error"
        assert "500" in result.error

    def test_dest_escaping_inbox_is_rejected(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        sess = _FakeSession()
        result = download_entry(
            sess,
            DownloadEntry(url="https://x/a", dest="../escape.html"),
            inbox_dir=str(inbox),
            enforce=True,
            timeout=10,
        )
        assert result.status == "error"
        assert "outside the inbox" in result.error
        assert not (tmp_path / "escape.html").exists()


def test_run_download_with_injected_session(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    manifest = _write(
        tmp_path / "m.yaml",
        "entries:\n"
        "  - url: https://x/a\n    dest: a.html\n"
        "  - url: https://x/b\n    dest: sub/b.html\n",
    )
    cfg = PipelineConfig(inbox_dir=str(inbox), enforce_workspace=True, download_auth="none")
    results = run_download(cfg, manifest, session=_FakeSession(get_content=b"ok"))
    assert [r.status for r in results] == ["ok", "ok"]
    assert (inbox / "a.html").exists() and (inbox / "sub" / "b.html").exists()
