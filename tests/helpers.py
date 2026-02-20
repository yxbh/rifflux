from __future__ import annotations

import socket
import subprocess
from pathlib import Path

EXPECTED_MCP_TOOL_NAMES = {
    "search_rifflux",
    "get_chunk",
    "get_file",
    "index_status",
    "reindex",
}

EXPECTED_MCP_TOOL_DESCRIPTIONS = {
    "search_rifflux": (
        "Search indexed content using lexical, semantic, or hybrid retrieval modes."
    ),
    "get_chunk": (
        "Get one indexed chunk by stable chunk ID, including metadata and content."
    ),
    "get_file": (
        "Get all indexed chunks and metadata for a specific source file path."
    ),
    "index_status": (
        "Report current index counts and embedding backend/model configuration."
    ),
    "reindex": "Index one path or multiple paths and optionally force a full rebuild.",
}

EXPECTED_MCP_TOOL_PARAM_DESCRIPTIONS = {
    "search_rifflux": {
        "query": "Natural-language query to search indexed content.",
        "top_k": "Maximum number of results to return (1-100).",
        "mode": "Retrieval mode: lexical, semantic, or hybrid.",
    },
    "get_chunk": {
        "chunk_id": "Stable chunk identifier returned by search results.",
    },
    "get_file": {
        "path": "Source file path to retrieve from the index.",
    },
    "index_status": {},
    "reindex": {
        "path": "Single directory or file path to index.",
        "paths": "Multiple directories or file paths to index.",
        "force": "Rebuild matching entries even if unchanged.",
        "prune_missing": "Delete indexed files missing from scanned paths.",
        "background": "Run indexing in the background and return a job_id immediately.",
    },
}

EXPECTED_MCP_TOOL_PARAM_ENUMS = {
    "search_rifflux": {
        "mode": ["lexical", "semantic", "hybrid"],
    },
}

EXPECTED_MCP_TOOL_PARAM_NUMERIC_BOUNDS = {
    "search_rifflux": {
        "top_k": {"minimum": 1, "maximum": 100},
    },
}


def write_search_fixture_corpus(root: Path, *, filename: str = "notes.md") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(
        """
# Notes

MCP server and retrieval architecture notes with practical guidance for indexing,
querying, ranking, and operational diagnostics in local development workflows.
These notes intentionally include enough prose to exceed chunk size thresholds,
so the fixture is reliably indexed in tests.

## Caching

Redis cache ttl policies and invalidation guidance with concrete examples:
use shorter TTLs for volatile data, prefer explicit invalidation on writes,
and keep cache keys namespaced by domain and resource type for predictable lookup.
""",
        encoding="utf-8",
    )


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
