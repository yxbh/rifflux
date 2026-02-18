# rifflux

Rifflux is a local/offline retrieval engine for markdown and file content with hybrid search:

- lexical search via SQLite FTS5/BM25
- semantic search via local embeddings
- score fusion via Reciprocal Rank Fusion (RRF)
- MCP tool surface for agent workflows

## Status

Starter scaffold is in place with deterministic chunking, indexing, hybrid retrieval, and MCP tool wiring.

## Quick start

1. Create environment and install:
   - `python -m venv .venv`
   - `.venv\\Scripts\\activate`
   - `pip install -e .[dev]`
2. Build index with your own script using `rifflux.indexing.indexer.Indexer`
3. Run MCP server:
   - `python -m rifflux.mcp.server`

### Local CLI helpers

- Reindex markdown under current folder:
   - `python scripts/reindex.py --path .`
   - `rifflux-reindex --path .`
- Query hybrid search:
   - `python scripts/query.py "cache ttl" --mode hybrid --top-k 5`
   - `rifflux-query "cache ttl" --mode hybrid --top-k 5`
- Rebuild DB after schema changes (delete DB + force reindex):
   - `python scripts/rebuild.py --path . --db .tmp/rifflux/rifflux.db`
   - `rifflux-rebuild --path . --db .tmp/rifflux/rifflux.db`
- Benchmark indexing/search with `github/awesome-copilot` sample corpus:
   - `python scripts/benchmark_awesome_copilot.py --runs 3 --query-runs 5`
   - `python scripts/benchmark_awesome_copilot.py --refresh-repo --output .tmp/benchmarks/awesome-copilot.json`
- Compare benchmark runs (baseline vs current):
   - `python scripts/compare_benchmarks.py .tmp/benchmarks/baseline.json .tmp/benchmarks/current.json`
   - `python scripts/compare_benchmarks.py .tmp/benchmarks/baseline.json .tmp/benchmarks/current.json --max-index-regression-pct 10 --max-search-regression-pct 15`
- Generate markdown benchmark report from baseline + current JSON (one command):
   - `python scripts/generate_benchmark_report.py`
   - `python scripts/generate_benchmark_report.py --baseline .tmp/benchmarks/awesome-copilot-smoke.json --current .tmp/benchmarks/awesome-copilot-report.json --output .tmp/benchmarks/awesome-copilot-perf-report.md`
- Inspect MCP `list_tools` metadata (descriptions + schemas):
   - `python scripts/inspect_mcp_tools.py --pretty`
   - `python scripts/inspect_mcp_tools.py --pretty --output .tmp/mcp-tools.json`

## Embedding backend toggle

Rifflux supports a configurable embedding backend via environment variables:

- `RIFLUX_EMBEDDING_BACKEND=auto|onnx|hash` (default `auto`)
- `RIFLUX_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`
- `RIFLUX_EMBEDDING_DIM=384`
- `RIFLUX_DB_PATH=.tmp/rifflux/rifflux.db`
- `RIFLUX_INDEX_INCLUDE_GLOBS=*.md` (comma-separated)
- `RIFLUX_INDEX_EXCLUDE_GLOBS=.git/*,.venv/*,**/__pycache__/*,**/.pytest_cache/*,**/.ruff_cache/*,**/node_modules/*` (comma-separated)
- `RIFLUX_AUTO_REINDEX_ON_SEARCH=0|1` (default `0`)
- `RIFLUX_AUTO_REINDEX_PATHS=.` (comma-separated paths)
- `RIFLUX_AUTO_REINDEX_MIN_INTERVAL_SECONDS=2.0`

Behavior:

- `hash`: deterministic local hash embedder only
- `onnx`: ONNX-capable embedder path via optional dependency, falls back to hash if unavailable
- `auto`: try ONNX path first, then hash fallback
- indexing scope: include/exclude globs are applied by the MCP server during reindex
- optional live refresh: if `RIFLUX_AUTO_REINDEX_ON_SEARCH=1`, each search performs incremental reindex over `RIFLUX_AUTO_REINDEX_PATHS` (throttled by `RIFLUX_AUTO_REINDEX_MIN_INTERVAL_SECONDS`)

Schema-change policy:

- On DB schema changes, use a full rebuild of the target DB file (delete/recreate + reindex).
- Incremental reindex is for content changes only, not structural migrations of existing DB files.

Default DB location:

- If `RIFLUX_DB_PATH` is not set, Rifflux uses `.tmp/rifflux/rifflux.db`.
- The `.tmp/` folder is git-ignored by default.

## Running as an MCP server

Rifflux MCP defaults are environment-variable driven.

- Preferred configuration surface: environment variables (especially when launched by MCP hosts).
- If `RIFLUX_DB_PATH` is omitted, DB files are created under `.tmp/rifflux/`.
- Relative paths are resolved from the MCP server process working directory.

Example environment setup:

- `RIFLUX_DB_PATH=.tmp/rifflux/rifflux.db`
- `RIFLUX_EMBEDDING_BACKEND=auto`
- `RIFLUX_AUTO_REINDEX_ON_SEARCH=0`

Tip:

- Use an absolute `RIFLUX_DB_PATH` if your MCP host runs from a different working directory than expected.

To enable ONNX-capable backend support:

- `pip install -e .[onnx]`

## Layout

- `src/rifflux/indexing`: markdown chunking + incremental indexing
- `src/rifflux/retrieval`: lexical, semantic, RRF, orchestrated search
- `src/rifflux/db`: SQLite schema and storage operations
- `src/rifflux/mcp`: FastMCP server and tools

## MCP reindex tool arguments

`reindex` supports both a single input location and multiple input locations.

- Single input location (backward compatible):

```json
{
   "path": "./docs",
   "force": false
}
```

- Multiple input locations:

```json
{
   "paths": ["./docs", "./notes", "./knowledge-base"],
   "force": true,
   "prune_missing": true
}
```

Behavior notes:

- If `paths` is provided and non-empty, it is used.
- If `paths` is omitted, `path` is used.
- If both are omitted, indexing defaults to the server current working directory.
- Reindex is progressive: unchanged files are skipped, changed files are re-chunked/re-embedded.
- `prune_missing` (default `true`) controls whether missing files are pruned (`deleted_files`).
- Git fingerprint metadata is stored when a scanned path is inside a Git worktree.

## MCP tool schema hints

Rifflux MCP tools expose descriptions and argument metadata so clients (including VS Code) can present richer tool guidance.

- `search_rifflux`
   - `query`: natural-language search query
   - `top_k`: integer, minimum `1`, maximum `100`, default `10`
   - `mode`: enum `lexical | semantic | hybrid` (default `hybrid`)
- `get_chunk`
   - `chunk_id`: stable chunk identifier
- `get_file`
   - `path`: indexed source file path
- `index_status`
   - no arguments
- `reindex`
   - `path`: optional single source location
   - `paths`: optional list of source locations
   - `force`: optional boolean rebuild flag
   - `prune_missing`: optional boolean stale-file prune toggle (default `true`)
   - response includes `deleted_files` and `git_fingerprint`

## Troubleshooting

- If search or reindex fails with SQL errors like `no such column: vec` or FTS mismatch errors, rebuild the DB schema and reindex:
   - `rifflux-rebuild --path . --db .tmp/rifflux/rifflux.db`
