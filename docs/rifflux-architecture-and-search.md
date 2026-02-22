## Rifflux Architecture and Search Mechanics

This document explains how Rifflux components fit together, how indexing
works, and why MCP-backed indexed search is usually faster and more
query-capable than running `grep` repeatedly.

## Big Picture

Rifflux separates retrieval logic from MCP transport:

- Core engine: chunking, indexing, lexical search, semantic search, RRF fusion.
- MCP layer: tool contracts, request handling, auto-reindex triggers, background
  orchestration.

```mermaid
flowchart LR
  Client[Agent or MCP Client] --> MCP["FastMCP Server<br/>rifflux.mcp.server/tools"]

  MCP --> SearchTool[search_rifflux]
  MCP --> ReindexTool[reindex / reindex_many]
  MCP --> StatusTool[index_status]
  MCP --> ReadTools[get_chunk / get_file]

  SearchTool --> SearchService["SearchService<br/>retrieval/search.py"]
  ReindexTool --> Indexer["Indexer<br/>indexing/indexer.py"]

  Indexer --> Chunker["Markdown Chunker<br/>indexing/chunker.py"]
  Indexer --> Embedder["Embedder Bundle<br/>embeddings/*"]
  Chunker --> DB[(SQLite: files/chunks/chunks_fts/embeddings)]
  Embedder --> DB

  SearchService --> Lexical["FTS5 BM25<br/>retrieval/lexical.py"]
  SearchService --> Semantic["Cosine Similarity<br/>retrieval/semantic.py"]
  Lexical --> DB
  Semantic --> DB
  SearchService --> RRF["RRF Fusion<br/>retrieval/rrf.py"]
  RRF --> SearchTool

  MCP --> BG["BackgroundIndexer + FileWatcher<br/>indexing/background.py + watcher.py"]
  BG --> ReindexTool
```

## Indexing Mechanism (Incremental and Deterministic)

Rifflux indexing is incremental by default and deterministic for chunk IDs.

### File-level change detection

For each candidate file under a source path:

- Apply include/exclude globs.
- Compare current `mtime_ns` + `size_bytes` with stored metadata.
- If metadata changed, compute `sha256`.
- If hash is unchanged, update metadata and skip re-chunk/re-embed.
- If hash changed (or `force=true`), re-chunk and re-embed.

This avoids unnecessary reprocessing when files are touched but content
did not change.

### Chunking rules

Markdown chunking uses AST parsing and preserves structure:

- Heading-aware section grouping (`heading_path` breadcrumbs).
- Fenced code blocks preserved as blocks.
- Chunk size bounded by `max_chunk_chars` with `min_chunk_chars` floor.
- Stable `chunk_id` from `sha256(normalized_relative_path::chunk_index)`.

### SQLite write path

- `files` stores per-file metadata.
- `chunks` stores chunk content and location metadata.
- `chunks_fts` is FTS5 external-content index on `chunks` via triggers.
- `embeddings` stores `vec` BLOB vectors per chunk.

```mermaid
flowchart TD
  Start[reindex path(s)] --> Scan[Scan files + glob filters]
  Scan --> StatCheck{"mtime+size<br/>changed?"}
  StatCheck -- no --> Skip1[Skip file]
  StatCheck -- yes --> Hash[Read bytes + sha256]
  Hash --> HashCheck{"sha256 changed?<br/>force?"}
  HashCheck -- no --> MetaOnly[Update file metadata only]
  HashCheck -- yes --> UpsertFile[Upsert files row]
  UpsertFile --> DeleteOld[Delete old chunks for file]
  DeleteOld --> Chunk[AST chunk markdown]
  Chunk --> InsertChunk[Insert chunks rows]
  InsertChunk --> Embed[Embed each chunk]
  Embed --> InsertVec[Upsert embeddings vec]
  InsertVec --> Commit[Commit transaction]
```

## Query Path (What Happens on `search_rifflux`)

`search_rifflux` initializes schema/runtime safely, optionally starts
auto-reindex or watcher behavior, then executes retrieval.

In hybrid mode:

1. Run lexical retrieval with FTS5/BM25 (`top_k * 2` candidates).
2. Embed query and run semantic cosine retrieval (`top_k * 2` candidates).
3. Fuse by Reciprocal Rank Fusion (RRF), not raw score averaging.
4. Return ranked chunks with score breakdown and metadata.

```mermaid
sequenceDiagram
  participant C as MCP Client
  participant M as tools.search_rifflux
  participant S as SearchService
  participant DB as SQLite

  C->>M: search_rifflux(query, top_k, mode)
  M->>M: ensure schema + runtime caches
  M->>M: maybe auto-reindex (background)
  M->>M: maybe start file watcher
  M->>S: search(query)

  par Lexical branch
    S->>DB: FTS5 MATCH + BM25
    DB-->>S: lexical candidates
  and Semantic branch
    S->>S: embed query
    S->>DB: read embeddings
    S->>S: cosine scores
  end

  S->>S: RRF fuse(lexical ranks, semantic ranks)
  S-->>M: fused results + score_breakdown
  M-->>C: {query, mode, results, auto_reindex}
```

