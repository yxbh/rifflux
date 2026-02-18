from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _build_parameters(db_path: str | None) -> StdioServerParameters:
    """Build stdio client parameters for connecting to the local Rifflux MCP server."""
    python_exe = ROOT / ".venv" / "Scripts" / "python.exe"
    env: dict[str, str] = {
        "PYTHONPATH": "src",
    }
    if db_path:
        env["RIFLUX_DB_PATH"] = db_path
    if backend := os.getenv("RIFLUX_EMBEDDING_BACKEND"):
        env["RIFLUX_EMBEDDING_BACKEND"] = backend

    return StdioServerParameters(
        command=str(python_exe),
        args=["-m", "rifflux.mcp.server"],
        cwd=str(ROOT),
        env=env,
    )


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    """Convert MCP tool metadata into a JSON-serializable dictionary."""
    input_schema = (
        getattr(tool, "inputSchema", None)
        or getattr(tool, "input_schema", None)
        or {}
    )
    output_schema = (
        getattr(tool, "outputSchema", None)
        or getattr(tool, "output_schema", None)
        or {}
    )
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": input_schema,
        "outputSchema": output_schema,
    }


async def _inspect_tools(db_path: str | None) -> dict[str, list[dict[str, Any]]]:
    """Connect to the MCP server and retrieve list_tools metadata."""
    params = _build_parameters(db_path)

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tool_list = await session.list_tools()
            return {"tools": [_tool_to_dict(tool) for tool in tool_list.tools]}


def main() -> None:
    """Inspect and print Rifflux MCP tools metadata as JSON."""
    parser = argparse.ArgumentParser(description="Inspect Rifflux MCP list_tools schema metadata.")
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional database path to pass as RIFLUX_DB_PATH.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output file path for the JSON payload.",
    )
    args = parser.parse_args()

    payload = anyio.run(_inspect_tools, args.db_path)
    indent = 2 if args.pretty else None
    rendered = json.dumps(payload, indent=indent, ensure_ascii=False)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        return

    print(rendered)


if __name__ == "__main__":
    main()
