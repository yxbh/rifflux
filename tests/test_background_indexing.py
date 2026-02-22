"""Tests for the BackgroundIndexer job manager and background reindex via tools."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from rifflux.indexing.background import BackgroundIndexer, IndexRequest
from rifflux.mcp.tools import (
    index_status,
    reindex,
    reindex_many,
    search_rifflux,
    _get_bg_indexer,
)


# ---------------------------------------------------------------------------
# Unit tests for BackgroundIndexer
# ---------------------------------------------------------------------------


def test_submit_returns_queued_job() -> None:
    results: list[dict] = []

    def fake_reindex(req: IndexRequest) -> dict:
        return {"indexed_files": 1}

    bg = BackgroundIndexer(run_reindex=fake_reindex)
    job = bg.submit(IndexRequest(db_path=None, source_paths=[]))
    assert job.status == "queued"
    assert job.job_id
    bg.drain(timeout=5)

    final = bg.get_job(job.job_id)
    assert final is not None
    assert final.status == "completed"
    assert final.result == {"indexed_files": 1}


def test_jobs_run_sequentially() -> None:
    order: list[str] = []

    def slow_reindex(req: IndexRequest) -> dict:
        tag = str(req.source_paths[0]) if req.source_paths else "?"
        time.sleep(0.05)
        order.append(tag)
        return {"tag": tag}

    bg = BackgroundIndexer(run_reindex=slow_reindex)
    bg.submit(IndexRequest(db_path=None, source_paths=[Path("a")]))
    bg.submit(IndexRequest(db_path=None, source_paths=[Path("b")]))
    bg.submit(IndexRequest(db_path=None, source_paths=[Path("c")]))
    bg.drain(timeout=10)

    assert order == ["a", "b", "c"]


def test_failed_job_captures_error() -> None:
    def failing_reindex(req: IndexRequest) -> dict:
        raise RuntimeError("disk full")

    bg = BackgroundIndexer(run_reindex=failing_reindex)
    job = bg.submit(IndexRequest(db_path=None, source_paths=[]))
    bg.drain(timeout=5)

    final = bg.get_job(job.job_id)
    assert final is not None
    assert final.status == "failed"
    assert "disk full" in (final.error or "")


def test_get_all_jobs_returns_session_history() -> None:
    counter = 0

    def counting_reindex(req: IndexRequest) -> dict:
        nonlocal counter
        counter += 1
        return {"n": counter}

    bg = BackgroundIndexer(run_reindex=counting_reindex)
    bg.submit(IndexRequest(db_path=None, source_paths=[]))
    bg.submit(IndexRequest(db_path=None, source_paths=[]))
    bg.drain(timeout=5)

    jobs = bg.get_all_jobs()
    assert len(jobs) == 2
    assert all(j.status == "completed" for j in jobs)


def test_to_dict_has_expected_fields() -> None:
    def noop(req: IndexRequest) -> dict:
        return {}

    bg = BackgroundIndexer(run_reindex=noop)
    job = bg.submit(IndexRequest(db_path=None, source_paths=[]))
    bg.drain(timeout=5)

    d = bg.get_job(job.job_id).to_dict()
    assert set(d.keys()) == {"job_id", "status", "elapsed_seconds", "result", "error", "retries"}
    assert d["status"] == "completed"
    assert d["elapsed_seconds"] is not None


# ---------------------------------------------------------------------------
# Integration tests via tools layer
# ---------------------------------------------------------------------------


def test_reindex_background_returns_job_immediately(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    source = tmp_path / "src"
    source.mkdir()
    (source / "a.md").write_text("# A\n\ncache ttl policy", encoding="utf-8")

    db_path = make_db_path("bg-reindex.db")

    result = reindex(db_path=db_path, source_path=source, force=True, background=True)
    assert "job_id" in result
    assert result["status"] == "queued"

    # Wait for completion.
    _get_bg_indexer().drain(timeout=10)

    job = _get_bg_indexer().get_job(result["job_id"])
    assert job is not None
    assert job.status == "completed"
    assert job.result["indexed_files"] == 1


def test_reindex_many_background(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    sa = tmp_path / "sa"
    sb = tmp_path / "sb"
    sa.mkdir()
    sb.mkdir()
    (sa / "a.md").write_text("# A\n\ncache ttl", encoding="utf-8")
    (sb / "b.md").write_text("# B\n\nprotocol tool", encoding="utf-8")

    db_path = make_db_path("bg-reindex-many.db")

    result = reindex_many(
        db_path=db_path,
        source_paths=[sa, sb],
        force=True,
        background=True,
    )
    assert result["status"] == "queued"

    _get_bg_indexer().drain(timeout=10)

    job = _get_bg_indexer().get_job(result["job_id"])
    assert job.status == "completed"
    assert job.result["indexed_files"] == 2


def test_reindex_blocking_still_works(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    source = tmp_path / "src"
    source.mkdir()
    (source / "a.md").write_text("# A\n\ncache ttl policy", encoding="utf-8")

    db_path = make_db_path("blocking-reindex.db")

    result = reindex(db_path=db_path, source_path=source, force=True, background=False)
    assert result["indexed_files"] == 1
    assert "job_id" not in result


def test_index_status_includes_background_jobs(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    source = tmp_path / "src"
    source.mkdir()
    (source / "a.md").write_text("# A\n\ncache ttl", encoding="utf-8")

    db_path = make_db_path("bg-status.db")

    reindex(db_path=db_path, source_path=source, force=True, background=True)
    _get_bg_indexer().drain(timeout=10)

    status = index_status(db_path=db_path)
    assert "background_jobs" in status
    assert len(status["background_jobs"]) >= 1
    assert status["background_jobs"][0]["status"] == "completed"
