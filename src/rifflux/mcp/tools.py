from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from rifflux.config import RiffluxConfig

logger = logging.getLogger("rifflux.mcp.tools")
from rifflux.db.sqlite_store import SqliteStore
from rifflux.embeddings.embedder_factory import EmbedderBundle, resolve_embedder
from rifflux.indexing.background import BackgroundIndexer, IndexRequest
from rifflux.indexing.indexer import Indexer
from rifflux.retrieval.search import SearchService


_LAST_AUTO_REINDEX_MONOTONIC: dict[str, float] = {}
_bg_indexer: BackgroundIndexer | None = None

# Thread-safe caches to avoid repeated expensive init on parallel tool calls.
_init_lock = threading.Lock()
_reindex_lock = threading.Lock()
_schema_initialized: set[str] = set()
_runtime_cache: dict[str, tuple[RiffluxConfig, EmbedderBundle]] = {}


def _db_for_hint(db_path: Path | None, config: RiffluxConfig | None = None) -> Path:
    if db_path is not None:
        return db_path
    if config is not None:
        return config.db_path
    return RiffluxConfig.from_env().db_path


def _raise_with_rebuild_hint(
    exc: sqlite3.OperationalError,
    *,
    db_path: Path | None,
    source_paths: list[Path] | None = None,
) -> None:
    target_db = _db_for_hint(db_path)
    source_arg = str(source_paths[0]) if source_paths else "."
    detail = str(exc).strip() or "sqlite operational error"
    hint = (
        f"{detail}. If this is due to a schema mismatch, rebuild the DB: "
        f"`riflux-rebuild --path {source_arg} --db {target_db}` "
        f"(or `python scripts/rebuild.py --path {source_arg} --db {target_db}`)."
    )
    raise RuntimeError(hint) from exc


def _git_fingerprint(path: Path) -> dict[str, Any] | None:
    resolved = path.resolve()
    if resolved.is_file():
        resolved = resolved.parent

    worktree_hint: Path | None = None
    for candidate in [resolved, *resolved.parents]:
        if (candidate / ".git").exists():
            worktree_hint = candidate
            break
    if worktree_hint is None:
        return None

    def _run_git(args: list[str]) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "-C", str(worktree_hint), *args],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    worktree = _run_git(["rev-parse", "--show-toplevel"])
    if not worktree:
        return None

    head = _run_git(["rev-parse", "HEAD"])
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    dirty_output = _run_git(["status", "--porcelain"])

    return {
        "worktree": worktree,
        "head": head,
        "branch": branch,
        "is_dirty": bool(dirty_output),
    }


def _combined_git_fingerprint(source_paths: list[Path]) -> dict[str, Any] | None:
    fingerprints = [
        fp
        for fp in (_git_fingerprint(path) for path in source_paths)
        if fp is not None
    ]
    if not fingerprints:
        return None

    primary = fingerprints[0]
    unique_worktrees = sorted({str(fp["worktree"]) for fp in fingerprints})
    primary["multi_repo"] = len(unique_worktrees) > 1
    primary["worktrees"] = unique_worktrees
    return primary


def _resolve_runtime(
    config: RiffluxConfig | None,
    db_path: Path | None,
) -> tuple[RiffluxConfig, Path, EmbedderBundle]:
    runtime_config = config or RiffluxConfig.from_env()
    runtime_db_path = db_path or runtime_config.db_path
    key = str(runtime_db_path.resolve())
    if key not in _runtime_cache:
        with _init_lock:
            if key not in _runtime_cache:
                t0 = time.perf_counter()
                bundle = resolve_embedder(runtime_config)
                dt = time.perf_counter() - t0
                logger.debug("embedder resolved in %.3fs backend=%s model=%s", dt, runtime_config.embedding_backend, bundle.model_label)
                _runtime_cache[key] = (runtime_config, bundle)
    cached_config, cached_bundle = _runtime_cache[key]
    return cached_config, runtime_db_path, cached_bundle


def _ensure_schema(store: SqliteStore) -> None:
    """Run schema DDL once per database path. Thread-safe."""
    key = str(store.db_path.resolve())
    if key in _schema_initialized:
        return
    with _init_lock:
        if key in _schema_initialized:
            return
        t0 = time.perf_counter()
        schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
        store.init_schema(schema_path)
        _schema_initialized.add(key)
        logger.debug("schema initialized in %.3fs db=%s", time.perf_counter() - t0, key)


