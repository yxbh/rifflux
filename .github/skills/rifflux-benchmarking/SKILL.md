---
name: rifflux-benchmarking
description: Run and analyze Rifflux performance benchmarks using github/awesome-copilot as corpus data. Use when asked to measure indexing/search latency, compare baseline vs current benchmark outputs, generate markdown perf reports, or produce sample-repo size/file composition stats.
---

## Rifflux Benchmarking Skill

Use this skill to execute repeatable local performance checks for Rifflux.

## When to use this skill

- You need fresh indexing and query latency numbers.
- You need baseline-vs-current regression comparison.
- You need a report suitable for sharing in Markdown.
- You need corpus composition stats for the sampled `awesome-copilot` repo.

## Prerequisites

- Python virtual environment configured for this workspace.
- Repository root as current working directory.
- Git available to clone `github/awesome-copilot` if missing.

## Quick commands

- Benchmark run:
  - `python scripts/benchmark_awesome_copilot.py --runs 3 --query-runs 5 --modes lexical hybrid semantic --top-k 10 --output .tmp/benchmarks/awesome-copilot-report.json`
- Baseline comparison:
  - `python scripts/compare_benchmarks.py .tmp/benchmarks/awesome-copilot-smoke.json .tmp/benchmarks/awesome-copilot-report.json --output .tmp/benchmarks/awesome-copilot-report-compare.json`
- Build markdown report from benchmark JSON:
  - Summarize `.tmp/benchmarks/awesome-copilot-report.json` and `.tmp/benchmarks/awesome-copilot-report-compare.json` into a `.md` artifact under `.tmp/benchmarks/`.

## Workflow

1. Ensure corpus exists (run benchmark with `--refresh-repo` if needed).
2. Run benchmark with explicit `--output` path.
3. Compare against baseline using `compare_benchmarks.py`.
4. Produce a concise markdown report with:
   - corpus commit and config,
   - indexing summary,
   - per-mode search summary,
   - cold-vs-warm or baseline deltas.
5. Optionally add corpus stats (overall and index-relevant subsets).

For a detailed runbook, use [benchmark-workflow.md](./references/benchmark-workflow.md).
