# Rifflux project instructions

Rifflux is a local/offline retrieval project focused on hybrid search over files and markdown content.

## Product goals
- Fast local lookup using lexical + semantic retrieval.
- No cloud dependency required for indexing/search.
- Expose retrieval via MCP tools for agent workflows.

## Primary stack
- Language: Python 3.11+
- Markdown parsing/chunking: mistune (AST-based)
- Storage: SQLite + FTS5
- Vector path: sqlite-vec where available; fallback to stored embedding blobs + in-process cosine
- MCP framework: Python MCP SDK (FastMCP)

## Architecture constraints
- Keep core retrieval engine separate from MCP transport layer.
- Keep indexing pipeline deterministic and incremental.
- Use stable chunk IDs derived from normalized path + chunk index.
- Preserve heading breadcrumbs and fenced code block boundaries in markdown chunking.

## Retrieval requirements
- Implement lexical (FTS5/BM25) and semantic search independently.
- Fuse rankings with Reciprocal Rank Fusion (RRF) instead of raw-score averaging.
- Return source metadata: file path, heading path, chunk index, score breakdown.

## Code quality
- Strong type hints for all public functions.
- Prefer small pure functions for tokenization/chunking/ranking.
- Avoid introducing cloud-only dependencies.
- Add tests for chunking edge cases and ranking fusion behavior.

## MCP tool surface (target)
- `search_rifflux(query, top_k, mode?)`
- `get_chunk(chunk_id)`
- `get_file(path)`
- `index_status()`
- `reindex(path?, force?)`

## Operational defaults
- Optimize for local corpora from hundreds to low tens-of-thousands of chunks.
- Favor clear, explainable ranking behavior over opaque heuristics.
- Keep output concise and machine-friendly for downstream agents.