def _services(
    db_path: Path | None = None,
    config: RiffluxConfig | None = None,
) -> tuple[SqliteStore, SearchService, RiffluxConfig, EmbedderBundle]:
    runtime_config, runtime_db_path, bundle = _resolve_runtime(config, db_path)
    store = SqliteStore(runtime_db_path)
    _ensure_schema(store)
    search_service = SearchService(store, embed_query=bundle.embed, rrf_k=runtime_config.rrf_k)
    return store, search_service, runtime_config, bundle


def _run_reindex_job(request: IndexRequest) -> dict[str, Any]:
    """Callback for BackgroundIndexer — runs a blocking reindex."""
    return reindex_many(
        db_path=request.db_path,
        source_paths=request.source_paths,
        force=request.force,
        prune_missing=request.prune_missing,
    )


def _get_bg_indexer() -> BackgroundIndexer:
    """Lazy singleton for the background indexer."""
    global _bg_indexer  # noqa: PLW0603
    if _bg_indexer is None:
        with _init_lock:
            if _bg_indexer is None:
                _bg_indexer = BackgroundIndexer(run_reindex=_run_reindex_job)
    return _bg_indexer


def _clear_caches() -> None:
    """Reset module-level caches. Intended for test teardown."""
    global _bg_indexer  # noqa: PLW0603
    # Drain any in-flight background jobs before clearing state.
    if _bg_indexer is not None:
        _bg_indexer.drain(timeout=10)
    _schema_initialized.clear()
    _runtime_cache.clear()
    _LAST_AUTO_REINDEX_MONOTONIC.clear()
    _bg_indexer = None


def _maybe_auto_reindex(
    db_path: Path | None,
    config: RiffluxConfig,
) -> dict[str, Any] | None:
    if not config.auto_reindex_on_search:
        return None

    effective_db = (db_path or config.db_path).resolve()
    db_key = str(effective_db)
    min_interval = max(0.0, config.auto_reindex_min_interval_seconds)

    # Atomic check-and-claim to prevent parallel auto-reindex storms.
    with _reindex_lock:
        now = time.monotonic()
        last_run = _LAST_AUTO_REINDEX_MONOTONIC.get(db_key)
        if last_run is not None and (now - last_run) < min_interval:
            return {
                "enabled": True,
                "executed": False,
                "reason": "throttled",
                "min_interval_seconds": min_interval,
            }
        # Claim the slot immediately so parallel calls are throttled.
        _LAST_AUTO_REINDEX_MONOTONIC[db_key] = now

    source_paths = [Path(raw).resolve() for raw in config.auto_reindex_paths]
    request = IndexRequest(
        db_path=db_path,
        source_paths=source_paths,
        force=False,
        prune_missing=False,
    )
    job = _get_bg_indexer().submit(request)
    logger.debug("auto-reindex job %s submitted for %s", job.job_id, [str(p) for p in source_paths])
    return {
        "enabled": True,
        "executed": "background",
        "job_id": job.job_id,
        "paths": [str(path) for path in source_paths],
    }


def search_rifflux(
    db_path: Path | None,
    query: str,
    top_k: int = 10,
    mode: str = "hybrid",
) -> dict[str, Any]:
    t_start = time.perf_counter()
    logger.debug("search_rifflux start query=%r top_k=%d mode=%s", query, top_k, mode)
    runtime_config = RiffluxConfig.from_env()
    try:
        # Initialise schema/connection first so the DB is ready before any
        # background thread opens its own connection (avoids EXCLUSIVE-lock
        # contention from executescript on a fresh database).
        store, search, _, bundle = _services(db_path=db_path)
        auto_reindex = _maybe_auto_reindex(db_path, runtime_config)
        try:
            results = search.search(query, top_k=top_k, mode=mode)
            dt = time.perf_counter() - t_start
            logger.debug("search_rifflux done in %.3fs count=%d", dt, len(results))
            return {
                "query": query,
                "mode": mode,
                "count": len(results),
                "embedding_model": bundle.model_label,
                "auto_reindex": auto_reindex,
                "results": results,
            }
        finally:
            store.close()
    except sqlite3.OperationalError as exc:
        _raise_with_rebuild_hint(exc, db_path=db_path)


def get_chunk(db_path: Path | None, chunk_id: str) -> dict[str, Any]:
    try:
        store, search, _, _ = _services(db_path=db_path)
        try:
            chunk = search.get_chunk(chunk_id)
            return {"chunk": chunk}
        finally:
            store.close()
    except sqlite3.OperationalError as exc:
        _raise_with_rebuild_hint(exc, db_path=db_path)


