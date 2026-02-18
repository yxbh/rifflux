from __future__ import annotations

import builtins
import sys
import types

import numpy as np

from rifflux.config import RiffluxConfig
from rifflux.embeddings import embedder_factory


def test_normalize_dim_flattens_truncates_and_normalizes() -> None:
    vector = np.array([[3.0, 4.0, 12.0]], dtype=np.float32)

    normalized = embedder_factory._normalize_dim(vector, target_dim=2)

    assert normalized.shape == (2,)
    assert np.isclose(np.linalg.norm(normalized), 1.0)


def test_normalize_dim_pads_when_input_shorter() -> None:
    vector = np.array([3.0, 4.0], dtype=np.float32)

    normalized = embedder_factory._normalize_dim(vector, target_dim=4)

    assert normalized.shape == (4,)
    assert np.isclose(np.linalg.norm(normalized), 1.0)
    assert np.allclose(normalized[2:], np.array([0.0, 0.0], dtype=np.float32))


def test_normalize_dim_keeps_exact_dim_and_handles_zero_norm() -> None:
    vector = np.array([0.0, 0.0, 0.0], dtype=np.float32)

    normalized = embedder_factory._normalize_dim(vector, target_dim=3)

    assert normalized.shape == (3,)
    assert np.allclose(normalized, np.array([0.0, 0.0, 0.0], dtype=np.float32))


def test_hash_embedder_uses_config_dim() -> None:
    config = RiffluxConfig(embedding_dim=8)

    bundle = embedder_factory._hash_embedder(config)
    embedding = bundle.embed("cache ttl")

    assert embedding.shape == (8,)
    assert bundle.model_label == "hash-8"


def test_fastembed_embedder_returns_none_when_dependency_unavailable(monkeypatch) -> None:
    original_import = builtins.__import__

    def fake_import(name: str, globals=None, locals=None, fromlist=(), level=0):
        if name == "fastembed":
            raise ImportError("missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    config = RiffluxConfig(embedding_model="X/Y", embedding_dim=16)

    bundle = embedder_factory._fastembed_embedder(config)

    assert bundle is None


def test_fastembed_embedder_returns_bundle_when_dependency_available(monkeypatch) -> None:
    class FakeTextEmbedding:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def embed(self, texts: list[str]):
            assert texts == ["cache ttl"]
            yield np.array([3.0, 4.0], dtype=np.float32)

    fake_module = types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    monkeypatch.setitem(sys.modules, "fastembed", fake_module)

    config = RiffluxConfig(embedding_model="A/B", embedding_dim=4)

    bundle = embedder_factory._fastembed_embedder(config)

    assert bundle is not None
    assert bundle.model_label == "onnx-A-B-4"
    embedding = bundle.embed("cache ttl")
    assert embedding.shape == (4,)
    assert np.isclose(np.linalg.norm(embedding), 1.0)


def test_resolve_embedder_hash_backend(monkeypatch) -> None:
    config = RiffluxConfig(embedding_backend="hash", embedding_dim=12)

    def fail_onnx(_config: RiffluxConfig):
        raise AssertionError("onnx should not be called")

    monkeypatch.setattr(embedder_factory, "_fastembed_embedder", fail_onnx)

    bundle = embedder_factory.resolve_embedder(config)

    assert bundle.model_label == "hash-12"


def test_resolve_embedder_onnx_backend_uses_onnx_when_available(monkeypatch) -> None:
    config = RiffluxConfig(embedding_backend="onnx")
    expected = embedder_factory.EmbedderBundle(
        embed=lambda text: np.array([1.0], dtype=np.float32),
        model_label="onnx-model",
    )

    monkeypatch.setattr(embedder_factory, "_fastembed_embedder", lambda _config: expected)

    bundle = embedder_factory.resolve_embedder(config)

    assert bundle is expected


def test_resolve_embedder_onnx_backend_falls_back_to_hash(monkeypatch) -> None:
    config = RiffluxConfig(embedding_backend="onnx", embedding_dim=10)

    monkeypatch.setattr(embedder_factory, "_fastembed_embedder", lambda _config: None)

    bundle = embedder_factory.resolve_embedder(config)

    assert bundle.model_label == "hash-10"


def test_resolve_embedder_auto_prefers_onnx_then_hash(monkeypatch) -> None:
    config = RiffluxConfig(embedding_backend="auto", embedding_dim=9)

    onnx_bundle = embedder_factory.EmbedderBundle(
        embed=lambda text: np.array([1.0], dtype=np.float32),
        model_label="onnx-auto",
    )

    monkeypatch.setattr(embedder_factory, "_fastembed_embedder", lambda _config: onnx_bundle)
    assert embedder_factory.resolve_embedder(config) is onnx_bundle

    monkeypatch.setattr(embedder_factory, "_fastembed_embedder", lambda _config: None)
    hash_bundle = embedder_factory.resolve_embedder(config)
    assert hash_bundle.model_label == "hash-9"
