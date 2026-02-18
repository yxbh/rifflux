from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from rifflux.db.sqlite_store import SqliteStore
from rifflux.retrieval.lexical import lexical_search
from rifflux.retrieval.rrf import rrf_fuse
from rifflux.retrieval.semantic import semantic_search


class SearchService:
    def __init__(
        self,
        store: SqliteStore,
        *,
        embed_query: Callable[[str], np.ndarray] | None = None,
        rrf_k: int = 60,
    ) -> None:
        self.store = store
        self.embed_query = embed_query
        self.rrf_k = rrf_k

    def search(self, query: str, *, top_k: int = 10, mode: str = "hybrid") -> list[dict[str, Any]]:
        lexical = (
            lexical_search(self.store, query, top_k=top_k * 2)
            if mode in {"hybrid", "lexical"}
            else []
        )
        query_vec = (
            self.embed_query(query)
            if self.embed_query and mode in {"hybrid", "semantic"}
            else None
        )
        semantic = (
            semantic_search(self.store, query_vec, top_k=top_k * 2)
            if mode in {"hybrid", "semantic"}
            else []
        )

        if mode == "lexical":
            return [
                {**row, "score_breakdown": {"bm25": row["bm25_score"]}}
                for row in lexical[:top_k]
            ]
        if mode == "semantic":
            return [
                {**row, "score_breakdown": {"cosine": row["cosine"]}}
                for row in semantic[:top_k]
            ]

        lexical_ids = [row["chunk_id"] for row in lexical]
        semantic_ids = [row["chunk_id"] for row in semantic]
        fused = rrf_fuse({"lexical": lexical_ids, "semantic": semantic_ids}, k=self.rrf_k)
        lexical_map = {row["chunk_id"]: row for row in lexical}
        semantic_map = {row["chunk_id"]: row for row in semantic}

        output: list[dict[str, Any]] = []
        for chunk_id, score in list(fused.items())[:top_k]:
            base = semantic_map.get(chunk_id) or lexical_map.get(chunk_id)
            if base is None:
                continue
            lexical_rank = lexical_ids.index(chunk_id) + 1 if chunk_id in lexical_map else None
            semantic_rank = semantic_ids.index(chunk_id) + 1 if chunk_id in semantic_map else None
            output.append(
                {
                    "chunk_id": chunk_id,
                    "path": base["path"],
                    "heading_path": base["heading_path"],
                    "chunk_index": base["chunk_index"],
                    "content": base["content"],
                    "score_breakdown": {
                        "rrf": score,
                        "lexical_rank": lexical_rank,
                        "semantic_rank": semantic_rank,
                    },
                }
            )
        return output

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self.store.get_chunk(chunk_id)

    def get_file(self, path: str) -> dict[str, Any] | None:
        return self.store.get_file(path)
