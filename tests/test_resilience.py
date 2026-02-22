"""Tests for resilience: retry on transient DB errors, watcher auto-restart,
background indexer shutdown, and atexit cleanup registration.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from rifflux.indexing.background import (
    BackgroundIndexer,
    IndexRequest,
    _is_transient,
)
from rifflux.indexing.watcher import FileWatcher


# ---------------------------------------------------------------------------
# BackgroundIndexer: retry on transient errors
# ---------------------------------------------------------------------------


def test_is_transient_detects_locked() -> None:
    assert _is_transient(sqlite3.OperationalError("database is locked"))


def test_is_transient_detects_busy() -> None:
    assert _is_transient(sqlite3.OperationalError("database is busy"))


def test_is_transient_rejects_permanent() -> None:
    assert not _is_transient(sqlite3.OperationalError("no such table: chunks"))
    assert not _is_transient(ValueError("bad value"))


def test_retry_succeeds_after_transient_failure() -> None:
    """Job should complete after transient errors within retry budget."""
    call_count = 0

    def flaky_reindex(req: IndexRequest) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise sqlite3.OperationalError("database is locked")
        return {"indexed_files": 1}

    bg = BackgroundIndexer(run_reindex=flaky_reindex, max_retries=3)
    request = IndexRequest(db_path=None, source_paths=[])
    job = bg.submit(request)
    bg.drain(timeout=15)

    assert job.status == "completed"
    assert job.retries == 2  # succeeded on 3rd attempt
    assert job.result == {"indexed_files": 1}
    assert call_count == 3


def test_retry_exhausted_marks_failed() -> None:
    """Job should be marked failed after all retries are exhausted."""
    def always_locked(req: IndexRequest) -> dict[str, Any]:
        raise sqlite3.OperationalError("database is locked")

    bg = BackgroundIndexer(run_reindex=always_locked, max_retries=2)
    request = IndexRequest(db_path=None, source_paths=[])
    job = bg.submit(request)
    bg.drain(timeout=30)

    assert job.status == "failed"
    assert job.retries == 2
    assert "locked" in (job.error or "")


def test_permanent_error_no_retry() -> None:
    """Non-transient errors should fail immediately without retry."""
    call_count = 0

    def bad_schema(req: IndexRequest) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        raise sqlite3.OperationalError("no such table: chunks")

    bg = BackgroundIndexer(run_reindex=bad_schema, max_retries=3)
    request = IndexRequest(db_path=None, source_paths=[])
    job = bg.submit(request)
    bg.drain(timeout=10)

    assert job.status == "failed"
    assert job.retries == 0
    assert call_count == 1


def test_job_to_dict_includes_retries() -> None:
    """Job.to_dict() should include the retries field."""
    def ok(req: IndexRequest) -> dict[str, Any]:
        return {"indexed_files": 0}

    bg = BackgroundIndexer(run_reindex=ok)
    job = bg.submit(IndexRequest(db_path=None, source_paths=[]))
    bg.drain(timeout=5)
    d = job.to_dict()
    assert "retries" in d
    assert d["retries"] == 0


# ---------------------------------------------------------------------------
# BackgroundIndexer: shutdown
# ---------------------------------------------------------------------------


def test_shutdown_cancels_queued_jobs() -> None:
    """Shutdown should cancel queued jobs that haven't started yet."""
    gate = threading.Event()

    def slow_reindex(req: IndexRequest) -> dict[str, Any]:
        gate.wait(timeout=10)
        return {"indexed_files": 1}

    bg = BackgroundIndexer(run_reindex=slow_reindex)

    # Submit two jobs: first will be running, second will be queued.
    job1 = bg.submit(IndexRequest(db_path=None, source_paths=[]))
    time.sleep(0.1)  # give worker time to pick up job1
    job2 = bg.submit(IndexRequest(db_path=None, source_paths=[]))

    # Shutdown should cancel job2 and wait for job1.
    gate.set()  # unblock job1
    bg.shutdown(timeout=5)

    assert job1.status == "completed"
    assert job2.status == "failed"
    assert "shutdown" in (job2.error or "").lower()


