from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.helpers import (
    EXPECTED_MCP_TOOL_DESCRIPTIONS,
    EXPECTED_MCP_TOOL_NAMES,
    EXPECTED_MCP_TOOL_PARAM_DESCRIPTIONS,
    EXPECTED_MCP_TOOL_PARAM_ENUMS,
    EXPECTED_MCP_TOOL_PARAM_NUMERIC_BOUNDS,
    free_tcp_port,
    terminate_process_tree,
)


async def _run_http_protocol_roundtrip(url: str, source_path: Path) -> None:
    # Retry until server is up; streamable-http startup can take a moment.
    for _ in range(50):
        try:
            async with streamable_http_client(url) as (read_stream, write_stream, _):
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

                    reindex_result = await session.call_tool(
                        "reindex",
                        {
                            "path": str(source_path),
                            "force": True,
                        },
                    )
                    assert not reindex_result.isError

                    search_result = await session.call_tool(
                        "search_rifflux",
                        {
                            "query": "cache ttl",
                            "top_k": 3,
                            "mode": "hybrid",
                        },
                    )
                    assert not search_result.isError
                    return
        except Exception:
            await anyio.sleep(0.1)

    raise RuntimeError("Could not complete MCP streamable-http protocol roundtrip")


def test_mcp_streamable_http_protocol_roundtrip(
    fixture_corpus_path: Path,
    make_db_path: Callable[[str], Path],
) -> None:
    workspace = Path(__file__).resolve().parents[1]
    python_exe = workspace / ".venv" / "Scripts" / "python.exe"
    db_path = make_db_path("protocol-http.db")
    source_path = fixture_corpus_path

    port = free_tcp_port()
    env = os.environ.copy()
    env["RIFLUX_DB_PATH"] = str(db_path)
    env["RIFLUX_EMBEDDING_BACKEND"] = "hash"
    env["PYTHONPATH"] = "src"

    server_code = (
        "from rifflux.mcp.server import create_server; "
        f"s=create_server(); s.settings.host='127.0.0.1'; s.settings.port={port}; "
        "s.run(transport='streamable-http')"
    )

    process = subprocess.Popen(
        [str(python_exe), "-c", server_code],
        cwd=str(workspace),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        # brief grace period before first connection attempts
        time.sleep(0.2)
        anyio.run(
            partial(
                _run_http_protocol_roundtrip,
                f"http://127.0.0.1:{port}/mcp",
                source_path,
            )
        )
    finally:
        terminate_process_tree(process)
