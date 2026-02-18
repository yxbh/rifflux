from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from rifflux.config import RiffluxConfig
from rifflux.embeddings.hash_embedder import hash_embed


@dataclass(slots=True)
class EmbedderBundle:
    embed: Callable[[str], np.ndarray]
    model_label: str


def _normalize_dim(vec: np.ndarray, target_dim: int) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    if arr.ndim != 1:
        arr = arr.reshape(-1)
    if arr.shape[0] == target_dim:
        out = arr
    elif arr.shape[0] > target_dim:
        out = arr[:target_dim]
    else:
        out = np.pad(arr, (0, target_dim - arr.shape[0]))
    norm = np.linalg.norm(out)
    if norm > 0:
        out = out / norm
    return out.astype(np.float32)


def _hash_embedder(config: RiffluxConfig) -> EmbedderBundle:
    def embed(text: str) -> np.ndarray:
        return hash_embed(text, dim=config.embedding_dim)

    return EmbedderBundle(embed=embed, model_label=f"hash-{config.embedding_dim}")


def _fastembed_embedder(config: RiffluxConfig) -> EmbedderBundle | None:
    try:
        from fastembed import TextEmbedding  # type: ignore
    except Exception:
        return None

    model = TextEmbedding(model_name=config.embedding_model)

    def embed(text: str) -> np.ndarray:
        vector = next(model.embed([text]))
        return _normalize_dim(np.asarray(vector, dtype=np.float32), config.embedding_dim)

    model_name = config.embedding_model.replace("/", "-")
    return EmbedderBundle(embed=embed, model_label=f"onnx-{model_name}-{config.embedding_dim}")


def resolve_embedder(config: RiffluxConfig) -> EmbedderBundle:
    backend = config.embedding_backend.lower().strip()
    if backend == "hash":
        return _hash_embedder(config)
    if backend == "onnx":
        onnx_bundle = _fastembed_embedder(config)
        if onnx_bundle:
            return onnx_bundle
        return _hash_embedder(config)
    onnx_bundle = _fastembed_embedder(config)
    if onnx_bundle:
        return onnx_bundle
    return _hash_embedder(config)
