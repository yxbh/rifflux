from collections.abc import Callable
from pathlib import Path

from rifflux.db.sqlite_store import SqliteStore
from rifflux.embeddings.hash_embedder import hash_embed
from rifflux.retrieval.search import SearchService


def _seed_store(db_path: Path, schema_path: Path) -> SqliteStore:
    store = SqliteStore(db_path)
    store.init_schema(schema_path)

    file_id = store.upsert_file("docs/search.md", 1, 100, "sha")
    chunks = [
        ("c1", 0, "Intro", "redis cache ttl policy and eviction"),
        ("c2", 1, "Other", "mcp protocol server tool description"),
    ]
    for chunk_id, chunk_index, heading_path, content in chunks:
        store.insert_chunk(
            chunk_id=chunk_id,
            file_id=file_id,
            chunk_index=chunk_index,
            heading_path=heading_path,
            content=content,
            token_count=len(content.split()),
        )
        store.insert_embedding(chunk_id=chunk_id, model="hash-384", vector=hash_embed(content))

    store.commit()
    return store


def test_lexical_mode_returns_bm25_breakdown(
    make_db_path: Callable[[str], Path],
    schema_sql_path: Path,
) -> None:
    store = _seed_store(make_db_path("lexical.db"), schema_sql_path)
    service = SearchService(store, embed_query=hash_embed)

    results = service.search("cache ttl", top_k=3, mode="lexical")
    assert results
    assert "bm25" in results[0]["score_breakdown"]
    store.close()


def test_semantic_mode_returns_cosine_breakdown(
    make_db_path: Callable[[str], Path],
    schema_sql_path: Path,
) -> None:
    store = _seed_store(make_db_path("semantic.db"), schema_sql_path)
    service = SearchService(store, embed_query=hash_embed)

    results = service.search("protocol tools", top_k=3, mode="semantic")
    assert results
    assert "cosine" in results[0]["score_breakdown"]
    store.close()


def test_hybrid_mode_returns_rrf_breakdown(
    make_db_path: Callable[[str], Path],
    schema_sql_path: Path,
) -> None:
    store = _seed_store(make_db_path("hybrid.db"), schema_sql_path)
    service = SearchService(store, embed_query=hash_embed)

    results = service.search("cache policy", top_k=3, mode="hybrid")
    assert results
    assert "rrf" in results[0]["score_breakdown"]
    assert "lexical_rank" in results[0]["score_breakdown"]
    assert "semantic_rank" in results[0]["score_breakdown"]
    store.close()


def test_lexical_mode_handles_punctuation_heavy_query(
    make_db_path: Callable[[str], Path],
    schema_sql_path: Path,
) -> None:
    store = SqliteStore(make_db_path("punctuation.db"))
    store.init_schema(schema_sql_path)

    file_id = store.upsert_file(".github/AGENTS.md", 1, 100, "sha-agents")
    content = ".github/agents/python-mcp-expert.agent.md"
    store.insert_chunk(
        chunk_id="c-agents",
        file_id=file_id,
        chunk_index=0,
        heading_path="AGENTS for Rifflux > Custom agents",
        content=content,
        token_count=len(content.split()),
    )
    store.insert_embedding(chunk_id="c-agents", model="hash-384", vector=hash_embed(content))
    store.commit()

    service = SearchService(store, embed_query=hash_embed)
    results = service.search("python mcp agent file .agent.md", top_k=3, mode="lexical")

    assert results
    assert results[0]["chunk_id"] == "c-agents"
    assert "bm25" in results[0]["score_breakdown"]
    store.close()


def test_lexical_mode_handles_comma_in_query(
    make_db_path: Callable[[str], Path],
    schema_sql_path: Path,
) -> None:
    store = _seed_store(make_db_path("lexical-comma.db"), schema_sql_path)
    service = SearchService(store, embed_query=hash_embed)

    results = service.search(
        "server setup, tools registration",
        top_k=3,
        mode="lexical",
    )

    assert isinstance(results, list)
    store.close()


def test_lexical_mode_handles_dash_in_query(
    make_db_path: Callable[[str], Path],
    schema_sql_path: Path,
) -> None:
    store = _seed_store(make_db_path("lexical-dash.db"), schema_sql_path)
    service = SearchService(store, embed_query=hash_embed)

    results = service.search("streamable-http", top_k=3, mode="lexical")

    assert isinstance(results, list)
    store.close()


def test_lexical_mode_handles_unterminated_quote_query(
    make_db_path: Callable[[str], Path],
    schema_sql_path: Path,
) -> None:
    store = _seed_store(make_db_path("lexical-unterminated-quote.db"), schema_sql_path)
    service = SearchService(store, embed_query=hash_embed)

    results = service.search('"streamable-http', top_k=3, mode="lexical")

    assert isinstance(results, list)
    store.close()


def test_lexical_mode_handles_punctuation_only_query(
    make_db_path: Callable[[str], Path],
    schema_sql_path: Path,
) -> None:
    store = _seed_store(make_db_path("lexical-punctuation-only.db"), schema_sql_path)
    service = SearchService(store, embed_query=hash_embed)

    results = service.search(".,:()\"", top_k=3, mode="lexical")

    assert results == []
    store.close()
