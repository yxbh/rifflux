from __future__ import annotations

from typing import Any

from rifflux.db.sqlite_store import SqliteStore


def lexical_search(store: SqliteStore, query: str, top_k: int) -> list[dict[str, Any]]:
    return store.lexical_search(query=query, top_k=top_k)
