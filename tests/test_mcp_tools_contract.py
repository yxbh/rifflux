import sqlite3
from collections.abc import Callable
from pathlib import Path

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
    assert Path(first["path"]).is_absolute()

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


def test_search_returns_absolute_paths_for_multi_root_indexes(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-tools-absolute-paths.db")
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    source_a.mkdir(parents=True, exist_ok=True)
    source_b.mkdir(parents=True, exist_ok=True)

    file_a = source_a / "shared.md"
    file_b = source_b / "shared.md"
    file_a.write_text(
        "# A\n\n"
        "cache ttl policy in source a repeated for chunk sizing coverage. "
        "cache ttl policy in source a repeated for chunk sizing coverage. "
        "cache ttl policy in source a repeated for chunk sizing coverage.",
        encoding="utf-8",
    )
    file_b.write_text(
        "# B\n\n"
        "cache ttl policy in source b repeated for chunk sizing coverage. "
        "cache ttl policy in source b repeated for chunk sizing coverage. "
        "cache ttl policy in source b repeated for chunk sizing coverage.",
        encoding="utf-8",
    )

    reindex_many(db_path=db_path, source_paths=[source_a, source_b], force=True)

    search = search_rifflux(db_path=db_path, query="cache ttl policy", top_k=10, mode="lexical")
    assert search["count"] == 2

    returned_paths = {row["path"] for row in search["results"]}
    expected_paths = {
        str(file_a.resolve()).replace("\\", "/"),
        str(file_b.resolve()).replace("\\", "/"),
    }
    assert returned_paths == expected_paths


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


def test_reindex_many_excludes_tmp_by_default(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-tools-default-tmp-exclude.db")
    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "keep.md").write_text("# Keep\n\ncache ttl", encoding="utf-8")
    (source / ".tmp").mkdir(parents=True, exist_ok=True)
    (source / ".tmp" / "skip.md").write_text("# Skip\n\nbenchmark corpus", encoding="utf-8")

    result = reindex_many(db_path=db_path, source_paths=[source], force=True)
    assert result["indexed_files"] == 1

    status = index_status(db_path=db_path)
    assert status["files"] == 1
    assert ".tmp/*" in status["index_exclude_globs"]


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


def _write_multi_chunk_corpus(root: Path) -> None:
    """Write a corpus with multiple chunks in one file and a second related file."""
    root.mkdir(parents=True, exist_ok=True)
    # File with multiple heading sections → multiple chunks
    (root / "guide.md").write_text(
        "# Guide\n\n"
        "## Introduction\n\n"
        "This introduction covers cache ttl policies and expiry strategies "
        "for local development workflows. Cache ttl policies are critical "
        "for reliable offline retrieval.\n\n"
        "## Configuration\n\n"
        "Configuration of cache ttl parameters including max-age, stale-while-"
        "revalidate, and expiry windows for different content types.\n\n"
        "## Advanced\n\n"
        "Advanced cache ttl tuning with sliding windows, adaptive refresh "
        "intervals, and capacity-based eviction policies for large corpora.\n",
        encoding="utf-8",
    )
    # Second file with related content
    (root / "reference.md").write_text(
        "# Reference\n\n"
        "## Cache Invalidation\n\n"
        "Cache invalidation patterns and cache ttl best practices for "
        "distributed systems and local indexes. Covers write-through, "
        "write-behind, and refresh-ahead strategies.\n",
        encoding="utf-8",
    )


def test_search_expand_returns_sibling_chunks(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-expand-siblings.db")
    corpus = tmp_path / "corpus"
    _write_multi_chunk_corpus(corpus)

    reindex_many(db_path=db_path, source_paths=[corpus], force=True)

    result = search_rifflux(
        db_path=db_path,
        query="cache ttl",
        top_k=1,
        mode="lexical",
        expand=True,
    )

    assert "related" in result
    assert "related_count" in result
    assert result["related_count"] >= 1

    # Related chunks should have a "relation" field
    for related in result["related"]:
        assert related["relation"] in {"sibling", "semantic"}
        assert "chunk_id" in related
        assert "path" in related
        assert "content" in related

    # Sibling chunks should come from the same file as the seed
    seed_path = result["results"][0]["path"]
    sibling_related = [r for r in result["related"] if r["relation"] == "sibling"]
    assert len(sibling_related) >= 1
    for sib in sibling_related:
        assert sib["path"] == seed_path


def test_search_expand_deduplicates_against_results(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-expand-dedup.db")
    corpus = tmp_path / "corpus"
    _write_multi_chunk_corpus(corpus)

    reindex_many(db_path=db_path, source_paths=[corpus], force=True)

    result = search_rifflux(
        db_path=db_path,
        query="cache ttl",
        top_k=5,
        mode="hybrid",
        expand=True,
    )

    result_ids = {r["chunk_id"] for r in result["results"]}
    related_ids = {r["chunk_id"] for r in result.get("related", [])}
    # No overlap between results and related
    assert result_ids.isdisjoint(related_ids)


def test_search_expand_false_omits_related(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-expand-off.db")
    corpus = tmp_path / "corpus"
    _write_multi_chunk_corpus(corpus)

    reindex_many(db_path=db_path, source_paths=[corpus], force=True)

    result = search_rifflux(
        db_path=db_path,
        query="cache ttl",
        top_k=3,
        mode="hybrid",
        expand=False,
    )

    assert "related" not in result
    assert "related_count" not in result


def test_search_expand_includes_cross_file_semantic(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-expand-crossfile.db")
    corpus = tmp_path / "corpus"
    _write_multi_chunk_corpus(corpus)

    reindex_many(db_path=db_path, source_paths=[corpus], force=True)

    # Search narrowly so we get results from one file, then expand
    result = search_rifflux(
        db_path=db_path,
        query="introduction cache ttl policies",
        top_k=1,
        mode="lexical",
        expand=True,
    )

    assert result["count"] >= 1
    related = result.get("related", [])
    assert len(related) >= 1

    seed_path = result["results"][0]["path"]
    semantic_related = [r for r in related if r["relation"] == "semantic"]
    assert len(semantic_related) >= 1
    for semantic in semantic_related:
        assert semantic["path"] != seed_path


def test_search_expand_true_includes_empty_related_when_no_results(
    make_db_path: Callable[[str], Path],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIFFLUX_EMBEDDING_BACKEND", "hash")

    db_path = make_db_path("rifflux-expand-empty.db")
    corpus = tmp_path / "corpus"
    _write_multi_chunk_corpus(corpus)

    reindex_many(db_path=db_path, source_paths=[corpus], force=True)

    result = search_rifflux(
        db_path=db_path,
        query="query-without-any-hits-xyzzy",
        top_k=3,
        mode="lexical",
        expand=True,
    )

    assert result["count"] == 0
    assert result["related"] == []
    assert result["related_count"] == 0
