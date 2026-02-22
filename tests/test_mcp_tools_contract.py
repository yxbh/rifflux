from collections.abc import Callable
from pathlib import Path
import sqlite3

import pytest

import rifflux.mcp.tools as mcp_tools
from rifflux.mcp.tools import (
    get_chunk,
    get_file,
    index_status,
    reindex,
    reindex_many,
    search_rifflux,
)


def test_mcp_tool_contracts_end_to_end(
    fixture_corpus_path: Path,
    make_db_path: Callable[[str], Path],
    monkeypatch,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    source_path = fixture_corpus_path
    db_path = make_db_path("rifflux-tools.db")

    reindex_result = reindex(db_path=db_path, source_path=source_path, force=True)
    assert "indexed_files" in reindex_result
    assert "embedding_model" in reindex_result

    status = index_status(db_path=db_path)
    assert {
        "files",
        "chunks",
        "embeddings",
        "db_path",
        "embedding_backend",
        "embedding_model",
        "git_fingerprint",
    }.issubset(status)
    assert status["files"] >= 1

    search = search_rifflux(db_path=db_path, query="cache ttl", top_k=3, mode="hybrid")
    assert {"query", "mode", "count", "embedding_model", "results"}.issubset(search)
    assert search["count"] >= 1

    first = search["results"][0]
    assert {
        "chunk_id",
        "path",
        "heading_path",
        "chunk_index",
        "content",
        "score_breakdown",
    }.issubset(first)

    chunk = get_chunk(db_path=db_path, chunk_id=first["chunk_id"])
    assert "chunk" in chunk
    assert chunk["chunk"] is not None

    file_data = get_file(db_path=db_path, path=first["path"])
    assert "file" in file_data
    assert file_data["file"] is not None
    assert "chunks" in file_data["file"]


def test_reindex_many_supports_multiple_input_locations(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-tools-many.db")
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    source_a.mkdir(parents=True, exist_ok=True)
    source_b.mkdir(parents=True, exist_ok=True)
    (source_a / "a.md").write_text("# A\n\ncache ttl policy", encoding="utf-8")
    (source_b / "b.md").write_text("# B\n\nprotocol tool contract", encoding="utf-8")

    result = reindex_many(db_path=db_path, source_paths=[source_a, source_b], force=True)

    assert result["indexed_files"] == 2
    assert result["skipped_files"] == 0
    assert result["deleted_files"] == 0
    assert result["prune_missing"] is True
    assert len(result["indexed_paths"]) == 2
    assert "embedding_model" in result
    assert "git_fingerprint" in result


def test_reindex_many_prunes_stale_files(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-tools-prune.db")
    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    file_a = source / "a.md"
    file_b = source / "b.md"
    file_a.write_text("# A\n\ncache ttl", encoding="utf-8")
    file_b.write_text("# B\n\nprotocol tool", encoding="utf-8")

    first = reindex_many(db_path=db_path, source_paths=[source], force=True)
    assert first["indexed_files"] == 2
    assert first["deleted_files"] == 0

    file_b.unlink()
    second = reindex_many(db_path=db_path, source_paths=[source], force=False)
    assert second["deleted_files"] == 1

    status = index_status(db_path=db_path)
    assert status["files"] == 1


def test_reindex_many_can_disable_stale_pruning(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-tools-no-prune.db")
    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    file_a = source / "a.md"
    file_b = source / "b.md"
    file_a.write_text("# A\n\ncache ttl", encoding="utf-8")
    file_b.write_text("# B\n\nprotocol tool", encoding="utf-8")

    first = reindex_many(db_path=db_path, source_paths=[source], force=True)
    assert first["indexed_files"] == 2

    file_b.unlink()
    second = reindex_many(
        db_path=db_path,
        source_paths=[source],
        force=False,
        prune_missing=False,
    )
    assert second["deleted_files"] == 0
    assert second["prune_missing"] is False

    status = index_status(db_path=db_path)
    assert status["files"] == 2


def test_reindex_many_respects_configured_exclude_globs(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RIFFLUX_INDEX_INCLUDE_GLOBS", "*.md")
    monkeypatch.setenv("RIFFLUX_INDEX_EXCLUDE_GLOBS", ".venv/*")

    db_path = make_db_path("rifflux-tools-exclude.db")
    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "keep.md").write_text("# Keep\n\ncache ttl", encoding="utf-8")
    (source / ".venv").mkdir(parents=True, exist_ok=True)
    (source / ".venv" / "skip.md").write_text("# Skip\n\nshould not index", encoding="utf-8")

    result = reindex_many(db_path=db_path, source_paths=[source], force=True)
    assert result["indexed_files"] == 1

    status = index_status(db_path=db_path)
    assert status["files"] == 1
    assert status["index_include_globs"] == ["*.md"]
    assert status["index_exclude_globs"] == [".venv/*"]


def test_operational_error_includes_rebuild_hint(
    make_db_path: Callable[[str], Path],
    monkeypatch,
) -> None:
    db_path = make_db_path("broken.db")

    def fake_services(*args, **kwargs):
        raise sqlite3.OperationalError("SQL logic error")

    monkeypatch.setattr(mcp_tools, "_services", fake_services)

    with pytest.raises(RuntimeError) as exc_info:
        index_status(db_path=db_path)

    message = str(exc_info.value)
    assert "rifflux-rebuild" in message
    assert str(db_path) in message


def test_search_can_auto_reindex_when_enabled(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RIFFLUX_AUTO_REINDEX_ON_SEARCH", "1")
    monkeypatch.setenv("RIFFLUX_AUTO_REINDEX_MIN_INTERVAL_SECONDS", "0")

    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    doc = source / "note.md"
    doc.write_text(
        "# Note\n\n"
        "cache ttl policy repeated for chunk sizing coverage. "
        "cache ttl policy repeated for chunk sizing coverage. "
        "cache ttl policy repeated for chunk sizing coverage.",
        encoding="utf-8",
    )
    monkeypatch.setenv("RIFFLUX_AUTO_REINDEX_PATHS", str(source))

    db_path = make_db_path("rifflux-tools-auto-reindex.db")

    first = search_rifflux(db_path=db_path, query="cache ttl", top_k=5, mode="hybrid")
    assert first["auto_reindex"] is not None
    assert first["auto_reindex"]["executed"] == "background"
    assert "job_id" in first["auto_reindex"]

    # Wait for the background reindex job to finish before checking results.
    import rifflux.mcp.tools as _tools_mod
    _tools_mod._get_bg_indexer().drain(timeout=10)

    # Now search again to see the freshly-indexed content.
    first2 = search_rifflux(db_path=db_path, query="cache ttl", top_k=5, mode="hybrid")
    assert first2["count"] >= 1

    doc.write_text(
        "# Note\n\n"
        "semantic refresh marker repeated for chunk sizing coverage. "
        "semantic refresh marker repeated for chunk sizing coverage. "
        "semantic refresh marker repeated for chunk sizing coverage.",
        encoding="utf-8",
    )
    second = search_rifflux(
        db_path=db_path,
        query="semantic refresh marker",
        top_k=5,
        mode="hybrid",
    )
    assert second["auto_reindex"] is not None
    assert second["auto_reindex"]["executed"] == "background"

    _tools_mod._get_bg_indexer().drain(timeout=10)

    second2 = search_rifflux(
        db_path=db_path,
        query="semantic refresh marker",
        top_k=5,
        mode="hybrid",
    )
    assert second2["count"] >= 1
