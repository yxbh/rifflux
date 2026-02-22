"""Tests for the FileWatcher integration with BackgroundIndexer.

Uses mocked ``watchfiles.watch`` for deterministic, fast tests that avoid
OS-level FS handle issues on Windows.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from rifflux.indexing.background import BackgroundIndexer, IndexRequest
from rifflux.indexing.watcher import FileWatcher
from rifflux.mcp.tools import (
    _get_file_watcher,
    _maybe_start_file_watcher,
    index_status,
    reindex,
    search_rifflux,
)
from rifflux.config import RiffluxConfig


# ---------------------------------------------------------------------------
# Helpers: mock watchfiles.watch to yield synthetic change batches
# ---------------------------------------------------------------------------


def _fake_watch_factory(
    changes_batches: list[set[tuple[int, str]]],
    *,
    delay_event: threading.Event | None = None,
):
    """Return a replacement for ``watchfiles.watch`` that yields *changes_batches*.

    If *delay_event* is given, waits for it to be set before yielding, so tests
    can control timing.
    """

    def _fake_watch(
        *paths: Any,
        debounce: int = 0,
        stop_event: threading.Event | None = None,
        recursive: bool = True,
        raise_interrupt: bool = True,
    ):
        for batch in changes_batches:
            if stop_event is not None and stop_event.is_set():
                return
            if delay_event is not None:
                delay_event.wait(timeout=5)
            yield batch

    return _fake_watch


# ---------------------------------------------------------------------------
# Unit: glob matching (no FS watcher needed)
# ---------------------------------------------------------------------------


def test_matches_globs_includes(tmp_path: Path) -> None:
    bg = BackgroundIndexer(run_reindex=lambda req: {})
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md", "*.txt"),
        exclude_globs=(".git/*",),
    )
    assert watcher._matches_globs(Path("README.md"))
    assert watcher._matches_globs(Path("notes.txt"))
    assert not watcher._matches_globs(Path("data.json"))


def test_matches_globs_excludes(tmp_path: Path) -> None:
    bg = BackgroundIndexer(run_reindex=lambda req: {})
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md",),
        exclude_globs=(".git/*",),
    )
    assert not watcher._matches_globs(Path(".git/config"))


def test_matches_globs_windows_separator_safe(tmp_path: Path) -> None:
    bg = BackgroundIndexer(run_reindex=lambda req: {})
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md",),
        exclude_globs=("**/node_modules/*",),
    )
    windows_style = Path("docs\\node_modules\\pkg\\README.md")
    assert not watcher._matches_globs(windows_style)


def test_matches_globs_excludes_absolute_under_watch_root(tmp_path: Path) -> None:
    bg = BackgroundIndexer(run_reindex=lambda req: {})
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md",),
        exclude_globs=(".venv/*",),
    )
    absolute = tmp_path / ".venv" / "pkg" / "README.md"
    assert not watcher._matches_globs(absolute)


# ---------------------------------------------------------------------------
# Unit: status() without starting the watcher
# ---------------------------------------------------------------------------


def test_watcher_status_reports_state(tmp_path: Path) -> None:
    bg = BackgroundIndexer(run_reindex=lambda req: {})
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md",),
        exclude_globs=(".git/*",),
        debounce_ms=200,
    )
    status = watcher.status()
    assert status["enabled"] is True
    assert status["running"] is False
    assert status["debounce_ms"] == 200
    assert status["events_received"] == 0
    assert status["jobs_submitted"] == 0


# ---------------------------------------------------------------------------
# Unit: start / stop lifecycle (mocked watch)
# ---------------------------------------------------------------------------


def test_watcher_starts_and_stops(tmp_path: Path) -> None:
    # watch() that blocks until stop_event is set, yielding nothing
    def _blocking_watch(*a: Any, stop_event: threading.Event | None = None, **kw: Any):
        if stop_event is not None:
            stop_event.wait()
        return
        yield  # make it a generator  # noqa: RET504

    bg = BackgroundIndexer(run_reindex=lambda req: {})
    watcher = FileWatcher(bg_indexer=bg, watch_paths=[tmp_path], debounce_ms=100)
    with patch("rifflux.indexing.watcher.watch", _blocking_watch):
        watcher.start()
        assert watcher.is_running
        watcher.stop(timeout=3)
        assert not watcher.is_running


# ---------------------------------------------------------------------------
# Unit: change detection via mocked FS events
# ---------------------------------------------------------------------------


def test_watcher_submits_job_on_matching_change(tmp_path: Path) -> None:
    results: list[dict] = []

    def fake_reindex(req: IndexRequest) -> dict:
        r = {"indexed_files": 1}
        results.append(r)
        return r

    fake_changes: list[set[tuple[int, str]]] = [
        {(1, str(tmp_path / "new.md"))},  # 1 = Change.added
    ]

    bg = BackgroundIndexer(run_reindex=fake_reindex)
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md",),
        debounce_ms=100,
    )
    with patch("rifflux.indexing.watcher.watch", _fake_watch_factory(fake_changes)):
        watcher.start()
        # The mocked watch yields one batch then exits, thread finishes quickly.
        watcher._thread.join(timeout=5)
        bg.drain(timeout=5)

    assert watcher._events_received >= 1
    assert watcher._jobs_submitted >= 1
    assert len(results) >= 1


def test_watcher_ignores_non_matching_change(tmp_path: Path) -> None:
    fake_changes: list[set[tuple[int, str]]] = [
        {(1, str(tmp_path / "data.json"))},
    ]

    bg = BackgroundIndexer(run_reindex=lambda req: {})
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md",),
        debounce_ms=100,
    )
    with patch("rifflux.indexing.watcher.watch", _fake_watch_factory(fake_changes)):
        watcher.start()
        watcher._thread.join(timeout=5)

    assert watcher._jobs_submitted == 0


def test_watcher_handles_modification_and_deletion(tmp_path: Path) -> None:
    """Both modified and deleted .md files should trigger a job."""
    submitted: list[dict] = []

    def fake_reindex(req: IndexRequest) -> dict:
        r = {"indexed_files": 1}
        submitted.append(r)
        return r

    fake_changes: list[set[tuple[int, str]]] = [
        {(2, str(tmp_path / "updated.md"))},   # 2 = Change.modified
        {(3, str(tmp_path / "deleted.md"))},    # 3 = Change.deleted
    ]

    bg = BackgroundIndexer(run_reindex=fake_reindex)
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md",),
        debounce_ms=100,
    )
    with patch("rifflux.indexing.watcher.watch", _fake_watch_factory(fake_changes)):
        watcher.start()
        watcher._thread.join(timeout=5)
        bg.drain(timeout=5)

    assert watcher._events_received == 2
    assert watcher._jobs_submitted == 2


def test_watcher_coalesces_burst_batches(tmp_path: Path) -> None:
    """Burst batches should not enqueue redundant full-reindex jobs."""
    gate = threading.Event()

    def slow_reindex(req: IndexRequest) -> dict:
        gate.wait(timeout=5)
        return {"indexed_files": 1}

    fake_changes: list[set[tuple[int, str]]] = [
        {(1, str(tmp_path / "a.md"))},
        {(1, str(tmp_path / "b.md"))},
        {(1, str(tmp_path / "c.md"))},
    ]

    bg = BackgroundIndexer(run_reindex=slow_reindex)
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md",),
        debounce_ms=100,
    )
    with patch("rifflux.indexing.watcher.watch", _fake_watch_factory(fake_changes)):
        watcher.start()
        watcher._thread.join(timeout=5)

    queued_or_running = [
        j for j in bg.get_all_jobs() if j.status in {"queued", "running"}
    ]
    assert len(queued_or_running) <= 1
    gate.set()
    bg.drain(timeout=5)


# ---------------------------------------------------------------------------
# Integration: watcher via tools layer (mocked watcher start)
# ---------------------------------------------------------------------------


def test_maybe_start_file_watcher_creates_watcher(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """_maybe_start_file_watcher creates and starts a FileWatcher when configured."""
    import rifflux.mcp.tools as tools_mod

    started: list[bool] = []
    original_start = FileWatcher.start

    def tracking_start(self: FileWatcher) -> None:
        started.append(True)
        # Don't actually start the watch thread to avoid FS handles.

    monkeypatch.setattr(FileWatcher, "start", tracking_start)

    config = RiffluxConfig(
        file_watcher_enabled=True,
        file_watcher_paths=(str(tmp_path),),
        file_watcher_debounce_ms=100,
    )
    _maybe_start_file_watcher(db_path=None, config=config)

    watcher = _get_file_watcher()
    assert watcher is not None
    assert len(started) == 1


def test_maybe_start_file_watcher_skips_when_disabled(
    tmp_path: Path,
) -> None:
    config = RiffluxConfig(file_watcher_enabled=False)
    _maybe_start_file_watcher(db_path=None, config=config)
    assert _get_file_watcher() is None


def test_maybe_start_file_watcher_recreates_for_new_db(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(FileWatcher, "start", lambda self: None)

    config = RiffluxConfig(
        file_watcher_enabled=True,
        file_watcher_paths=(str(tmp_path),),
        file_watcher_debounce_ms=100,
    )

    db1 = tmp_path / "a.db"
    db2 = tmp_path / "b.db"
    _maybe_start_file_watcher(db_path=db1, config=config)
    first = _get_file_watcher()
    assert first is not None

    # Simulate running watcher so code path that would normally early-return is hit.
    monkeypatch.setattr(FileWatcher, "is_running", property(lambda self: True))
    _maybe_start_file_watcher(db_path=db2, config=config)
    second = _get_file_watcher()
    assert second is not None
    assert second is not first


def test_index_status_includes_watcher_info(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFLUX_EMBEDDING_BACKEND", "hash")
    # Patch FileWatcher.start to avoid real FS watching.
    monkeypatch.setattr(FileWatcher, "start", lambda self: None)
    monkeypatch.setenv("RIFLUX_FILE_WATCHER", "1")
    monkeypatch.setenv("RIFLUX_FILE_WATCHER_PATHS", str(tmp_path))

    source = tmp_path / "docs"
    source.mkdir()
    (source / "note.md").write_text("# Note\n\ncache ttl", encoding="utf-8")

    db_path = make_db_path("watcher-status.db")
    reindex(db_path=db_path, source_path=source, force=True)

    # Trigger watcher creation (start is mocked).
    search_rifflux(db_path=db_path, query="cache", top_k=1, mode="hybrid")

    status = index_status(db_path=db_path)
    assert "file_watcher" in status
    assert status["file_watcher"]["enabled"] is True


def test_index_status_shows_disabled_when_no_watcher(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFLUX_EMBEDDING_BACKEND", "hash")
    # File watcher not enabled.

    source = tmp_path / "docs"
    source.mkdir()
    (source / "note.md").write_text("# Note\n\ncache ttl", encoding="utf-8")

    db_path = make_db_path("no-watcher.db")
    reindex(db_path=db_path, source_path=source, force=True)

    status = index_status(db_path=db_path)
    assert status["file_watcher"]["enabled"] is False
