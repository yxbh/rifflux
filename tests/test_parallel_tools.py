"""Verify parallel MCP tool calls don't deadlock on SQLite access."""
from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from pathlib import Path

import pytest

from rifflux.mcp.tools import (
    get_chunk,
    index_status,
    reindex,
    search_rifflux,
)


@pytest.fixture
def indexed_db(
    fixture_corpus_path: Path,
    make_db_path: Callable[[str], Path],
    monkeypatch,
) -> Path:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")
    db_path = make_db_path("parallel.db")
    reindex(db_path=db_path, source_path=fixture_corpus_path, force=True)
    return db_path


def test_parallel_search_calls_do_not_deadlock(indexed_db: Path) -> None:
    """Simulate Copilot dispatching multiple search tool calls at once."""
    queries = ["cache ttl", "MCP server", "retrieval architecture"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(
                search_rifflux,
                db_path=indexed_db,
                query=q,
                top_k=5,
                mode="hybrid",
            )
            for q in queries
        ]
        results = [f.result(timeout=30) for f in futures]

    assert len(results) == 3
    for result in results:
        assert result["count"] >= 1


def test_parallel_mixed_tool_calls(indexed_db: Path) -> None:
    """Mix of search, index_status, and get_chunk running in parallel."""
    search_result = search_rifflux(
        db_path=indexed_db, query="cache", top_k=1, mode="hybrid",
    )
    chunk_id = search_result["results"][0]["chunk_id"]

    def call_search() -> dict:
        return search_rifflux(
            db_path=indexed_db, query="cache ttl", top_k=3, mode="hybrid",
        )

    def call_status() -> dict:
        return index_status(db_path=indexed_db)

    def call_chunk() -> dict:
        return get_chunk(db_path=indexed_db, chunk_id=chunk_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        fs = [pool.submit(fn) for fn in [call_search, call_status, call_chunk]]
        results = [f.result(timeout=30) for f in fs]

    assert results[0]["count"] >= 1
    assert results[1]["files"] >= 1
    assert results[2]["chunk"] is not None
