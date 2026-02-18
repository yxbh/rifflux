---
title: Rifflux Hybrid Retrieval and Search Tool Contract Specification
version: 1.1
date_created: 2026-02-17
last_updated: 2026-02-17
owner: Rifflux Core Team
tags: [tool, retrieval, search, mcp, contract]
---

# Introduction

This specification defines the search behavior, ranking rules, result schemas, and MCP-facing contracts for Rifflux hybrid retrieval. It is designed to be explicit, deterministic, and machine-readable for implementation and automated validation.

## 1. Purpose & Scope

This specification standardizes the retrieval behavior exposed by the Rifflux search service and MCP tool function `search_rifflux`, plus indexing input-location behavior exposed by MCP tool function `reindex`.

Scope includes:
- Lexical-only retrieval (SQLite FTS5 BM25 ranking).
- Semantic-only retrieval (cosine similarity over stored embedding vectors).
- Hybrid retrieval using Reciprocal Rank Fusion (RRF).
- Result payload contracts, score breakdown contracts, and key edge behaviors.
- Reindex input-location contracts for single and multi-location MCP calls.

Intended audience:
- Core retrieval implementers.
- MCP tool implementers.
- Test automation authors.
- Agent orchestration developers consuming search outputs.

Assumptions:
- Indexing has already produced chunk records and optional embedding records.
- Query embedding capability may be available or unavailable at runtime.

## 2. Definitions

- **BM25**: A lexical relevance ranking score produced by SQLite FTS5 `bm25(...)`.
- **Cosine Similarity**: Similarity metric computed as $\frac{a \cdot b}{\|a\|\|b\|}$.
- **RRF**: Reciprocal Rank Fusion, rank-level combination method using $\sum \frac{1}{k + rank}$.
- **Chunk**: A retrievable text unit with metadata (`chunk_id`, `path`, `heading_path`, `chunk_index`, `content`).
- **Lexical Ranking**: Ordered list of chunks from FTS5 matching.
- **Semantic Ranking**: Ordered list of chunks by descending cosine similarity to query vector.
- **Hybrid Ranking**: Fused ranking produced by applying RRF across lexical and semantic rankings.
- **Score Breakdown**: Per-result object exposing ranking evidence used for explainability.

## 3. Requirements, Constraints & Guidelines

- **REQ-001**: The system shall support `mode` values `lexical`, `semantic`, and `hybrid`.
- **REQ-002**: In `lexical` mode, results shall be sourced exclusively from lexical search.
- **REQ-003**: In `semantic` mode, results shall be sourced exclusively from semantic search.
- **REQ-004**: In `hybrid` mode, results shall be fused using RRF over lexical and semantic ranked IDs.
- **REQ-005**: Search results shall include `chunk_id`, `path`, `heading_path`, `chunk_index`, `content`, and `score_breakdown`.
- **REQ-006**: The search layer shall retrieve up to `top_k * 2` candidates per enabled modality before post-processing.
- **REQ-007**: Final output shall be truncated to at most `top_k` items.

- **RRF-001**: RRF score contribution per list shall be computed as $\frac{1}{k + rank}$ where rank starts at 1.
- **RRF-002**: RRF default constant `k` shall be configurable and default to `60`.
- **RRF-003**: Hybrid result ordering shall be descending by fused RRF score.
- **RRF-004**: Raw BM25 and cosine scores shall not be directly averaged.

- **SEM-001**: Semantic search shall return an empty list when query embedding is unavailable (`None`).
- **SEM-002**: Semantic cosine similarity with zero denominator shall evaluate to `0.0`.
- **SEM-003**: Semantic candidates shall be sorted descending by cosine score prior to truncation.

- **LEX-001**: Lexical search shall use SQLite FTS5 `MATCH` semantics.
- **LEX-002**: Lexical result ordering shall follow SQLite BM25 order (`ORDER BY bm25(...)`).

