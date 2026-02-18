from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from rifflux.config import RiffluxConfig
from rifflux.mcp.tools import (
    get_chunk as mcp_get_chunk,
    get_file as mcp_get_file,
    index_status as mcp_index_status,
    reindex as mcp_reindex,
    reindex_many as mcp_reindex_many,
    search_rifflux as mcp_search_rifflux,
)


def create_server(db_path: Path | None = None) -> FastMCP:
    configured_db = Path(os.getenv("RIFLUX_DB_PATH", str(RiffluxConfig.from_env().db_path)))
    resolved_db_path = db_path or configured_db
    mcp = FastMCP("rifflux")

    @mcp.tool()
    def search_rifflux(
        query: Annotated[
            str,
            Field(description="Natural-language query to search indexed content."),
        ],
        top_k: Annotated[
            int,
            Field(
                description="Maximum number of results to return (1-100).",
                ge=1,
                le=100,
            ),
        ] = 10,
        mode: Annotated[
            Literal["lexical", "semantic", "hybrid"],
            Field(description="Retrieval mode: lexical, semantic, or hybrid."),
        ] = "hybrid",
    ) -> dict[str, Any]:
        """Search indexed content using lexical, semantic, or hybrid retrieval modes."""
        return mcp_search_rifflux(
            resolved_db_path,
            query=query,
            top_k=top_k,
            mode=mode,
        )

    @mcp.tool()
    def get_chunk(
        chunk_id: Annotated[
            str,
            Field(description="Stable chunk identifier returned by search results."),
        ]
    ) -> dict[str, Any]:
        """Get one indexed chunk by stable chunk ID, including metadata and content."""
        return mcp_get_chunk(resolved_db_path, chunk_id=chunk_id)

    @mcp.tool()
    def get_file(
        path: Annotated[
            str,
            Field(description="Source file path to retrieve from the index."),
        ]
    ) -> dict[str, Any]:
        """Get all indexed chunks and metadata for a specific source file path."""
        return mcp_get_file(resolved_db_path, path=path)

    @mcp.tool()
    def index_status() -> dict[str, Any]:
        """Report current index counts and embedding backend/model configuration."""
        return mcp_index_status(resolved_db_path)

    @mcp.tool()
    def reindex(
        path: Annotated[
            str | None,
            Field(description="Single directory or file path to index."),
        ] = None,
        paths: Annotated[
            list[str] | None,
            Field(description="Multiple directories or file paths to index."),
        ] = None,
        force: Annotated[
            bool,
            Field(description="Rebuild matching entries even if unchanged."),
        ] = False,
        prune_missing: Annotated[
            bool,
            Field(description="Delete indexed files missing from scanned paths."),
        ] = True,
    ) -> dict[str, Any]:
        """Index one path or multiple paths and optionally force a full rebuild."""
        if paths:
            source_paths = [Path(item) for item in paths]
            return mcp_reindex_many(
                resolved_db_path,
                source_paths=source_paths,
                force=force,
                prune_missing=prune_missing,
            )
        source = Path(path) if path else Path.cwd()
        return mcp_reindex(
            resolved_db_path,
            source_path=source,
            force=force,
            prune_missing=prune_missing,
        )

    return mcp


def main() -> None:
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
