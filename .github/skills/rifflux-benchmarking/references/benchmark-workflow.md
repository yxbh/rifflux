## Benchmark Workflow Reference

### 1) Prepare or refresh corpus

Use this if the sample repo is missing or you want a fresh pull:

`python scripts/benchmark_awesome_copilot.py --prepare-only --refresh-repo`

### 2) Run benchmark

Recommended standard run:

`python scripts/benchmark_awesome_copilot.py --runs 3 --query-runs 5 --modes lexical hybrid semantic --top-k 10 --output .tmp/benchmarks/awesome-copilot-report.json`

Cold-start run (forces full reindex each run):

`python scripts/benchmark_awesome_copilot.py --runs 3 --query-runs 5 --modes lexical hybrid semantic --top-k 10 --force-reindex --output .tmp/benchmarks/awesome-copilot-report-cold.json`

### 3) Compare baseline vs current

`python scripts/compare_benchmarks.py .tmp/benchmarks/awesome-copilot-smoke.json .tmp/benchmarks/awesome-copilot-report.json --output .tmp/benchmarks/awesome-copilot-report-compare.json`

With thresholds:

`python scripts/compare_benchmarks.py .tmp/benchmarks/awesome-copilot-smoke.json .tmp/benchmarks/awesome-copilot-report.json --max-index-regression-pct 10 --max-search-regression-pct 15`

### 4) Report template checklist

Include these sections in markdown reports:

- Metadata: timestamp, corpus URL, corpus commit, DB path.
- Benchmark config: runs, modes, query set, top_k, force_reindex flag.
- Indexing summary: min/max/mean/median/p95 and per-run details.
- Search summary by mode: samples, min/max/mean/median/p95.
- Comparison deltas: baseline → current (% change).
- Notes: warm vs cold interpretation and known caveats.

### 5) Corpus stats add-on

Provide both views when needed:

- Overall repo composition (all files).
- Index-relevant subset based on Riflux include/exclude globs.

Store generated artifacts under `.tmp/benchmarks/` for consistency.