- **CON-001**: Retrieval core logic shall remain independent from MCP transport concerns.
- **CON-002**: Result metadata keys and score breakdown keys shall remain stable for downstream agents.
- **CON-003**: When a fused chunk is present in both modalities, shared metadata shall be sourced consistently from one row instance.
- **CON-004**: MCP `reindex` shall support either a single location (`path`) or multiple locations (`paths`).
- **CON-005**: If `paths` is present and non-empty, it shall take precedence over `path`.
- **CON-006**: If both `path` and `paths` are omitted, the server current working directory shall be used as the indexing location.

- **GUD-001**: Consumers should treat score breakdown values as explainability signals, not calibrated probabilities.
- **GUD-002**: Consumers should default to `hybrid` mode for general-purpose retrieval unless strict mode isolation is required.

## 4. Interfaces & Data Contracts

### 4.1 Search Service Interface

```python
search(query: str, *, top_k: int = 10, mode: str = "hybrid") -> list[dict[str, Any]]
```

Supported `mode` values:
- `lexical`
- `semantic`
- `hybrid`

### 4.2 Result Object Contract

| Field | Type | Required | Description |
|---|---|---|---|
| `chunk_id` | string | Yes | Stable chunk identifier |
| `path` | string | Yes | Relative source file path |
| `heading_path` | string | Yes | Heading breadcrumb string |
| `chunk_index` | integer | Yes | 0-based order index in file |
| `content` | string | Yes | Chunk text payload |
| `score_breakdown` | object | Yes | Mode-specific ranking details |

### 4.3 Score Breakdown Contract by Mode

Lexical mode:

```json
{
  "bm25": -1.234
}
```

Semantic mode:

```json
{
  "cosine": 0.8123
}
```

Hybrid mode:

```json
{
  "rrf": 0.0281,
  "lexical_rank": 1,
  "semantic_rank": 3
}
```

`lexical_rank` and `semantic_rank` may be `null` when the chunk is absent from the corresponding ranked list.

### 4.4 MCP Tool Contract (`search_rifflux`)

Input contract:

| Field | Type | Required | Default |
|---|---|---|---|
| `db_path` | path/null | No | runtime configuration |
| `query` | string | Yes | none |
| `top_k` | integer | No | 10 |
| `mode` | string | No | `hybrid` |

Output contract:

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | Yes | Echoed query |
| `mode` | string | Yes | Applied retrieval mode |
| `count` | integer | Yes | Number of returned results |
| `embedding_model` | string | Yes | Active embedding model label |
| `results` | array | Yes | Search result objects |

### 4.5 MCP Tool Contract (`reindex`)

Input contract:

| Field | Type | Required | Default |
|---|---|---|---|
| `path` | string/null | No | server current working directory (when `paths` omitted) |
| `paths` | array[string]/null | No | none |
| `force` | boolean | No | `false` |

Input precedence rules:
- If `paths` is provided and non-empty, `path` is ignored.
- If `paths` is omitted or empty, `path` is used.
- If both are omitted, server current working directory is used.

Output contract:

| Field | Type | Required | Description |
|---|---|---|---|
| `indexed_files` | integer | Yes | Total indexed file count across all processed locations |
| `skipped_files` | integer | Yes | Total skipped file count across all processed locations |
| `indexed_paths` | array[string] | Conditional | Present for multi-location aggregation path |
| `embedding_model` | string | Yes | Active embedding model label |
| `embedding_backend` | string | Yes | Active embedding backend identifier |

## 5. Acceptance Criteria

