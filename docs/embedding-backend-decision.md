## Embedding Backend Decision Record

This document explains why Rifflux uses ONNX as the primary semantic
embedding path (with `auto` fallback behavior), what alternatives were
considered, and the practical trade-offs.

## Decision Context

Rifflux goals relevant to embedding selection:

- Local/offline operation by default.
- Strong semantic retrieval quality for hybrid search.
- Predictable operation in constrained/dev/CI environments.
- Minimal operational burden for a Python-first local tool.

## Decision

- Primary quality path: ONNX-capable local embedding backend (`onnx`).
- Operational default: `auto` (`onnx` first, deterministic `hash` fallback).
- Deterministic fallback path: `hash` (`hash-384`) for low-friction setups.

In short: ONNX is chosen for semantic quality without requiring cloud APIs,
while `auto` preserves resiliency when ONNX dependencies are unavailable.

## Options Considered

| Option | Quality | Offline | Setup Complexity | Portability | Determinism | Why chosen / not chosen |
|---|---|---|---|---|---|---|
| `hash` (`hash-384`) | Low-Medium | Excellent | Very low | Excellent | High | Kept as deterministic fallback; not primary due lower semantic fidelity |
| ONNX local models (current) | Medium-High | Excellent | Medium | Good | Medium | **Chosen primary**: best quality/operability balance for local-first use |
| PyTorch sentence-transformers runtime | High | Excellent | High | Medium | Medium | Not chosen now: larger dependency/runtime footprint and operational complexity |
| Cloud embedding APIs | High | Poor (requires network) | Medium | Medium | Medium | Not chosen by design: conflicts with no-cloud/offline objective |
| GGUF/llama.cpp style embedding runtimes | Medium-High | Excellent | Medium-High | Medium | Medium | Not chosen now: extra runtime/tooling complexity, less mature integration path here |

## Why ONNX Was Chosen

ONNX was selected as the primary semantic backend because it is the best
fit for Rifflux constraints:

- Delivers better semantic ranking than hash-only baselines.
- Runs locally without cloud dependence.
- Avoids bringing full PyTorch runtime complexity into default workflows.
- Works with `auto` strategy so deployments degrade gracefully instead of
  failing hard when model/runtime dependencies are missing.

## Why `auto` Is the Runtime Default

`auto` is a product default (not a benchmark-quality default) because it
prioritizes reliability across heterogeneous environments:

- If ONNX is present: use better semantic path.
- If ONNX is absent: continue operating via deterministic `hash` fallback.

This avoids startup failures in local/dev/CI contexts while still enabling
higher quality where available.

## Practical Guidance

- Use `onnx` when semantic quality is a priority and environment setup is
  controlled.
- Use `hash` for deterministic CI baselines, minimal setup, or constrained
  hosts.
- Use `auto` when you need robust behavior across mixed environments.

## Specific ONNX Model Guidance

Current recommended model for Rifflux:

- `BAAI/bge-small-en-v1.5` (default)

Why this is the default:

- Good semantic quality for local hybrid retrieval at modest runtime cost.
- Works well with the current default embedding dimension (`384`).
- Reasonable local operational footprint for Python-first/offline workflows.

How to choose a model in practice:

- Stay on `BAAI/bge-small-en-v1.5` unless you have a measured reason to
  change.
- If you change `RIFFLUX_EMBEDDING_MODEL`, keep `RIFFLUX_EMBEDDING_DIM`
  aligned with the model's native output dimension whenever possible.
- Reindex after model changes so stored vectors are consistent with query-time
  embeddings.

Important implementation note:

- Rifflux normalizes vectors and force-fits dimensions to
  `RIFFLUX_EMBEDDING_DIM` (truncate/pad). Using a model with a mismatched
  native dimension can degrade retrieval quality.

## Future Revisit Criteria

Re-evaluate backend choice if one of these changes materially:

- ONNX semantic quality or latency becomes a bottleneck for target corpora.
- A lower-complexity backend provides clearly better quality/latency.
- Operational constraints change (for example, cloud dependencies become
  acceptable for a deployment profile).
