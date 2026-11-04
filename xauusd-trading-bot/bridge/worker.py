"""Background order execution, so the webhook can be answered within TradingView's ~3 s timeout.

One daemon thread takes signals from a bounded FIFO queue and runs Engine.execute for each, so orders are placed
strictly one at a time and in arrival order (an entry followed by its close can't be reordered).
"""
from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from typing import Any

from .engine import Engine, Result
from .journal import utc_now
from .signals import Signal

log = logging.getLogger(__name__)
_STOP = object()


class OrderWorker:
    def __init__(self, engine: Engine, maxsize: int = 100, keep: int = 20):
        self.engine = engine
        self._q: queue.Queue = queue.Queue(maxsize)
        self._recent: deque = deque(maxlen=keep)
        self._recent_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="order-worker", daemon=True)
        self._thread.start()

    def submit(self, envelope: dict[str, Any], sig: Signal) -> bool:
        """Queue a prechecked signal. False if the queue is full (the caller answers 503)."""
        try:
            self._q.put_nowait((envelope, sig))
            return True
        except queue.Full:
            log.error("order queue full (%d), dropping %s", self._q.maxsize, sig.dedupe_key)
            return False

    def depth(self) -> int:
        return self._q.qsize()

    def recent_results(self) -> list[dict]:
        with self._recent_lock:
            return list(self._recent)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def stop(self, timeout: float = 30.0) -> bool:
        """Finish everything already queued, then exit. True if the thread ended within the timeout."""
        try:
            self._q.put(_STOP, timeout=timeout)
        except queue.Full:
            log.error("order worker did not drain within %.0fs", timeout)
            return False
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is _STOP:
                    return
                envelope, sig = item
                try:
                    res = self.engine.execute(envelope, sig)
                except Exception as exc:  # noqa: BLE001 - the worker thread must never die
                    log.exception("order worker: unexpected error for %s", sig.dedupe_key)
                    res = Result(500, "error", f"worker error: {exc}")
                with self._recent_lock:
                    self._recent.append({"time": utc_now().isoformat(timespec="seconds"),
                                         "key": sig.dedupe_key, "status": res.status, "detail": res.detail})
            finally:
                self._q.task_done()
