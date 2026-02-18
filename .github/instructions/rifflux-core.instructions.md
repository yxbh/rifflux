---
description: 'Rifflux core architecture and retrieval constraints for Python local/offline hybrid search'
applyTo: '**/*.py, **/*.md, **/pyproject.toml, **/requirements*.txt, **/*.sql'
---

# Rifflux Core Constraints

- Keep retrieval core framework-agnostic; MCP transport must call core services, not contain ranking logic.
- Keep indexing deterministic and incremental (changed files only unless force rebuild).
- Preserve markdown semantics during chunking:
  - heading-aware section boundaries
  - fenced code blocks not split across chunks
  - heading breadcrumb stored with each chunk
- Generate stable chunk IDs from normalized relative path + chunk index.
- Implement lexical and semantic retrieval independently, then fuse via RRF.
- Never average raw BM25 and cosine scores directly.
- Return per-result metadata: `path`, `heading_path`, `chunk_index`, and score breakdown.
- Prefer SQLite-native capabilities first (FTS5, transactions, WAL).
- Use sqlite-vec where available; otherwise use embedding BLOB storage + in-process cosine fallback.
- Keep all public interfaces fully type-hinted and unit-test chunking/ranking logic.
