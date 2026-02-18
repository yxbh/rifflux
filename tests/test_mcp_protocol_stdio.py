from __future__ import annotations

import os
from collections.abc import Callable
from functools import partial
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from rifflux.mcp.tools import reindex
from tests.helpers import (
    EXPECTED_MCP_TOOL_DESCRIPTIONS,
    EXPECTED_MCP_TOOL_NAMES,
    EXPECTED_MCP_TOOL_PARAM_DESCRIPTIONS,
    EXPECTED_MCP_TOOL_PARAM_ENUMS,
    EXPECTED_MCP_TOOL_PARAM_NUMERIC_BOUNDS,
)


async def _run_protocol_roundtrip(*, workspace: Path, db_path: Path, source_path: Path) -> None:
    python_exe = workspace / ".venv" / "Scripts" / "python.exe"
    env = os.environ.copy()
    env["RIFLUX_DB_PATH"] = str(db_path)
    env["RIFLUX_EMBEDDING_BACKEND"] = "hash"
    env["PYTHONPATH"] = "src"
    env["PYTHONIOENCODING"] = "utf-8"
    params = StdioServerParameters(
        command=str(python_exe),
        args=["-m", "rifflux.mcp.server"],
        cwd=str(workspace),
        env=env,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tool_list = await session.list_tools()
            names = {tool.name for tool in tool_list.tools}
            assert EXPECTED_MCP_TOOL_NAMES.issubset(names)
            descriptions = {
                tool.name: tool.description
                for tool in tool_list.tools
                if tool.name in EXPECTED_MCP_TOOL_DESCRIPTIONS
            }
            assert descriptions == EXPECTED_MCP_TOOL_DESCRIPTIONS
            param_descriptions: dict[str, dict[str, str]] = {}
            param_enums: dict[str, dict[str, list[str]]] = {}
            param_numeric_bounds: dict[str, dict[str, dict[str, int]]] = {}
            for tool in tool_list.tools:
                if tool.name not in EXPECTED_MCP_TOOL_PARAM_DESCRIPTIONS:
                    continue
                schema = (
                    getattr(tool, "inputSchema", None)
                    or getattr(tool, "input_schema", None)
                    or {}
                )
                properties = schema.get("properties", {})
                param_descriptions[tool.name] = {
                    name: details.get("description", "")
                    for name, details in properties.items()
                }
                if tool.name in EXPECTED_MCP_TOOL_PARAM_ENUMS:
                    param_enums[tool.name] = {
                        name: details.get("enum", [])
                        for name, details in properties.items()
                        if "enum" in details
                    }
                if tool.name in EXPECTED_MCP_TOOL_PARAM_NUMERIC_BOUNDS:
                    param_numeric_bounds[tool.name] = {
                        name: {
                            "minimum": int(details.get("minimum")),
                            "maximum": int(details.get("maximum")),
                        }
                        for name, details in properties.items()
                        if "minimum" in details and "maximum" in details
                    }
            assert param_descriptions == EXPECTED_MCP_TOOL_PARAM_DESCRIPTIONS
            assert param_enums == EXPECTED_MCP_TOOL_PARAM_ENUMS
            assert param_numeric_bounds == EXPECTED_MCP_TOOL_PARAM_NUMERIC_BOUNDS

            search_result = await session.call_tool(
                "search_rifflux",
                {
                    "query": "cache ttl",
                    "top_k": 3,
                    "mode": "hybrid",
                },
            )
            assert not search_result.isError

            status_result = await session.call_tool("index_status")
            assert not status_result.isError


def test_mcp_stdio_protocol_roundtrip(
    fixture_corpus_path: Path,
    make_db_path: Callable[[str], Path],
    monkeypatch,
) -> None:
    workspace = Path(__file__).resolve().parents[1]
    db_path = make_db_path("protocol-test.db")
    source_path = fixture_corpus_path
    monkeypatch.setenv("RIFLUX_EMBEDDING_BACKEND", "hash")

    reindex_result = reindex(db_path=db_path, source_path=source_path, force=True)
    assert reindex_result["indexed_files"] >= 1

    anyio.run(
        partial(
            _run_protocol_roundtrip,
            workspace=workspace,
            db_path=db_path,
            source_path=source_path,
        )
    )
