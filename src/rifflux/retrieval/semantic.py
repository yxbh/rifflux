from __future__ import annotations

from typing import Any

import numpy as np

from rifflux.db.sqlite_store import SqliteStore


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def semantic_search(
    store: SqliteStore,
    query_vector: np.ndarray | None,
    top_k: int,
) -> list[dict[str, Any]]:
    if query_vector is None:
        return []
    candidates: list[dict[str, Any]] = []
    for row in store.all_embeddings():
        dim = int(row["dim"])
        vec = np.frombuffer(row["vector"], dtype=np.float32, count=dim)
        score = _cosine_similarity(query_vector, vec)
        candidates.append(
            {
                "chunk_id": row["chunk_id"],
                "path": row["path"],
                "heading_path": row["heading_path"],
                "chunk_index": row["chunk_index"],
                "content": row["content"],
                "cosine": score,
            }
        )
    candidates.sort(key=lambda x: x["cosine"], reverse=True)
    return candidates[:top_k]
