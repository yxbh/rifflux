from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from rifflux.db.sqlite_store import SqliteStore
from rifflux.retrieval.lexical import lexical_search
from rifflux.retrieval.rrf import rrf_fuse
from rifflux.retrieval.semantic import semantic_search

logger = logging.getLogger("rifflux.retrieval")

# Defaults for expansion parameters.
_DEFAULT_EXPAND_SEEDS = 3
_DEFAULT_SIBLING_WINDOW = 2
_DEFAULT_SEMANTIC_EXPAND_K = 5


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
        t0 = time.perf_counter()

        t_lex = time.perf_counter()
        lexical = (
            lexical_search(self.store, query, top_k=top_k * 2)
            if mode in {"hybrid", "lexical"}
            else []
        )
        dt_lex = time.perf_counter() - t_lex

        t_embed = time.perf_counter()
        query_vec = (
            self.embed_query(query)
            if self.embed_query and mode in {"hybrid", "semantic"}
            else None
        )
        dt_embed = time.perf_counter() - t_embed

        t_sem = time.perf_counter()
        semantic = (
            semantic_search(self.store, query_vec, top_k=top_k * 2)
            if mode in {"hybrid", "semantic"}
            else []
        )
        dt_sem = time.perf_counter() - t_sem

        logger.debug(
            "search phases: lexical=%.3fs (%d hits) embed=%.3fs semantic=%.3fs (%d hits)",
            dt_lex, len(lexical), dt_embed, dt_sem, len(semantic),
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

    def expand(
        self,
        results: list[dict[str, Any]],
        *,
        max_seeds: int = _DEFAULT_EXPAND_SEEDS,
        sibling_window: int = _DEFAULT_SIBLING_WINDOW,
        semantic_k: int = _DEFAULT_SEMANTIC_EXPAND_K,
    ) -> list[dict[str, Any]]:
        """Return 2nd-degree related chunks for the given search results.

        Expansion produces two pools:
        1. Sibling chunks from the same file (±sibling_window), in doc order.
        2. Cross-file semantically similar chunks via stored embeddings.
        Both pools are deduped against the seed chunk_ids.
        """
        t0 = time.perf_counter()
        seed_ids: set[str] = {r["chunk_id"] for r in results}
        seen_ids: set[str] = set(seed_ids)
        siblings: list[dict[str, Any]] = []
        cross_file: list[dict[str, Any]] = []

        seeds = results[:max_seeds]

        # 1. Sibling expansion
        for seed in seeds:
            for sib in self.store.get_sibling_chunks(
                seed["path"], seed["chunk_index"], window=sibling_window,
            ):
                if sib["chunk_id"] not in seen_ids:
                    seen_ids.add(sib["chunk_id"])
                    sib["relation"] = "sibling"
                    siblings.append(sib)

        # 2. Cross-file semantic expansion
        if self.embed_query is not None:
            for seed in seeds:
                seed_vec = self.store.get_embedding(seed["chunk_id"])
                if seed_vec is None:
                    continue
                neighbors = semantic_search(
                    self.store, seed_vec, top_k=semantic_k + len(seen_ids),
                )
                for neighbor in neighbors:
                    if neighbor["chunk_id"] in seen_ids:
                        continue
                    seen_ids.add(neighbor["chunk_id"])
                    cross_file.append({
                        "chunk_id": neighbor["chunk_id"],
                        "path": neighbor["path"],
                        "heading_path": neighbor["heading_path"],
                        "chunk_index": neighbor["chunk_index"],
                        "content": neighbor["content"],
                        "relation": "semantic",
                        "cosine": neighbor["cosine"],
                    })
                    if len(cross_file) >= semantic_k:
                        break
                if len(cross_file) >= semantic_k:
                    break

        related = siblings + cross_file
        dt = time.perf_counter() - t0
        logger.debug(
            "expand done in %.3fs siblings=%d cross_file=%d",
            dt, len(siblings), len(cross_file),
        )
        return related
