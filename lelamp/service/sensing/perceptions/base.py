import logging
import queue
import threading
from abc import ABC, abstractmethod
from typing import Callable

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)


class Perception(ABC):
    """Base class for a single camera-frame perception check.

    check() is non-blocking: it enqueues _check_impl() onto a shared FIFO
    worker thread so perceptions execute in the order they are submitted.
    If the previous invocation of the same perception is still pending or
    running, the call is skipped.
    """

    def __init__(self, send_event: Callable):
        self._send_event = send_event
        self._busy: bool = False
        self._lock: threading.Lock = threading.Lock()
        self._queue: queue.Queue[npt.NDArray[np.uint8]] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._worker_lock: threading.Lock = threading.Lock()
        self._stopped: threading.Event = threading.Event()

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker_thread is not None:
                return

            self._stopped.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop, daemon=True, name="perception-worker"
            )
            self._worker_thread.start()

    def __del__(self):
        self._stopped.set()
        if self._worker_thread is not None:
            self._worker_thread.join()

    def _worker_loop(self) -> None:
        while not self._stopped.is_set():
            frame = self._queue.get()
            try:
                self._check_impl(frame)
            except Exception:
                logger.exception("check error")
            finally:
                with self._lock:
                    self._busy = False
                self._queue.task_done()

    def check(self, frame: npt.NDArray[np.uint8]) -> None:
        """Non-blocking entry point. Skips if a previous check is still queued or running."""
        with self._lock:
            if self._busy:
                return
            self._busy = True
        self._ensure_worker()
        self._queue.put(frame)

    @abstractmethod
    def _check_impl(self, frame: npt.NDArray[np.uint8]) -> None:
        """Run detection on a single frame. Called by the FIFO worker thread."""
