from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two Rifflux benchmark JSON files and report timing deltas "
            "(current vs baseline)."
        )
    )
    parser.add_argument("baseline", help="Path to baseline benchmark JSON.")
    parser.add_argument("current", help="Path to current benchmark JSON.")
    parser.add_argument(
        "--max-index-regression-pct",
        type=float,
        default=None,
        help=(
            "Fail if indexing mean time regression exceeds this percent "
            "(positive delta only)."
        ),
    )
    parser.add_argument(
        "--max-search-regression-pct",
        type=float,
        default=None,
        help=(
            "Fail if any mode's search mean time regression exceeds this percent "
            "(positive delta only)."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional file path to write JSON comparison output.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_nested_number(data: dict[str, Any], keys: list[str]) -> float:
    cursor: Any = data
    for key in keys:
        cursor = cursor[key]
    return float(cursor)


def _pct_delta(baseline: float, current: float) -> float:
    if baseline == 0.0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


def _format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def main() -> None:
    args = _parse_args()
    baseline_path = Path(args.baseline).resolve()
    current_path = Path(args.current).resolve()

    baseline = _load_json(baseline_path)
    current = _load_json(current_path)

    baseline_index_mean = _get_nested_number(
        baseline, ["indexing", "summary", "mean_s"]
    )
    current_index_mean = _get_nested_number(
        current, ["indexing", "summary", "mean_s"]
    )
    index_delta_pct = _pct_delta(baseline_index_mean, current_index_mean)

    baseline_modes = baseline.get("search", {}).get("summary_by_mode", {})
    current_modes = current.get("search", {}).get("summary_by_mode", {})
    common_modes = sorted(set(baseline_modes) & set(current_modes))

    search_mode_deltas: dict[str, dict[str, float]] = {}
    for mode in common_modes:
        baseline_mean = float(baseline_modes[mode]["mean_s"])
        current_mean = float(current_modes[mode]["mean_s"])
        search_mode_deltas[mode] = {
            "baseline_mean_s": baseline_mean,
            "current_mean_s": current_mean,
            "delta_pct": _pct_delta(baseline_mean, current_mean),
        }

    violations: list[str] = []
    if args.max_index_regression_pct is not None:
        if index_delta_pct > args.max_index_regression_pct:
            violations.append(
                "indexing mean regression "
                f"{_format_pct(index_delta_pct)} exceeds "
                f"{args.max_index_regression_pct:.2f}%"
            )

    if args.max_search_regression_pct is not None:
        for mode, details in search_mode_deltas.items():
            if details["delta_pct"] > args.max_search_regression_pct:
                violations.append(
                    f"search mean regression for mode '{mode}' "
                    f"{_format_pct(details['delta_pct'])} exceeds "
                    f"{args.max_search_regression_pct:.2f}%"
                )

    comparison = {
        "baseline": str(baseline_path),
        "current": str(current_path),
        "indexing": {
            "baseline_mean_s": baseline_index_mean,
            "current_mean_s": current_index_mean,
            "delta_pct": index_delta_pct,
        },
        "search": {
            "common_modes": common_modes,
            "summary_by_mode": search_mode_deltas,
        },
        "violations": violations,
        "pass": not violations,
    }

    print(
        f"Indexing mean: {baseline_index_mean:.4f}s -> {current_index_mean:.4f}s "
        f"({_format_pct(index_delta_pct)})"
    )
    for mode in common_modes:
        details = search_mode_deltas[mode]
        print(
            f"Search[{mode}] mean: {details['baseline_mean_s']:.4f}s -> "
            f"{details['current_mean_s']:.4f}s "
            f"({_format_pct(details['delta_pct'])})"
        )

    if violations:
        print("\nThreshold violations:")
        for item in violations:
            print(f"- {item}")
    else:
        print("\nNo threshold violations.")

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")

    if violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()