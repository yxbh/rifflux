from collections.abc import Callable
from pathlib import Path

from rifflux.db.sqlite_store import SqliteStore
from rifflux.embeddings.hash_embedder import hash_embed
from rifflux.retrieval.search import SearchService


def test_search_smoke(
    make_db_path: Callable[[str], Path],
    schema_sql_path: Path,
) -> None:
    db_path = make_db_path("rifflux.db")
    store = SqliteStore(db_path)
    store.init_schema(schema_sql_path)
    file_id = store.upsert_file("docs/one.md", 1, 100, "abc")
    store.insert_chunk(
        chunk_id="c1",
        file_id=file_id,
        chunk_index=0,
        heading_path="Intro",
        content="redis cache policy and ttl",
        token_count=5,
    )
    store.insert_embedding(
        chunk_id="c1",
        model="hash-384",
        vector=hash_embed("redis cache policy and ttl"),
    )
    store.commit()

    service = SearchService(store, embed_query=hash_embed)
    results = service.search("cache ttl", top_k=3, mode="hybrid")
    assert results
    assert results[0]["path"] == "docs/one.md"
    store.close()
