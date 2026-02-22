"""Filesystem watcher that triggers background reindex on file changes.

Uses ``watchfiles`` (Rust-backed) for efficient cross-platform FS events.
Changes are debounced and filtered by include/exclude globs before
submitting a reindex job to the :class:`BackgroundIndexer`.

The watch loop automatically restarts on transient errors (e.g. permission
or OS-level handle errors) with exponential backoff, up to a configurable
maximum number of consecutive crashes.
"""

from __future__ import annotations

import logging
import threading
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

try:
    from watchfiles import Change, watch
except ImportError:  # optional dependency
    watch = None  # type: ignore[assignment]

from rifflux.indexing.background import BackgroundIndexer, IndexRequest

logger = logging.getLogger("rifflux.indexing")

# Auto-restart settings.
_MAX_CRASH_RESTARTS = 5
_RESTART_BACKOFF_BASE_S = 2.0  # doubles each consecutive crash


class FileWatcher:
    """Watch directories for file changes and trigger background reindex.

    Parameters
    ----------
    bg_indexer:
        The :class:`BackgroundIndexer` to submit reindex jobs to.
    watch_paths:
        Directories to watch recursively.
    db_path:
        Database path passed to reindex jobs.
    include_globs:
        Only trigger on files matching these patterns (e.g. ``("*.md",)``).
    exclude_globs:
        Ignore files matching these patterns.
    debounce_ms:
        Minimum milliseconds between FS event batches (watchfiles setting).
    max_crash_restarts:
        Maximum consecutive crashes before the watcher gives up.
    """

    def __init__(
        self,
        bg_indexer: BackgroundIndexer,
        watch_paths: list[Path],
        db_path: Path | None = None,
        include_globs: tuple[str, ...] = ("*.md",),
        exclude_globs: tuple[str, ...] = (),
        debounce_ms: int = 500,
        max_crash_restarts: int = _MAX_CRASH_RESTARTS,
    ) -> None:
        self._bg_indexer = bg_indexer
        self._watch_paths = [p.resolve() for p in watch_paths]
        self._watch_paths_key = tuple(str(p.resolve()) for p in watch_paths)
        self._db_path = db_path
        self._include_globs = include_globs
        self._exclude_globs = exclude_globs
        self._debounce_ms = debounce_ms
        self._max_crash_restarts = max_crash_restarts

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started_at: float | None = None
        self._events_received: int = 0
        self._jobs_submitted: int = 0
        self._crash_count: int = 0

    # -- public API ----------------------------------------------------------

    def start(self) -> None:
        """Start watching in a background daemon thread."""
        if watch is None:
            logger.warning("watchfiles not installed; file watcher disabled")
            return
        if self._thread is not None and self._thread.is_alive():
            logger.debug("file watcher already running")
            return
        self._stop_event.clear()
        self._crash_count = 0
        self._thread = threading.Thread(target=self._run_with_restart, daemon=True)
        self._thread.start()
        self._started_at = time.monotonic()
        logger.info(
            "file watcher started: paths=%s include=%s exclude=%s debounce=%dms",
            [str(p) for p in self._watch_paths],
            self._include_globs,
            self._exclude_globs,
            self._debounce_ms,
        )

    def stop(self, timeout: float = 3.0) -> None:
        """Signal the watcher to stop and wait for the thread to finish."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("file watcher thread did not exit within %.1fs", timeout)
        self._thread = None
        logger.info("file watcher stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        """Return watcher status for inclusion in ``index_status``."""
        return {
            "enabled": True,
            "running": self.is_running,
            "watch_paths": [str(p) for p in self._watch_paths],
            "include_globs": list(self._include_globs),
            "exclude_globs": list(self._exclude_globs),
            "debounce_ms": self._debounce_ms,
            "events_received": self._events_received,
            "jobs_submitted": self._jobs_submitted,
            "crash_restarts": self._crash_count,
        }

    # -- internal ------------------------------------------------------------

    def _matches_globs(self, file_path: Path) -> bool:
        """Check if a changed file matches include globs and not exclude globs."""
        name = file_path.name
        normalized = str(file_path).replace("\\", "/")
        variants = {name, normalized}

        try:
            resolved = file_path.resolve()
        except Exception:
            resolved = None

        if resolved is not None:
            variants.add(str(resolved).replace("\\", "/"))
            for root in self._watch_paths:
                try:
                    rel = resolved.relative_to(root)
                except Exception:
                    continue
                variants.add(rel.as_posix())

        included = any(fnmatch(candidate, g) for candidate in variants for g in self._include_globs)
        if not included:
            return False

        excluded = any(fnmatch(candidate, g) for candidate in variants for g in self._exclude_globs)
        return not excluded

    def _has_pending_reindex_job(self) -> bool:
        db_key = str(self._db_path.resolve()) if self._db_path is not None else None
        for job in self._bg_indexer.get_all_jobs():
            if job.status not in {"queued", "running"}:
                continue
            req_db = job.request.db_path
            req_db_key = str(req_db.resolve()) if req_db is not None else None
            req_paths_key = tuple(str(Path(path).resolve()) for path in job.request.source_paths)
            if req_db_key == db_key and req_paths_key == self._watch_paths_key:
                return True
        return False

    def _run_with_restart(self) -> None:
        """Outer loop that auto-restarts ``_watch_loop`` on crash."""
        while not self._stop_event.is_set():
            try:
                self._watch_loop()
                # Normal exit (stop_event set or generator exhausted).
                return
            except Exception:
                self._crash_count += 1
                if self._crash_count > self._max_crash_restarts:
                    logger.error(
                        "file watcher exceeded %d crash restarts; giving up",
                        self._max_crash_restarts,
                    )
                    return
                delay = _RESTART_BACKOFF_BASE_S * (2 ** (self._crash_count - 1))
                logger.warning(
                    "file watcher crashed (%d/%d), restarting in %.1fs",
                    self._crash_count,
                    self._max_crash_restarts,
                    delay,
                )
                # Interruptible sleep — honours stop requests.
                if self._stop_event.wait(timeout=delay):
                    return

    def _watch_loop(self) -> None:
        """Blocking loop that yields batches of FS events."""
        for changes in watch(
            *self._watch_paths,
            debounce=self._debounce_ms,
            stop_event=self._stop_event,
            recursive=True,
            raise_interrupt=False,
        ):
            if self._stop_event.is_set():
                break

            relevant = [
                (change_type, Path(path))
                for change_type, path in changes
                if self._matches_globs(Path(path))
            ]
            self._events_received += len(relevant)

            if not relevant:
                continue

            logger.debug(
                "file watcher: %d relevant changes detected",
                len(relevant),
            )

            if self._has_pending_reindex_job():
                logger.debug("file watcher: coalesced burst while reindex job pending")
                continue

            # Submit one reindex job covering all watched paths.
            request = IndexRequest(
                db_path=self._db_path,
                source_paths=list(self._watch_paths),
                force=False,
                prune_missing=True,
            )
            self._bg_indexer.submit(request)
            self._jobs_submitted += 1

            # Reset crash counter on successful batch processing.
            self._crash_count = 0
