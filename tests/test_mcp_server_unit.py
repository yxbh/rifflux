from __future__ import annotations

import argparse
from functools import partial
from pathlib import Path

import anyio

from rifflux.mcp import server as mcp_server


async def _call_tool(service, name: str, arguments: dict) -> dict:
    _, structured = await service.call_tool(name, arguments)
    return structured


def test_create_server_registers_tools_with_schema_metadata(monkeypatch) -> None:
    monkeypatch.setenv("RIFFLUX_DB_PATH", "env-rifflux.db")

    service = mcp_server.create_server()

    tools = anyio.run(service.list_tools)
    by_name = {tool.name: tool for tool in tools}

    assert {
        "search_rifflux",
        "get_chunk",
        "get_file",
        "index_status",
        "reindex",
    }.issubset(by_name)

    search_schema = by_name["search_rifflux"].inputSchema
    assert search_schema["properties"]["mode"]["enum"] == ["lexical", "semantic", "hybrid"]
    assert search_schema["properties"]["top_k"]["minimum"] == 1
    assert search_schema["properties"]["top_k"]["maximum"] == 100


def test_create_server_tool_wrappers_delegate_to_mcp_tools(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_search(
        db_path: Path | None,
        query: str,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> dict:
        calls["search"] = (db_path, query, top_k, mode)
        return {"tool": "search"}

    def fake_get_chunk(db_path: Path | None, chunk_id: str) -> dict:
        calls["chunk"] = (db_path, chunk_id)
        return {"tool": "chunk"}

    def fake_get_file(db_path: Path | None, path: str) -> dict:
        calls["file"] = (db_path, path)
        return {"tool": "file"}

    def fake_status(db_path: Path | None) -> dict:
        calls["status"] = db_path
        return {"tool": "status"}

    def fake_reindex(
        db_path: Path | None,
        source_path: Path,
        force: bool = False,
        prune_missing: bool = True,
        background: bool = False,
    ) -> dict:
        calls["reindex"] = (db_path, source_path, force, prune_missing)
        return {"tool": "reindex"}

    def fake_reindex_many(
        db_path: Path | None,
        source_paths: list[Path],
        force: bool = False,
        prune_missing: bool = True,
        background: bool = False,
    ) -> dict:
        calls["reindex_many"] = (db_path, source_paths, force, prune_missing)
        return {"tool": "reindex_many"}

    monkeypatch.setattr(mcp_server, "mcp_search_rifflux", fake_search)
    monkeypatch.setattr(mcp_server, "mcp_get_chunk", fake_get_chunk)
    monkeypatch.setattr(mcp_server, "mcp_get_file", fake_get_file)
    monkeypatch.setattr(mcp_server, "mcp_index_status", fake_status)
    monkeypatch.setattr(mcp_server, "mcp_reindex", fake_reindex)
    monkeypatch.setattr(mcp_server, "mcp_reindex_many", fake_reindex_many)

    db_path = tmp_path / "unit.db"
    service = mcp_server.create_server(db_path=db_path)

    search_result = anyio.run(
        partial(
            _call_tool,
            service,
            "search_rifflux",
            {"query": "cache", "top_k": 3, "mode": "lexical"},
        )
    )
    chunk_result = anyio.run(partial(_call_tool, service, "get_chunk", {"chunk_id": "cid-1"}))
    file_result = anyio.run(partial(_call_tool, service, "get_file", {"path": "notes.md"}))
    status_result = anyio.run(partial(_call_tool, service, "index_status", {}))
    many_result = anyio.run(
        partial(
            _call_tool,
            service,
            "reindex",
            {"paths": ["one", "two"], "force": True, "prune_missing": False},
        )
    )
    single_result = anyio.run(
        partial(
            _call_tool,
            service,
            "reindex",
            {"path": "single", "force": False, "prune_missing": True},
        )
    )

    assert search_result == {"tool": "search"}
    assert chunk_result == {"tool": "chunk"}
    assert file_result == {"tool": "file"}
    assert status_result == {"tool": "status"}
    assert many_result == {"tool": "reindex_many"}
    assert single_result == {"tool": "reindex"}

    assert calls["search"] == (db_path, "cache", 3, "lexical")
    assert calls["chunk"] == (db_path, "cid-1")
    assert calls["file"] == (db_path, "notes.md")
    assert calls["status"] == db_path

    reindex_many_call = calls["reindex_many"]
    assert reindex_many_call[0] == db_path
    assert [str(path) for path in reindex_many_call[1]] == ["one", "two"]
    assert reindex_many_call[2] is True
    assert reindex_many_call[3] is False

    reindex_call = calls["reindex"]
    assert reindex_call[0] == db_path
    assert str(reindex_call[1]) == "single"
    assert reindex_call[2] is False
    assert reindex_call[3] is True


def test_main_runs_created_server(monkeypatch) -> None:
    state = {"ran": False}

    class FakeServer:
        def run(self) -> None:
            state["ran"] = True

    class FakeParser:
        def parse_args(self) -> argparse.Namespace:
            return argparse.Namespace(db=None, watch_path=[])

    monkeypatch.setattr(mcp_server, "_server_parser", lambda: FakeParser())
    monkeypatch.setattr(mcp_server, "create_server", lambda: FakeServer())

    mcp_server.main()

    assert state["ran"] is True


def test_main_applies_watch_path_cli_overrides(monkeypatch) -> None:
    state = {"ran": False}

    class FakeServer:
        def run(self) -> None:
            state["ran"] = True

    class FakeParser:
        def parse_args(self) -> argparse.Namespace:
            return argparse.Namespace(db="tmp/custom.db", watch_path=["docs", "notes"])

    monkeypatch.delenv("RIFFLUX_DB_PATH", raising=False)
    monkeypatch.delenv("RIFFLUX_FILE_WATCHER", raising=False)
    monkeypatch.delenv("RIFFLUX_FILE_WATCHER_PATHS", raising=False)
    monkeypatch.setattr(mcp_server, "_server_parser", lambda: FakeParser())
    monkeypatch.setattr(mcp_server, "create_server", lambda: FakeServer())

    mcp_server.main()

    assert state["ran"] is True
    assert mcp_server.os.environ["RIFFLUX_DB_PATH"] == "tmp/custom.db"
    assert mcp_server.os.environ["RIFFLUX_FILE_WATCHER"] == "1"
    assert mcp_server.os.environ["RIFFLUX_FILE_WATCHER_PATHS"] == "docs,notes"
