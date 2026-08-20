"""Background job execution for long pipeline operations (PRD §22: generation runs as a background job)."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

log = logging.getLogger(__name__)


class JobBusy(RuntimeError):
    pass


class JobRunner:
    """Thread-pool runner; at most one running job per project."""

    def __init__(self, max_workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ttcf-job")
        self._running: dict[str, Future] = {}
        self._lock = threading.Lock()

    def submit(self, key: str, fn: Callable[[], None]) -> None:
        with self._lock:
            fut = self._running.get(key)
            if fut is not None and not fut.done():
                raise JobBusy(f"a job is already running for {key}")

            def _wrapped():
                try:
                    fn()
                except Exception:  # noqa: BLE001 — errors are persisted on the project by the service
                    log.exception("job %s failed", key)

            self._running[key] = self._pool.submit(_wrapped)

    def is_running(self, key: str) -> bool:
        with self._lock:
            fut = self._running.get(key)
            return fut is not None and not fut.done()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class InlineJobRunner(JobRunner):
    """Runs jobs synchronously (tests / CLI)."""

    def __init__(self):
        self._running = {}
        self._lock = threading.Lock()

    def submit(self, key: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("inline job %s failed", key)

    def is_running(self, key: str) -> bool:
        return False

    def shutdown(self) -> None:
        pass