## MCP Indexed Search vs `grep`

### Why indexed search can be faster for repeated queries

`grep` behavior is generally:

- Per query: read many files from disk and scan text linearly.
- No persistent semantic index.
- Good for exact/pattern text match, especially one-off lookups.

Rifflux via MCP is generally:

- Upfront indexing cost once (or incrementally on changes).
- Query-time lookup over prebuilt FTS and embedding tables.
- Reuses cached DB structures across many queries.
- Supports semantic ranking and hybrid fusion.

For many queries over mostly stable content, amortized cost tends to favor
indexed retrieval.

### Capability comparison

| Dimension | `grep` | Rifflux MCP search |
|---|---|---|
| Exact term lookup | Strong | Strong (FTS lexical mode) |
| Semantic similarity | No | Yes (semantic mode) |
| Hybrid lexical + semantic | No | Yes (RRF fusion) |
| Structured metadata (`path`, heading, chunk index) | Limited/manual | Native in results |
| Incremental update support | N/A | Yes (mtime/size/hash pipeline) |
| Background refresh | No | Yes (auto-reindex + watcher) |

### Practical rule of thumb

- Use `grep` for fast ad-hoc literal regex checks.
- Use Rifflux MCP tools for repeated exploration, ranking quality,
  and semantic/hybrid retrieval.

## Background Indexing and Watcher Resilience

Rifflux includes operational mechanisms that help search stay fresh without
blocking interactive calls:

- `BackgroundIndexer` runs queued reindex jobs sequentially.
- Transient SQLite lock/busy errors retry up to 3 times with exponential backoff.
- `FileWatcher` can auto-submit reindex jobs on relevant file changes.
- Watcher auto-restarts on transient crashes (up to configured cap).
- `index_status` reports job and watcher state.

### Background job lifecycle

```mermaid
stateDiagram-v2
  [*] --> queued: submit(reindex background)
  queued --> running: worker picks next job
  running --> completed: reindex succeeds
  running --> retry_wait: transient SQLite lock/busy
  retry_wait --> running: backoff elapsed (1s/2s/4s)
  running --> failed: permanent error or retries exhausted
  queued --> failed: shutdown cancels pending jobs
  retry_wait --> failed: shutdown during retry wait
  completed --> [*]
  failed --> [*]
```

### File watcher event path

```mermaid
flowchart TD
  FS[Filesystem events] --> Debounce[watchfiles debounce]
  Debounce --> Filter["Apply include/exclude globs<br/>(path normalized + watch-root-relative)"]
  Filter --> Relevant{Relevant changes?}
  Relevant -- no --> Drop[Ignore batch]
  Relevant -- yes --> Pending{"Matching reindex job<br/>already queued/running?"}
  Pending -- yes --> Coalesce["Coalesce burst<br/>(skip redundant submit)"]
  Pending -- no --> Submit[Submit one background reindex job]
  Submit --> Queue[BackgroundIndexer queue]
```

### Shutdown sequence

```mermaid
sequenceDiagram
  participant Exit as Process Exit
  participant Tools as mcp.tools atexit
  participant Watcher as FileWatcher
  participant BG as BackgroundIndexer

  Exit->>Tools: _shutdown_server()
  Tools->>Watcher: stop()
  Note over Watcher: Prevent new job submissions
  Tools->>BG: shutdown(timeout)
  Note over BG: Mark terminal shutdown state
  Note over BG: Cancel queued jobs
  Note over BG: Let running job finish or fail
  BG-->>Tools: shutdown complete
```

## Embedding Backend Decision (Pros/Cons)

Rifflux uses ONNX as the primary semantic path, with `auto` runtime default
(`onnx` first, deterministic `hash` fallback) to keep environments resilient.

For full rationale, alternatives considered, and explicit pros/cons
comparisons, see `docs/embedding-backend-decision.md`.

## Where to Look in Code

- MCP tools and orchestration: `src/rifflux/mcp/tools.py`
- Indexing pipeline: `src/rifflux/indexing/indexer.py`
- Markdown chunking: `src/rifflux/indexing/chunker.py`
- Background queue and retry: `src/rifflux/indexing/background.py`
- File watcher: `src/rifflux/indexing/watcher.py`
- Search orchestration: `src/rifflux/retrieval/search.py`
- SQLite operations: `src/rifflux/db/sqlite_store.py`
- Schema (tables, FTS, triggers): `src/rifflux/db/schema.sql`
