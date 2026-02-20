"""Background indexing job manager.

Accepts reindex requests, assigns job IDs, and processes them sequentially
in a single daemon worker thread. Jobs persist for the server session lifetime.

Transient errors (e.g. ``sqlite3.OperationalError("database is locked")``)
are retried with exponential backoff before marking a job as failed.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger("rifflux.indexing")

# Retry settings for transient DB errors.
_MAX_RETRIES = 3
_BASE_BACKOFF_S = 1.0  # first retry delay; doubles each attempt


def _is_transient(exc: Exception) -> bool:
    """Return True if *exc* looks like a temporary SQLite lock."""
    if isinstance(exc, sqlite3.OperationalError):
        msg = str(exc).lower()
        return "locked" in msg or "busy" in msg
    return False


@dataclass(slots=True)
class IndexRequest:
    """Parameters for a reindex job."""

    db_path: Any  # Path | None — avoid importing Path just for typing
    source_paths: list[Any]
    force: bool = False
    prune_missing: bool = True


@dataclass(slots=True)
class IndexJob:
    """Tracks the lifecycle of a single reindex job."""

    job_id: str
    status: str  # queued | running | completed | failed
    request: IndexRequest
    created_at: float  # time.monotonic()
    started_at: float | None = None
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    retries: int = 0

    def to_dict(self) -> dict[str, Any]:
        elapsed: float | None = None
        if self.started_at is not None:
            end = self.completed_at if self.completed_at is not None else time.monotonic()
            elapsed = round(end - self.started_at, 3)
        return {
            "job_id": self.job_id,
            "status": self.status,
            "elapsed_seconds": elapsed,
            "result": self.result,
            "error": self.error,
            "retries": self.retries,
        }


class BackgroundIndexer:
    """Sequential job queue for background reindex operations.

    - ``submit()`` enqueues a job and returns immediately.
    - A single daemon thread processes jobs one at a time.
    - Transient SQLite lock errors are retried with exponential backoff.
    - ``shutdown()`` cancels pending jobs and waits for the running job.
    - All completed/failed jobs are retained for the server session.
    """

    def __init__(
        self,
        run_reindex: Callable[[IndexRequest], dict[str, Any]],
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._run_reindex = run_reindex
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._jobs: dict[str, IndexJob] = {}
        self._queue: deque[str] = deque()
        self._worker: threading.Thread | None = None
        self._shutdown_event = threading.Event()

    # -- public API ----------------------------------------------------------

    def submit(self, request: IndexRequest) -> IndexJob:
        """Enqueue a reindex job. Returns the job immediately (status=queued)."""
        if self._shutdown_event.is_set():
            raise RuntimeError("BackgroundIndexer is shut down")
        job_id = uuid4().hex[:12]
        job = IndexJob(
            job_id=job_id,
            status="queued",
            request=request,
            created_at=time.monotonic(),
        )
        with self._lock:
            self._jobs[job_id] = job
            self._queue.append(job_id)
            self._maybe_start_worker()
        logger.debug("background job %s queued (%d in queue)", job_id, len(self._queue))
        return job

    def get_job(self, job_id: str) -> IndexJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_all_jobs(self) -> list[IndexJob]:
        with self._lock:
            return list(self._jobs.values())

    def drain(self, timeout: float = 30.0) -> None:
        """Block until all queued/running jobs finish. For test teardown."""
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)

    def shutdown(self, timeout: float = 10.0) -> None:
        """Cancel pending jobs, let the running job finish, then stop.

        Safe to call multiple times or from atexit/signal handlers.
        """
        self._shutdown_event.set()
        # Cancel queued (not yet running) jobs.
        with self._lock:
            while self._queue:
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                if job is not None and job.status == "queued":
                    job.status = "failed"
                    job.error = "cancelled: server shutdown"
                    job.completed_at = time.monotonic()
        # Wait for the running job to complete.
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)
        logger.info("BackgroundIndexer shut down")

    # -- internal ------------------------------------------------------------

    def _maybe_start_worker(self) -> None:
        """Start the worker thread if it's not already running.

        Must be called while holding ``self._lock``.
        """
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _worker_loop(self) -> None:
        """Process jobs from the queue sequentially until empty or shut down."""
        while not self._shutdown_event.is_set():
            with self._lock:
                if not self._queue:
                    return  # thread exits; restarted on next submit()
                job_id = self._queue.popleft()
                job = self._jobs[job_id]
                job.status = "running"
                job.started_at = time.monotonic()

            logger.debug("background job %s running", job_id)
            self._execute_with_retry(job)

    def _execute_with_retry(self, job: IndexJob) -> None:
        """Run a job, retrying on transient errors with exponential backoff."""
        attempt = 0
        while True:
            try:
                result = self._run_reindex(job.request)
                with self._lock:
                    job.status = "completed"
                    job.result = result
                    job.retries = attempt
                    job.completed_at = time.monotonic()
                logger.debug("background job %s completed (attempts=%d)", job.job_id, attempt + 1)
                return
            except Exception as exc:
                if _is_transient(exc) and attempt < self._max_retries:
                    attempt += 1
                    delay = _BASE_BACKOFF_S * (2 ** (attempt - 1))
                    logger.warning(
                        "background job %s transient error (attempt %d/%d), retrying in %.1fs: %s",
                        job.job_id, attempt, self._max_retries, delay, exc,
                    )
                    # Interruptible sleep — honours shutdown requests.
                    if self._shutdown_event.wait(timeout=delay):
                        with self._lock:
                            job.status = "failed"
                            job.error = "cancelled: server shutdown during retry"
                            job.retries = attempt
                            job.completed_at = time.monotonic()
                        return
                    continue
                # Permanent error or retries exhausted.
                logger.exception("background job %s failed (attempts=%d)", job.job_id, attempt + 1)
                with self._lock:
                    job.status = "failed"
                    job.error = str(exc)
                    job.retries = attempt
                    job.completed_at = time.monotonic()
                return
