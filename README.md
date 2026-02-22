# rifflux

Rifflux is a local/offline retrieval engine for markdown and file content with hybrid search:

- lexical search via SQLite FTS5/BM25
- semantic search via local embeddings
- score fusion via Reciprocal Rank Fusion (RRF)
- MCP tool surface for agent workflows

## Architecture docs

- [Rifflux architecture, indexing flow, and MCP-vs-grep comparison](docs/rifflux-architecture-and-search.md)
- [Fresh quantitative benchmark: MCP indexed search vs grep-style scan](docs/mcp-vs-grep-benchmark.md)
- [Embedding backend decision record (why ONNX, alternatives, trade-offs)](docs/embedding-backend-decision.md)

## Status

Core retrieval engine with deterministic chunking, incremental indexing, hybrid search (lexical + semantic + RRF), background indexing with retry, file watching, and MCP tool surface.

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
- `RIFLUX_FILE_WATCHER=0|1` (default `0`)
- `RIFLUX_FILE_WATCHER_PATHS=` (comma-separated directories to watch; required when watcher is enabled)
- `RIFLUX_FILE_WATCHER_DEBOUNCE_MS=500` (minimum ms between FS event batches)

### Environment variables reference

| Variable | What it controls | Default | Example value |
|---|---|---|---|
| `RIFLUX_EMBEDDING_BACKEND` | Embedding backend strategy (`auto`, `onnx`, `hash`) | `auto` | `onnx` |
| `RIFLUX_EMBEDDING_MODEL` | Preferred model label used by ONNX-capable path | `BAAI/bge-small-en-v1.5` | `BAAI/bge-small-en-v1.5` |
| `RIFLUX_EMBEDDING_DIM` | Embedding vector dimension expected by runtime/store | `384` | `384` |
| `RIFLUX_DB_PATH` | SQLite DB file location for index and embeddings | `.tmp/riflux/riflux.db` | `.tmp/riflux/my-index.db` |
| `RIFLUX_INDEX_INCLUDE_GLOBS` | Comma-separated file patterns to include in indexing | `*.md` | `*.md,*.txt` |
| `RIFLUX_INDEX_EXCLUDE_GLOBS` | Comma-separated file patterns to exclude from indexing | `.git/*,.venv/*,**/__pycache__/*,**/.pytest_cache/*,**/.ruff_cache/*,**/node_modules/*` | `.git/*,.venv/*,**/node_modules/*,build/*` |
| `RIFLUX_AUTO_REINDEX_ON_SEARCH` | Whether search calls trigger incremental background refresh | `0` | `1` |
| `RIFLUX_AUTO_REINDEX_PATHS` | Paths scanned when auto-reindex on search is enabled | `.` | `docs,notes` |
| `RIFLUX_AUTO_REINDEX_MIN_INTERVAL_SECONDS` | Minimum seconds between auto-reindex runs per DB | `2.0` | `10.0` |
| `RIFLUX_FILE_WATCHER` | Whether filesystem watcher integration is enabled | `0` | `1` |
| `RIFLUX_FILE_WATCHER_PATHS` | Comma-separated directories monitored by watcher | empty | `docs,knowledge-base` |
| `RIFLUX_FILE_WATCHER_DEBOUNCE_MS` | Event debounce window before watcher emits a batch | `500` | `750` |
| `RIFLUX_LOG_LEVEL` | Logging verbosity for CLI and MCP server | `WARNING` | `DEBUG` |

### Example configurations

Minimal deterministic local setup (hash backend):

```bash
RIFLUX_EMBEDDING_BACKEND=hash
RIFLUX_DB_PATH=.tmp/riflux/riflux.db
RIFLUX_LOG_LEVEL=INFO
```

Higher-quality semantic setup (ONNX preferred):

```bash
RIFLUX_EMBEDDING_BACKEND=onnx
RIFLUX_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RIFLUX_DB_PATH=.tmp/riflux/riflux.db
RIFLUX_LOG_LEVEL=INFO
```

Auto-refresh + watcher setup for active docs workspace:

```bash
RIFLUX_EMBEDDING_BACKEND=auto
RIFLUX_AUTO_REINDEX_ON_SEARCH=1
RIFLUX_AUTO_REINDEX_PATHS=docs,notes
RIFLUX_FILE_WATCHER=1
RIFLUX_FILE_WATCHER_PATHS=docs,notes
RIFLUX_FILE_WATCHER_DEBOUNCE_MS=500
RIFLUX_LOG_LEVEL=DEBUG
```

