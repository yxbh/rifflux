from __future__ import annotations

import argparse
import json
from pathlib import Path

from rifflux import cli


def test_reindex_parser_defaults() -> None:
    parser = cli._reindex_parser()

    args = parser.parse_args([])

    assert args.path == "."
    assert args.db is None
    assert args.force is False


def test_query_parser_defaults_and_choices() -> None:
    parser = cli._query_parser()

    args = parser.parse_args(["hello"])

    assert args.query == "hello"
    assert args.mode == "hybrid"
    assert args.top_k == 10
    assert args.db is None


def test_rebuild_parser_defaults() -> None:
    parser = cli._rebuild_parser()

    args = parser.parse_args([])

    assert args.path == "."
    assert args.db is None


def test_reindex_main_invokes_tool_and_prints_json(monkeypatch, capsys, tmp_path: Path) -> None:
    expected_db = tmp_path / "rifflux.db"
    source = tmp_path / "docs"

    fake_args = argparse.Namespace(path=str(source), db=str(expected_db), force=True)

    class FakeParser:
        def parse_args(self) -> argparse.Namespace:
            return fake_args

    calls: dict[str, object] = {}

    def fake_reindex(db_path: Path | None, source_path: Path, force: bool = False) -> dict:
        calls["reindex"] = (db_path, source_path, force)
        return {"indexed_files": 4, "skipped_files": 1}

    monkeypatch.setattr(cli, "_reindex_parser", lambda: FakeParser())
    monkeypatch.setattr(cli, "reindex", fake_reindex)

    cli.reindex_main()

    result = json.loads(capsys.readouterr().out)
    assert result == {"indexed_files": 4, "skipped_files": 1}

    reindex_call = calls["reindex"]
    assert reindex_call[0] == expected_db
    assert reindex_call[1] == source.resolve()
    assert reindex_call[2] is True


def test_query_main_invokes_tool_and_prints_json(monkeypatch, capsys, tmp_path: Path) -> None:
    expected_db = tmp_path / "rifflux.db"
    fake_args = argparse.Namespace(
        query="cache ttl",
        mode="semantic",
        top_k=7,
        db=str(expected_db),
    )

    class FakeParser:
        def parse_args(self) -> argparse.Namespace:
            return fake_args

    calls: dict[str, object] = {}

    def fake_search(
        db_path: Path | None,
        query: str,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> dict:
        calls["search"] = (db_path, query, top_k, mode)
        return {"count": 2, "results": []}

    monkeypatch.setattr(cli, "_query_parser", lambda: FakeParser())
    monkeypatch.setattr(cli, "search_rifflux", fake_search)

    cli.query_main()

    result = json.loads(capsys.readouterr().out)
    assert result == {"count": 2, "results": []}
    assert calls["search"] == (expected_db, "cache ttl", 7, "semantic")


def test_rebuild_main_deletes_db_and_force_reindexes(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    expected_db = tmp_path / "rifflux.db"
    expected_db.write_text("old-db", encoding="utf-8")
    source = tmp_path / "docs"

    fake_args = argparse.Namespace(path=str(source), db=str(expected_db))

    class FakeParser:
        def parse_args(self) -> argparse.Namespace:
            return fake_args

    calls: dict[str, object] = {}

    def fake_reindex(
        db_path: Path | None,
        source_path: Path,
        force: bool = False,
    ) -> dict:
        calls["reindex"] = (db_path, source_path, force)
        return {"indexed_files": 4, "skipped_files": 0, "deleted_files": 0}

    monkeypatch.setattr(cli, "_rebuild_parser", lambda: FakeParser())
    monkeypatch.setattr(cli, "reindex", fake_reindex)

    cli.rebuild_main()

    result = json.loads(capsys.readouterr().out)
    assert result["rebuilt_db_path"] == str(expected_db)
    assert result["deleted_existing_db"] is True
    assert result["indexed_files"] == 4
    assert expected_db.exists() is False

    reindex_call = calls["reindex"]
    assert reindex_call[0] == expected_db
    assert reindex_call[1] == source.resolve()
    assert reindex_call[2] is True
