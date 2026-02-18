from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rifflux.mcp.tools import index_status, reindex, search_rifflux  # noqa: E402


DEFAULT_REPO_URL = "https://github.com/github/awesome-copilot.git"
DEFAULT_REPO_DIR = ROOT / ".tmp" / "benchmarks" / "awesome-copilot"
DEFAULT_DB_PATH = ROOT / ".tmp" / "benchmarks" / "awesome-copilot-rifflux.db"
DEFAULT_QUERIES = [
    "custom instructions",
    "agent skills",
    "mcp server",
    "prompt files",
    "vscode settings",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark Rifflux indexing and retrieval performance using "
            "github/awesome-copilot as sample data."
        )
    )
    parser.add_argument(
        "--repo-url",
        default=DEFAULT_REPO_URL,
        help="Git URL for the benchmark corpus repository.",
    )
    parser.add_argument(
        "--repo-dir",
        default=str(DEFAULT_REPO_DIR),
        help="Local directory for the benchmark corpus checkout.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite DB path used for benchmark indexing/search.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of indexing benchmark runs.",
    )
    parser.add_argument(
        "--query-runs",
        type=int,
        default=5,
        help="Number of repeated runs per query+mode pair.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="top_k used for search benchmark calls.",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["lexical", "semantic", "hybrid"],
        default=["lexical", "hybrid", "semantic"],
        help="Search modes to benchmark.",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        default=None,
        help="Query to benchmark (repeat for multiple).",
    )
    parser.add_argument(
        "--refresh-repo",
        action="store_true",
        help="Delete and re-clone the corpus repository before benchmark.",
    )
    parser.add_argument(
        "--force-reindex",
        action="store_true",
        help="Force full reindex for each indexing run.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Only clone/update corpus and exit (no benchmark execution).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional file path to write JSON benchmark output.",
    )
    return parser.parse_args()


def _run_command(args: list[str], *, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip()


def _ensure_repo(repo_url: str, repo_dir: Path, *, refresh_repo: bool) -> None:
    if refresh_repo and repo_dir.exists():
        shutil.rmtree(repo_dir)

    if (repo_dir / ".git").exists():
        return

    if repo_dir.exists() and any(repo_dir.iterdir()):
        raise RuntimeError(
            f"Repository directory exists and is not empty: {repo_dir}. "
            "Use --refresh-repo to recreate it."
        )

    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    _run_command(["git", "clone", "--depth", "1", repo_url, str(repo_dir)])


def _repo_head(repo_dir: Path) -> str | None:
    try:
        return _run_command(["git", "rev-parse", "HEAD"], cwd=repo_dir)
    except Exception:
        return None


def _timed_call(func, /, *args, **kwargs) -> tuple[Any, float]:
    start = time.perf_counter()
    result = func(*args, **kwargs)
    duration_s = time.perf_counter() - start
    return result, duration_s


def _summarize_timings(values: Iterable[float]) -> dict[str, float]:
    samples = list(values)
    if not samples:
        return {
            "count": 0,
            "min_s": 0.0,
            "max_s": 0.0,
            "mean_s": 0.0,
            "median_s": 0.0,
            "p95_s": 0.0,
        }

    ordered = sorted(samples)
    idx_95 = int((len(ordered) - 1) * 0.95)
    return {
        "count": float(len(samples)),
        "min_s": min(samples),
        "max_s": max(samples),
        "mean_s": statistics.fmean(samples),
        "median_s": statistics.median(samples),
        "p95_s": ordered[idx_95],
    }


def main() -> None:
    args = _parse_args()

    repo_dir = Path(args.repo_dir).resolve()
    db_path = Path(args.db).resolve()
    queries = args.queries if args.queries else list(DEFAULT_QUERIES)

    _ensure_repo(args.repo_url, repo_dir, refresh_repo=args.refresh_repo)
    if args.prepare_only:
        print(
            json.dumps(
                {
                    "prepared": True,
                    "repo_dir": str(repo_dir),
                    "repo_head": _repo_head(repo_dir),
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                },
                indent=2,
            )
        )
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)

    index_runs: list[dict[str, Any]] = []
    index_timings: list[float] = []
    for run_no in range(1, args.runs + 1):
        result, duration_s = _timed_call(
            reindex,
            db_path=db_path,
            source_path=repo_dir,
            force=args.force_reindex,
            prune_missing=True,
        )
        index_timings.append(duration_s)
        index_runs.append(
            {
                "run": run_no,
                "duration_s": duration_s,
                "indexed_files": int(result.get("indexed_files", 0)),
                "skipped_files": int(result.get("skipped_files", 0)),
                "deleted_files": int(result.get("deleted_files", 0)),
            }
        )

    search_runs: list[dict[str, Any]] = []
    search_timings_by_mode: dict[str, list[float]] = {mode: [] for mode in args.modes}
    for mode in args.modes:
        for query in queries:
            for run_no in range(1, args.query_runs + 1):
                result, duration_s = _timed_call(
                    search_rifflux,
                    db_path=db_path,
                    query=query,
                    top_k=args.top_k,
                    mode=mode,
                )
                search_timings_by_mode[mode].append(duration_s)
                search_runs.append(
                    {
                        "mode": mode,
                        "query": query,
                        "run": run_no,
                        "duration_s": duration_s,
                        "result_count": int(result.get("count", 0)),
                    }
                )

    status = index_status(db_path=db_path)
    output: dict[str, Any] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "corpus": {
            "repo_url": args.repo_url,
            "repo_dir": str(repo_dir),
            "repo_head": _repo_head(repo_dir),
        },
        "config": {
            "db_path": str(db_path),
            "index_runs": args.runs,
            "force_reindex": bool(args.force_reindex),
            "query_runs": args.query_runs,
            "top_k": args.top_k,
            "modes": args.modes,
            "queries": queries,
        },
        "indexing": {
            "runs": index_runs,
            "summary": _summarize_timings(index_timings),
        },
        "search": {
            "runs": search_runs,
            "summary_by_mode": {
                mode: _summarize_timings(timings)
                for mode, timings in search_timings_by_mode.items()
            },
        },
        "index_status": status,
    }

    text = json.dumps(output, indent=2)
    print(text)

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()