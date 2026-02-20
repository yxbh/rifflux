"""Background indexing job manager.

Accepts reindex requests, assigns job IDs, and processes them sequentially
in a single daemon worker thread. Jobs persist for the server session lifetime.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger("rifflux.indexing")


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
        }


class BackgroundIndexer:
    """Sequential job queue for background reindex operations.

    - ``submit()`` enqueues a job and returns immediately.
    - A single daemon thread processes jobs one at a time.
    - All completed/failed jobs are retained for the server session.
    """

    def __init__(self, run_reindex: Callable[[IndexRequest], dict[str, Any]]) -> None:
        self._run_reindex = run_reindex
        self._lock = threading.Lock()
        self._jobs: dict[str, IndexJob] = {}
        self._queue: deque[str] = deque()
        self._worker: threading.Thread | None = None

    # -- public API ----------------------------------------------------------

    def submit(self, request: IndexRequest) -> IndexJob:
        """Enqueue a reindex job. Returns the job immediately (status=queued)."""
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
        """Process jobs from the queue sequentially until empty."""
        while True:
            with self._lock:
                if not self._queue:
                    return  # thread exits; restarted on next submit()
                job_id = self._queue.popleft()
                job = self._jobs[job_id]
                job.status = "running"
                job.started_at = time.monotonic()

            logger.debug("background job %s running", job_id)
            try:
                result = self._run_reindex(job.request)
                with self._lock:
                    job.status = "completed"
                    job.result = result
                    job.completed_at = time.monotonic()
                logger.debug("background job %s completed", job_id)
            except Exception as exc:
                logger.exception("background job %s failed", job_id)
                with self._lock:
                    job.status = "failed"
                    job.error = str(exc)
                    job.completed_at = time.monotonic()
