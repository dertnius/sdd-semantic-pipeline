"""Tests for the inbox/outbox workspace contract (``sdd_pipeline.workspace``).

These exercise the path resolvers directly with explicit ``enforce`` flags, so
they are independent of the autouse env fixture in conftest.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sdd_pipeline.workspace import (
    OUTBOX_CHUNKS,
    OUTBOX_INDEX,
    WorkspaceError,
    ensure_inbox_exists,
    resolve_index_path,
    resolve_input,
    resolve_output_dir,
    resolve_output_file,
)


class TestResolveInput:
    def test_default_is_inbox_root(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        assert resolve_input(None, inbox_dir=inbox, enforce=True) == inbox

    def test_default_subpath(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        got = resolve_input(None, inbox_dir=inbox, enforce=True, default_subpath="sample")
        assert got == inbox / "sample"

    def test_inbox_root_itself_allowed(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        assert resolve_input(inbox, inbox_dir=inbox, enforce=True) == inbox

    def test_subfolder_under_inbox_allowed(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        sub = inbox / "sample" / "deep"
        assert resolve_input(sub, inbox_dir=inbox, enforce=True) == sub

    def test_outside_inbox_rejected(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        with pytest.raises(WorkspaceError, match="inbox"):
            resolve_input(tmp_path / "elsewhere", inbox_dir=inbox, enforce=True)

    def test_dotdot_traversal_rejected(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        with pytest.raises(WorkspaceError):
            resolve_input(inbox / ".." / "elsewhere", inbox_dir=inbox, enforce=True)

    def test_enforce_false_allows_outside(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        outside = tmp_path / "elsewhere"
        assert resolve_input(outside, inbox_dir=inbox, enforce=False) == outside


class TestResolveOutput:
    def test_default_subpath_dir_is_created(self, tmp_path: Path):
        outbox = tmp_path / "outbox"
        got = resolve_output_dir(
            None, outbox_dir=outbox, enforce=True, default_subpath=OUTBOX_CHUNKS
        )
        assert got == outbox / OUTBOX_CHUNKS
        assert got.is_dir()

    def test_dir_outside_outbox_rejected_before_create(self, tmp_path: Path):
        outbox = tmp_path / "outbox"
        outside = tmp_path / "elsewhere" / "chunks"
        with pytest.raises(WorkspaceError, match="outbox"):
            resolve_output_dir(outside, outbox_dir=outbox, enforce=True, default_subpath="x")
        assert not outside.exists()  # rejected before mkdir

    def test_output_file_creates_parent(self, tmp_path: Path):
        outbox = tmp_path / "outbox"
        got = resolve_output_file(
            None, outbox_dir=outbox, enforce=True, default_subpath="reports/r.json"
        )
        assert got == outbox / "reports" / "r.json"
        assert got.parent.is_dir()
        assert not got.exists()  # only the parent is created

    def test_file_outside_outbox_rejected(self, tmp_path: Path):
        outbox = tmp_path / "outbox"
        with pytest.raises(WorkspaceError):
            resolve_output_file(
                tmp_path / "x.json", outbox_dir=outbox, enforce=True, default_subpath="r.json"
            )

    def test_enforce_false_allows_outside(self, tmp_path: Path):
        outbox = tmp_path / "outbox"
        target = tmp_path / "elsewhere"
        assert (
            resolve_output_dir(target, outbox_dir=outbox, enforce=False, default_subpath="x")
            == target
        )


class TestIndexPath:
    def test_default_is_outbox_index(self, tmp_path: Path):
        outbox = tmp_path / "outbox"
        assert resolve_index_path(None, outbox_dir=outbox, enforce=True) == outbox / OUTBOX_INDEX

    def test_does_not_create_dir(self, tmp_path: Path):
        outbox = tmp_path / "outbox"
        got = resolve_index_path(None, outbox_dir=outbox, enforce=True)
        assert not got.exists()  # search just reads it

    def test_outside_outbox_rejected(self, tmp_path: Path):
        outbox = tmp_path / "outbox"
        with pytest.raises(WorkspaceError):
            resolve_index_path(tmp_path / "elsewhere", outbox_dir=outbox, enforce=True)


class TestEnsureInbox:
    def test_missing_inbox_raises_when_enforced(self, tmp_path: Path):
        with pytest.raises(WorkspaceError, match="does not exist"):
            ensure_inbox_exists(tmp_path / "nope", enforce=True)

    def test_missing_inbox_ok_when_not_enforced(self, tmp_path: Path):
        ensure_inbox_exists(tmp_path / "nope", enforce=False)  # no raise

    def test_existing_inbox_ok(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        ensure_inbox_exists(inbox, enforce=True)  # no raise


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
class TestSymlink:
    def test_symlink_escaping_inbox_rejected(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outside = tmp_path / "secret"
        outside.mkdir()
        link = inbox / "link"
        link.symlink_to(outside, target_is_directory=True)
        # The link lives under the inbox but resolves outside it → rejected.
        with pytest.raises(WorkspaceError):
            resolve_input(link, inbox_dir=inbox, enforce=True)
