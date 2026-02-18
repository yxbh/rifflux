from __future__ import annotations

import numpy as np

from rifflux.retrieval.semantic import _cosine_similarity, semantic_search


class _FakeStore:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def all_embeddings(self) -> list[dict]:
        return self._rows


def _row(
    chunk_id: str,
    path: str,
    heading_path: str,
    chunk_index: int,
    content: str,
    vector: np.ndarray,
) -> dict:
    vec = vector.astype(np.float32)
    return {
        "chunk_id": chunk_id,
        "path": path,
        "heading_path": heading_path,
        "chunk_index": chunk_index,
        "content": content,
        "dim": int(vec.shape[0]),
        "vector": vec.tobytes(),
    }


def test_cosine_similarity_returns_zero_when_denominator_is_zero() -> None:
    a = np.array([0.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 0.0], dtype=np.float32)

    score = _cosine_similarity(a, b)

    assert score == 0.0


def test_semantic_search_returns_empty_when_query_vector_none() -> None:
    store = _FakeStore(
        rows=[
            _row(
                chunk_id="c1",
                path="docs/one.md",
                heading_path="Intro",
                chunk_index=0,
                content="redis cache",
                vector=np.array([1.0, 0.0], dtype=np.float32),
            )
        ]
    )

    results = semantic_search(store=store, query_vector=None, top_k=5)

    assert results == []


def test_semantic_search_sorts_by_cosine_and_applies_top_k() -> None:
    store = _FakeStore(
        rows=[
            _row(
                chunk_id="c1",
                path="docs/one.md",
                heading_path="Intro",
                chunk_index=0,
                content="redis cache",
                vector=np.array([1.0, 0.0], dtype=np.float32),
            ),
            _row(
                chunk_id="c2",
                path="docs/two.md",
                heading_path="Details",
                chunk_index=1,
                content="mcp tools",
                vector=np.array([0.0, 1.0], dtype=np.float32),
            ),
        ]
    )

    results = semantic_search(
        store=store,
        query_vector=np.array([1.0, 0.0], dtype=np.float32),
        top_k=1,
    )

    assert len(results) == 1
    assert results[0]["chunk_id"] == "c1"
    assert "cosine" in results[0]