- **AC-001**: Given indexed text matching query terms, when `mode=lexical`, then each result contains `score_breakdown.bm25` and does not require semantic fields.
- **AC-002**: Given available query embedding and indexed vectors, when `mode=semantic`, then each result contains `score_breakdown.cosine`.
- **AC-003**: Given lexical and semantic candidate lists, when `mode=hybrid`, then each result contains `score_breakdown.rrf`, `lexical_rank`, and `semantic_rank`.
- **AC-004**: Given semantic mode with missing query embedding, when search executes, then result set is empty and no exception is raised.
- **AC-005**: Given any mode and positive `top_k`, when search completes, then returned result count is less than or equal to `top_k`.
- **AC-006**: Given MCP tool invocation, when `search_rifflux` returns, then output includes `query`, `mode`, `count`, `embedding_model`, and `results`.
- **AC-007**: Given hybrid mode, when rankings are fused, then ordering follows descending RRF score and not raw-score averaging.
- **AC-008**: Given `reindex` with `paths` containing multiple valid locations, when indexing executes, then the response aggregates counts across all provided locations.
- **AC-009**: Given both `path` and non-empty `paths`, when `reindex` executes, then only `paths` inputs are used.
- **AC-010**: Given `reindex` with no `path` and no `paths`, when indexing executes, then the server current working directory is used.

## 6. Test Automation Strategy

- **Test Levels**: Unit and integration tests.
- **Frameworks**: `pytest`.
- **Test Data Management**: Use temporary SQLite databases seeded with deterministic fixtures.
- **CI/CD Integration**: Execute retrieval and MCP contract tests in automated test workflow.
- **Coverage Requirements**:
  - Mandatory: lexical/semantic/hybrid mode behavior.
  - Mandatory: RRF fusion ranking and score-breakdown shape.
  - Mandatory: semantic `None` query-vector path and zero-denominator cosine behavior.
- **Performance Testing**: Add optional benchmark tests for candidate generation and fusion latency under increasing chunk counts.

## 7. Rationale & Context

RRF is used because it combines rank evidence across modalities without requiring score-scale normalization between BM25 and cosine metrics. This improves explainability and stability versus raw-score averaging. Separate lexical and semantic pathways ensure each modality remains testable and independently diagnosable. Mode-specific score breakdown supports downstream agent reasoning and auditability.

## 8. Dependencies & External Integrations

### External Systems
- **EXT-001**: Local filesystem corpus source - supplies indexed content.

### Third-Party Services
- **SVC-001**: None required - retrieval is local/offline by default.

### Infrastructure Dependencies
- **INF-001**: SQLite database with FTS5 support - required for lexical ranking.

### Data Dependencies
- **DAT-001**: Chunk table and embeddings table - required for retrieval results and semantic scoring.

### Technology Platform Dependencies
- **PLT-001**: Python runtime (3.11+) - required for retrieval service and MCP tool execution.
- **PLT-002**: Numerical vector operations capability (NumPy-compatible) - required for cosine similarity path.

### Compliance Dependencies
- **COM-001**: No external compliance dependency mandated by this specification; local data handling policies apply per deployment.

## 9. Examples & Edge Cases

```python
# Example: semantic mode with unavailable query embedding
results = search_service.search("cache ttl", top_k=5, mode="semantic")
# If embed_query is not configured or returns None:
# results == []

# Example: hybrid score composition
# lexical ranks:  c1=1, c2=2
# semantic ranks: c2=1, c3=2
# rrf(c2) = 1/(k+2) + 1/(k+1)
# rrf(c1) = 1/(k+1)
# rrf(c3) = 1/(k+2)
```

Edge cases:
- Empty lexical candidate set with non-empty semantic set.
- Empty semantic candidate set with non-empty lexical set.
- Both candidate sets empty.
- Duplicate chunk ID appearing in both modalities.
- Query vector with zero norm.
- `reindex` called with both `path` and `paths` populated.
- `reindex` called with `paths=[]`.

## 10. Validation Criteria

- Validate that all mode outputs conform to Section 4 contracts.
- Validate score breakdown keys by mode exactly.
- Validate fused ordering against deterministic RRF computation.
- Validate `count == len(results)` in MCP response.
- Validate no raw-score averaging exists in hybrid ranking implementation.
- Validate top-k truncation behavior with over-complete candidate sets.

## 11. Related Specifications / Further Reading

- Retrieval core constraints in repository instructions (`.github/instructions/rifflux-core.instructions.md`).
- MCP server guidance (`.github/instructions/python-mcp-server.instructions.md`).
- Project overview (`README.md`).