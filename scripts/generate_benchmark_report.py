from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / ".tmp" / "benchmarks" / "awesome-copilot-smoke.json"
DEFAULT_CURRENT = ROOT / ".tmp" / "benchmarks" / "awesome-copilot-report.json"
DEFAULT_OUTPUT = ROOT / ".tmp" / "benchmarks" / "awesome-copilot-perf-report.md"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate markdown benchmark report from baseline/current JSON outputs."
    )
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="Baseline benchmark JSON path")
    parser.add_argument("--current", default=str(DEFAULT_CURRENT), help="Current benchmark JSON path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output markdown report path")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pct_delta(baseline: float, current: float) -> float:
    if baseline == 0.0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


def _fmt_secs(value: float) -> str:
    return f"{value:.4f}"


def _fmt_pct(value: float) -> str:
    return f"{value:+.2f}%"


def _build_report(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    baseline_path: Path,
    current_path: Path,
) -> str:
    corpus = current.get("corpus", {})
    config = current.get("config", {})
    index_status = current.get("index_status", {})

    indexing_summary = current["indexing"]["summary"]
    indexing_runs = current["indexing"]["runs"]
    baseline_indexing_summary = baseline["indexing"]["summary"]
    baseline_indexing_runs = baseline["indexing"]["runs"]
    search_summary = current["search"]["summary_by_mode"]

    baseline_index_mean = float(baseline["indexing"]["summary"]["mean_s"])
    current_index_mean = float(indexing_summary["mean_s"])
    index_delta = _pct_delta(baseline_index_mean, current_index_mean)

    baseline_modes = baseline.get("search", {}).get("summary_by_mode", {})
    current_modes = current.get("search", {}).get("summary_by_mode", {})
    common_modes = sorted(set(baseline_modes) & set(current_modes))

    delta_lines: list[str] = [
        f"- **Indexing mean:** {_fmt_secs(baseline_index_mean)}s → {_fmt_secs(current_index_mean)}s (**{_fmt_pct(index_delta)}**)"
    ]
    for mode in common_modes:
        baseline_mean = float(baseline_modes[mode]["mean_s"])
        current_mean = float(current_modes[mode]["mean_s"])
        delta = _pct_delta(baseline_mean, current_mean)
        delta_lines.append(
            f"- **{mode.capitalize()} search mean:** {_fmt_secs(baseline_mean)}s → {_fmt_secs(current_mean)}s (**{_fmt_pct(delta)}**)"
        )

    mode_rows = []
    for mode in sorted(search_summary):
        summary = search_summary[mode]
        mode_rows.append(
            "| {mode} | {count:.0f} | {min_s:.4f} | {max_s:.4f} | {mean_s:.4f} | {median_s:.4f} | {p95_s:.4f} |".format(
                mode=mode,
                count=float(summary["count"]),
                min_s=float(summary["min_s"]),
                max_s=float(summary["max_s"]),
                mean_s=float(summary["mean_s"]),
                median_s=float(summary["median_s"]),
                p95_s=float(summary["p95_s"]),
            )
        )

    run_rows = []
    for run in indexing_runs:
        run_rows.append(
            "| {run} | {duration:.4f} | {indexed} | {skipped} | {deleted} |".format(
                run=int(run["run"]),
                duration=float(run["duration_s"]),
                indexed=int(run.get("indexed_files", 0)),
                skipped=int(run.get("skipped_files", 0)),
                deleted=int(run.get("deleted_files", 0)),
            )
        )

    baseline_run_rows = []
    for run in baseline_indexing_runs:
        baseline_run_rows.append(
            "| {run} | {duration:.4f} | {indexed} | {skipped} | {deleted} |".format(
                run=int(run["run"]),
                duration=float(run["duration_s"]),
                indexed=int(run.get("indexed_files", 0)),
                skipped=int(run.get("skipped_files", 0)),
                deleted=int(run.get("deleted_files", 0)),
            )
        )

    generated = current.get("timestamp_utc") or datetime.now(UTC).isoformat()
    report = f"""## Rifflux Performance Report

- **Generated (UTC):** {generated}
- **Corpus repo:** {corpus.get("repo_url", "n/a")}
- **Corpus commit:** `{corpus.get("repo_head", "n/a")}`
- **DB:** `{config.get("db_path", "n/a")}`

## Benchmark Configuration

- **Index runs:** {config.get("index_runs", "n/a")}
- **Query runs per query/mode:** {config.get("query_runs", "n/a")}
- **Modes:** {", ".join(config.get("modes", []))}
- **top_k:** {config.get("top_k", "n/a")}

## Corpus/Index State

- **Indexed files:** {index_status.get("files", "n/a")}
- **Chunks:** {index_status.get("chunks", "n/a")}
- **Embeddings:** {index_status.get("embeddings", "n/a")}
- **Embedding backend/model:** {index_status.get("embedding_backend", "n/a")} / {index_status.get("embedding_model", "n/a")}

## Indexing Performance (Cold vs Warm)

### Cold Baseline

| Metric | Value (s) |
|---|---:|
| min | {_fmt_secs(float(baseline_indexing_summary["min_s"]))} |
| max | {_fmt_secs(float(baseline_indexing_summary["max_s"]))} |
| mean | {_fmt_secs(float(baseline_indexing_summary["mean_s"]))} |
| median | {_fmt_secs(float(baseline_indexing_summary["median_s"]))} |
| p95 | {_fmt_secs(float(baseline_indexing_summary["p95_s"]))} |

Per-run details:

| Run | Duration (s) | Indexed | Skipped | Deleted |
|---:|---:|---:|---:|---:|
{chr(10).join(baseline_run_rows)}

### Warm Incremental Current

| Metric | Value (s) |
|---|---:|
| min | {_fmt_secs(float(indexing_summary["min_s"]))} |
| max | {_fmt_secs(float(indexing_summary["max_s"]))} |
| mean | {_fmt_secs(float(indexing_summary["mean_s"]))} |
| median | {_fmt_secs(float(indexing_summary["median_s"]))} |
| p95 | {_fmt_secs(float(indexing_summary["p95_s"]))} |

Per-run details:

| Run | Duration (s) | Indexed | Skipped | Deleted |
|---:|---:|---:|---:|---:|
{chr(10).join(run_rows)}

## Search Performance Summary

| Mode | Samples | Min (s) | Max (s) | Mean (s) | Median (s) | p95 (s) |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(mode_rows)}

## Baseline Comparison

Baseline file: `{baseline_path}`  
Current file: `{current_path}`

{chr(10).join(delta_lines)}
"""
    return report


def main() -> None:
    args = _parse_args()
    baseline_path = Path(args.baseline).resolve()
    current_path = Path(args.current).resolve()
    output_path = Path(args.output).resolve()

    baseline = _load_json(baseline_path)
    current = _load_json(current_path)
    report = _build_report(
        baseline,
        current,
        baseline_path=baseline_path,
        current_path=current_path,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report + "\n", encoding="utf-8")
    print(f"Wrote markdown report to {output_path}")


if __name__ == "__main__":
    main()
