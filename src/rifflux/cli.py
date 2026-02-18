from __future__ import annotations

import argparse
import json
from pathlib import Path

from rifflux.config import RiffluxConfig
from rifflux.mcp.tools import reindex, search_rifflux


def _reindex_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reindex markdown files into rifflux SQLite store."
    )
    parser.add_argument("--path", default=".", help="Root path to scan for markdown files")
    parser.add_argument("--db", default=None, help="Optional DB path override")
    parser.add_argument("--force", action="store_true", help="Force reindex of all files")
    return parser


def _query_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query rifflux hybrid retrieval index.")
    parser.add_argument("query", help="Search text")
    parser.add_argument(
        "--mode",
        default="hybrid",
        choices=["hybrid", "lexical", "semantic"],
        help="Search mode",
    )
    parser.add_argument("--top-k", type=int, default=10, help="Number of results")
    parser.add_argument("--db", default=None, help="Optional DB path override")
    return parser


def _rebuild_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild rifflux SQLite store by deleting DB and force reindexing markdown files."
    )
    parser.add_argument("--path", default=".", help="Root path to scan for markdown files")
    parser.add_argument("--db", default=None, help="Optional DB path override")
    return parser


def reindex_main() -> None:
    args = _reindex_parser().parse_args()
    db_path = Path(args.db) if args.db else None
    source_path = Path(args.path).resolve()
    result = reindex(db_path=db_path, source_path=source_path, force=args.force)
    print(json.dumps(result, indent=2))


def query_main() -> None:
    args = _query_parser().parse_args()
    db_path = Path(args.db) if args.db else None
    result = search_rifflux(
        db_path=db_path,
        query=args.query,
        top_k=args.top_k,
        mode=args.mode,
    )
    print(json.dumps(result, indent=2))


def rebuild_main() -> None:
    args = _rebuild_parser().parse_args()
    source_path = Path(args.path).resolve()

    if args.db:
        db_path = Path(args.db)
    else:
        db_path = RiffluxConfig.from_env().db_path

    deleted_existing_db = False
    if db_path.exists():
        db_path.unlink()
        deleted_existing_db = True

    result = reindex(db_path=db_path, source_path=source_path, force=True)
    payload = {
        "rebuilt_db_path": str(db_path),
        "deleted_existing_db": deleted_existing_db,
        **result,
    }
    print(json.dumps(payload, indent=2))