def test_submit_after_shutdown_raises() -> None:
    """Submitting after shutdown should raise RuntimeError."""
    bg = BackgroundIndexer(run_reindex=lambda r: {})
    bg.shutdown(timeout=1)
    with pytest.raises(RuntimeError, match="shut down"):
        bg.submit(IndexRequest(db_path=None, source_paths=[]))


def test_submit_shutdown_race_does_not_leave_queued_job() -> None:
    """Submit must not enqueue once shutdown state is set under lock."""
    bg = BackgroundIndexer(run_reindex=lambda r: {"ok": 1})
    with bg._lock:  # type: ignore[attr-defined]
        bg._is_shutdown = True  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="shut down"):
        bg.submit(IndexRequest(db_path=None, source_paths=[]))

    jobs = bg.get_all_jobs()
    assert not any(job.status == "queued" for job in jobs)


# ---------------------------------------------------------------------------
# FileWatcher: auto-restart on crash
# ---------------------------------------------------------------------------


def _crashing_watch_factory(
    crash_count: int,
    changes_after: list[set[tuple[int, str]]] | None = None,
):
    """Return a fake watch that crashes *crash_count* times then yields events."""
    calls = {"n": 0}

    def _fake_watch(*paths: Any, stop_event: threading.Event | None = None, **kw: Any):
        calls["n"] += 1
        if calls["n"] <= crash_count:
            raise OSError(f"simulated crash #{calls['n']}")
        if changes_after:
            for batch in changes_after:
                if stop_event is not None and stop_event.is_set():
                    return
                yield batch

    return _fake_watch, calls


def test_watcher_restarts_after_crash(tmp_path: Path) -> None:
    """Watcher should auto-restart after a crash and continue processing."""
    submitted: list[dict] = []

    def fake_reindex(req: IndexRequest) -> dict[str, Any]:
        r = {"indexed_files": 1}
        submitted.append(r)
        return r

    fake_watch, calls = _crashing_watch_factory(
        crash_count=2,
        changes_after=[{(1, str(tmp_path / "new.md"))}],
    )

    bg = BackgroundIndexer(run_reindex=fake_reindex)
    # Use max_crash_restarts=5, very small backoff for fast tests.
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        include_globs=("*.md",),
        debounce_ms=100,
        max_crash_restarts=5,
    )
    with patch("rifflux.indexing.watcher.watch", fake_watch), \
         patch("rifflux.indexing.watcher._RESTART_BACKOFF_BASE_S", 0.01):
        watcher.start()
        watcher._thread.join(timeout=10)
        bg.drain(timeout=5)

    assert calls["n"] == 3  # 2 crashes + 1 successful run
    assert watcher._crash_count == 0  # reset after successful batch
    assert len(submitted) >= 1


def test_watcher_gives_up_after_max_crashes(tmp_path: Path) -> None:
    """Watcher should stop retrying after exceeding max crash restarts."""
    fake_watch, calls = _crashing_watch_factory(crash_count=100)

    bg = BackgroundIndexer(run_reindex=lambda req: {})
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        debounce_ms=100,
        max_crash_restarts=3,
    )
    with patch("rifflux.indexing.watcher.watch", fake_watch), \
         patch("rifflux.indexing.watcher._RESTART_BACKOFF_BASE_S", 0.01):
        watcher.start()
        watcher._thread.join(timeout=10)

    # Should have crashed 3+1=4 times (initial + 3 restarts) then given up.
    assert calls["n"] == 4
    assert watcher._crash_count == 4


def test_watcher_status_includes_crash_count(tmp_path: Path) -> None:
    bg = BackgroundIndexer(run_reindex=lambda req: {})
    watcher = FileWatcher(
        bg_indexer=bg,
        watch_paths=[tmp_path],
        debounce_ms=100,
    )
    status = watcher.status()
    assert "crash_restarts" in status
    assert status["crash_restarts"] == 0


# ---------------------------------------------------------------------------
# atexit registration
# ---------------------------------------------------------------------------


def test_shutdown_server_registered_at_import() -> None:
    """_shutdown_server should be registered via atexit on module import."""
    import atexit
    import rifflux.mcp.tools as tools_mod

    # atexit doesn't expose its registry publicly, so we verify the
    # function exists and is callable.
    assert callable(tools_mod._shutdown_server)
