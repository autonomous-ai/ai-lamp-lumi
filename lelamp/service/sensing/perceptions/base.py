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

    _queue: queue.Queue = queue.Queue()
    _worker_started: bool = False
    _worker_lock: threading.Lock = threading.Lock()

    @classmethod
    def _ensure_worker(cls) -> None:
        with cls._worker_lock:
            if cls._worker_started:
                return
            cls._worker_started = True
            threading.Thread(
                target=cls._worker_loop, daemon=True, name="perception-worker"
            ).start()

    @classmethod
    def _worker_loop(cls) -> None:
        while True:
            perception, frame = cls._queue.get()
            try:
                perception._check_impl(frame)
            except Exception:
                logger.exception("[%s] check error", type(perception).__name__)
            finally:
                with perception._lock:
                    perception._busy = False
                cls._queue.task_done()

    def __init__(self, send_event: Callable):
        self._send_event = send_event
        self._busy = False
        self._lock = threading.Lock()

    def check(self, frame: npt.NDArray[np.uint8]) -> None:
        """Non-blocking entry point. Skips if a previous check is still queued or running."""
        with self._lock:
            if self._busy:
                return
            self._busy = True
        Perception._ensure_worker()
        Perception._queue.put((self, frame))

    @abstractmethod
    def _check_impl(self, frame: npt.NDArray[np.uint8]) -> None:
        """Run detection on a single frame. Called by the FIFO worker thread."""