Behavior:

- `hash`: deterministic local hash embedder only
- `onnx`: ONNX-capable embedder path via optional dependency, falls back to hash if unavailable
- `auto`: try ONNX path first, then hash fallback
- indexing scope: include/exclude globs are applied by the MCP server during reindex
- optional live refresh: if `RIFLUX_AUTO_REINDEX_ON_SEARCH=1`, each search performs incremental reindex over `RIFLUX_AUTO_REINDEX_PATHS` (throttled by `RIFLUX_AUTO_REINDEX_MIN_INTERVAL_SECONDS`)

### Embedding model choice

For rationale and comparisons (including why ONNX is the primary semantic
path and what alternatives were considered), see
`docs/embedding-backend-decision.md`.

Quick operational defaults:

- `auto`: recommended default for mixed/dev environments.
- `onnx`: preferred when semantic quality is a priority and setup is controlled.
- `hash`: preferred for deterministic CI/minimal-setup workflows.

File watcher:

- When `RIFLUX_FILE_WATCHER=1` and `RIFLUX_FILE_WATCHER_PATHS` is set, Riflux monitors those paths for file changes and automatically triggers background reindex.
- The watcher uses `watchfiles` (Rust-backed, cross-platform). Install with `pip install -e .[watch]` or `pip install -e .[dev]`.
- Only files matching `RIFLUX_INDEX_INCLUDE_GLOBS` (and not excluded) trigger reindex jobs.
- The watcher auto-restarts on transient OS errors (up to 5 consecutive crashes with exponential backoff).
- The watcher starts lazily on the first search call, not at server startup.

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

## Background indexing and resilience

Reindex jobs submitted via `background: true` or triggered by auto-reindex / file watcher run in a single sequential background thread.

- **Retry on transient errors**: If a job fails with a transient SQLite error (`database is locked`, `database is busy`), it is retried up to 3 times with exponential backoff (1s, 2s, 4s). Non-transient errors fail immediately.
- **Graceful shutdown**: On process exit (including VS Code killing the MCP server), `atexit` cleanup stops the file watcher, cancels queued jobs, and waits for any running job to finish.
- **Job status**: `index_status` returns all background job details including `retries` count and `crash_restarts` from the file watcher.

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

## Debug logging

Rifflux emits structured debug logs via Python `logging` under these loggers:

- `rifflux.mcp.tools` — tool call entry/exit with wall-clock timing, embedder resolution, schema init
- `rifflux.indexing` — file scan counts, per-file skip/index decisions, chunk+embed timing
- `rifflux.retrieval` — lexical/semantic/embed phase durations and hit counts

Set `RIFLUX_LOG_LEVEL` to control verbosity:

- `RIFLUX_LOG_LEVEL=DEBUG` — full timing and decision traces (recommended for diagnosing slow tool calls)
- `RIFLUX_LOG_LEVEL=INFO` — high-level summaries only
- `RIFLUX_LOG_LEVEL=WARNING` — default, silent unless something is wrong

Example output at `DEBUG` level:

```
10:42:01 rifflux.mcp.tools DEBUG search_rifflux start query='cache ttl' top_k=3 mode=hybrid
10:42:01 rifflux.retrieval DEBUG search phases: lexical=0.001s (2 hits) embed=0.000s semantic=0.003s (5 hits)
10:42:01 rifflux.mcp.tools DEBUG search_rifflux done in 0.005s count=3
```

For VS Code MCP server usage, add to `.vscode/mcp.json` env:

```json
"RIFLUX_LOG_LEVEL": "DEBUG"
```

For CLI usage:

```bash
RIFLUX_LOG_LEVEL=DEBUG rifflux-query "cache ttl" --mode hybrid
```

## Troubleshooting

- If search or reindex fails with SQL errors like `no such column: vec` or FTS mismatch errors, rebuild the DB schema and reindex:
   - `rifflux-rebuild --path . --db .tmp/rifflux/rifflux.db`
- If background reindex jobs fail with `database is locked`, they are automatically retried (up to 3 times). Check `index_status` for job details and retry counts.
- If the file watcher stops unexpectedly, it auto-restarts with backoff. After 5 consecutive crashes it gives up — check logs at `RIFLUX_LOG_LEVEL=DEBUG`.