def get_file(db_path: Path | None, path: str) -> dict[str, Any]:
    try:
        store, search, _, _ = _services(db_path=db_path)
        try:
            file_data = search.get_file(path)
            return {"file": file_data}
        finally:
            store.close()
    except sqlite3.OperationalError as exc:
        _raise_with_rebuild_hint(exc, db_path=db_path)


def index_status(db_path: Path | None) -> dict[str, Any]:
    try:
        store, _, config, bundle = _services(db_path=db_path)
        try:
            fingerprint_raw = store.get_metadata("git_fingerprint")
            fingerprint = json.loads(fingerprint_raw) if fingerprint_raw else None
            jobs = [j.to_dict() for j in _get_bg_indexer().get_all_jobs()]
            return {
                **store.index_status(),
                "db_path": str(config.db_path if db_path is None else db_path),
                "embedding_backend": config.embedding_backend,
                "embedding_model": bundle.model_label,
                "index_include_globs": list(config.index_include_globs),
                "index_exclude_globs": list(config.index_exclude_globs),
                "git_fingerprint": fingerprint,
                "background_jobs": jobs,
            }
        finally:
            store.close()
    except sqlite3.OperationalError as exc:
        _raise_with_rebuild_hint(exc, db_path=db_path)


def reindex(
    db_path: Path | None,
    source_path: Path,
    force: bool = False,
    prune_missing: bool = True,
    background: bool = False,
) -> dict[str, Any]:
    if background:
        request = IndexRequest(
            db_path=db_path,
            source_paths=[source_path],
            force=force,
            prune_missing=prune_missing,
        )
        # Ensure schema is ready before the background thread opens a connection.
        store, *_ = _services(db_path=db_path)
        store.close()
        job = _get_bg_indexer().submit(request)
        return job.to_dict()
    result = reindex_many(
        db_path=db_path,
        source_paths=[source_path],
        force=force,
        prune_missing=prune_missing,
    )
    result.pop("indexed_paths", None)
    return result


def reindex_many(
    db_path: Path | None,
    source_paths: list[Path],
    force: bool = False,
    prune_missing: bool = True,
    background: bool = False,
) -> dict[str, Any]:
    if background:
        request = IndexRequest(
            db_path=db_path,
            source_paths=source_paths,
            force=force,
            prune_missing=prune_missing,
        )
        # Ensure schema is ready before the background thread opens a connection.
        store, *_ = _services(db_path=db_path)
        store.close()
        job = _get_bg_indexer().submit(request)
        return job.to_dict()
    t_start = time.perf_counter()
    logger.debug("reindex_many start paths=%s force=%s prune=%s", [str(p) for p in source_paths], force, prune_missing)
    try:
        store, _, config, bundle = _services(db_path=db_path)
        try:
            indexer = Indexer(
                store,
                max_chunk_chars=config.max_chunk_chars,
                min_chunk_chars=config.min_chunk_chars,
                embed_chunk=bundle.embed,
                embedding_model=bundle.model_label,
                include_globs=config.index_include_globs,
                exclude_globs=config.index_exclude_globs,
            )

            indexed_files = 0
            skipped_files = 0
            indexed_paths: list[str] = []
            seen_paths: list[str] = []
            for source_path in source_paths:
                result = indexer.reindex_path(source_path, force=force)
                indexed_files += int(result.get("indexed_files", 0))
                skipped_files += int(result.get("skipped_files", 0))
                indexed_paths.append(str(source_path))
                seen_paths.extend([str(path) for path in result.get("seen_paths", [])])

            unique_seen_paths = sorted(set(seen_paths))
            deleted_files = 0
            if prune_missing:
                deleted_files = store.delete_files_except(unique_seen_paths)

            fingerprint = _combined_git_fingerprint(source_paths)
            if fingerprint is None:
                store.delete_metadata("git_fingerprint")
            else:
                store.set_metadata("git_fingerprint", json.dumps(fingerprint, separators=(",", ":")))

            store.commit()

            dt = time.perf_counter() - t_start
            logger.debug(
                "reindex_many done in %.3fs indexed=%d skipped=%d deleted=%d",
                dt, indexed_files, skipped_files, deleted_files,
            )
            return {
                "indexed_files": indexed_files,
                "skipped_files": skipped_files,
                "deleted_files": deleted_files,
                "indexed_paths": indexed_paths,
                "embedding_model": bundle.model_label,
                "embedding_backend": config.embedding_backend,
                "git_fingerprint": fingerprint,
                "prune_missing": prune_missing,
            }
        finally:
            store.close()
    except sqlite3.OperationalError as exc:
        _raise_with_rebuild_hint(exc, db_path=db_path, source_paths=source_paths)
