from __future__ import annotations

import hashlib
import logging
import time
from fnmatch import fnmatch
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from rifflux.db.sqlite_store import SqliteStore
from rifflux.embeddings.hash_embedder import hash_embed
from rifflux.indexing.chunker import chunk_markdown, normalize_path

logger = logging.getLogger("rifflux.indexing")


class Indexer:
    def __init__(
        self,
        store: SqliteStore,
        *,
        max_chunk_chars: int = 2000,
        min_chunk_chars: int = 120,
        embed_chunk: Callable[[str], np.ndarray] | None = None,
        embedding_model: str = "hash-384",
        include_globs: tuple[str, ...] = ("*.md",),
        exclude_globs: tuple[str, ...] = (),
    ) -> None:
        self.store = store
        self.max_chunk_chars = max_chunk_chars
        self.min_chunk_chars = min_chunk_chars
        self.embed_chunk = embed_chunk or hash_embed
        self.embedding_model = embedding_model
        self.include_globs = include_globs
        self.exclude_globs = exclude_globs

    def _is_included(self, relative_path: str) -> bool:
        return any(fnmatch(relative_path, pattern) for pattern in self.include_globs)

    def _is_excluded(self, relative_path: str) -> bool:
        return any(fnmatch(relative_path, pattern) for pattern in self.exclude_globs)

    def reindex_path(self, root: Path, *, force: bool = False) -> dict[str, Any]:
        t_start = time.perf_counter()
        indexed = 0
        skipped = 0
        seen_paths: list[str] = []
        root = root.resolve()
        source_root = root.parent if root.is_file() else root
        file_candidates = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        logger.debug("reindex_path root=%s candidates=%d force=%s", root, len(file_candidates), force)

        # Bulk-load existing file metadata to avoid per-file DB queries.
        file_meta_map = self.store.get_all_file_meta()

        for file_path in file_candidates:
            rel = normalize_path(str(file_path.relative_to(source_root)))
            if not self._is_included(rel) or self._is_excluded(rel):
                continue
            seen_paths.append(rel)
            stat = file_path.stat()
            existing = file_meta_map.get(rel)

            # Fast path: mtime + size unchanged → skip without reading file
            if (
                not force
                and existing
                and int(existing["mtime_ns"]) == int(stat.st_mtime_ns)
                and int(existing["size_bytes"]) == int(stat.st_size)
            ):
                logger.debug("skip (stat match) %s", rel)
                skipped += 1
                continue

            # Slow path: metadata changed — read file and compute hash
            content_bytes = file_path.read_bytes()
            sha256 = hashlib.sha256(content_bytes).hexdigest()

            # Content-only check: mtime/size changed but content identical
            # (e.g. touch, copy-replace with same content) → update metadata, skip re-chunking
            if (
                not force
                and existing
                and str(existing["sha256"]) == sha256
            ):
                logger.debug("skip (hash match, stat updated) %s", rel)
                self.store.upsert_file(
                    path=rel,
                    mtime_ns=int(stat.st_mtime_ns),
                    size_bytes=int(stat.st_size),
                    sha256=sha256,
                )
                skipped += 1
                continue

            t_file = time.perf_counter()
            file_id = self.store.upsert_file(
                path=rel,
                mtime_ns=int(stat.st_mtime_ns),
                size_bytes=int(stat.st_size),
                sha256=sha256,
            )
            self.store.delete_chunks_for_file(file_id)
            text = content_bytes.decode("utf-8")
            chunks = chunk_markdown(
                text,
                rel,
                max_chunk_chars=self.max_chunk_chars,
                min_chunk_chars=self.min_chunk_chars,
            )
            for chunk in chunks:
                self.store.insert_chunk(
                    chunk_id=chunk.chunk_id,
                    file_id=file_id,
                    chunk_index=chunk.chunk_index,
                    heading_path=chunk.heading_path,
                    content=chunk.content,
                    token_count=chunk.token_count,
                )
                self.store.insert_embedding(
                    chunk_id=chunk.chunk_id,
                    model=self.embedding_model,
                    vector=self.embed_chunk(chunk.content),
                )

            dt_file = time.perf_counter() - t_file
            logger.debug("indexed %s chunks=%d in %.3fs", rel, len(chunks), dt_file)
            indexed += 1
        self.store.commit()
        dt = time.perf_counter() - t_start
        logger.debug("reindex_path done in %.3fs indexed=%d skipped=%d", dt, indexed, skipped)
        return {
            "indexed_files": indexed,
            "skipped_files": skipped,
            "seen_paths": seen_paths,
        }
