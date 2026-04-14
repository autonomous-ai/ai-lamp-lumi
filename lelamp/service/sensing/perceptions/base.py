import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from abc import ABC, abstractmethod
from typing import Callable

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)


class Perception(ABC):
    """Base class for a single camera-frame perception check.

    check() is non-blocking: it submits _check_impl() to a shared thread
    pool. A per-instance busy guard ensures each perception has at most one
    task in the pool, preserving FIFO order per instance while different
    perceptions run in parallel.
    """

    _pool: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=1)

    def __init__(self, send_event: Callable):
        self._send_event = send_event
        self._busy: bool = False
        self._lock: threading.Lock = threading.Lock()

    def check(self, frame: npt.NDArray[np.uint8]) -> None:
        """Non-blocking entry point. Skips if a previous check is still queued or running."""
        with self._lock:
            if self._busy:
                return
            self._busy = True

        try:
            Perception._pool.submit(self._run, frame)
        except RuntimeError:
            with self._lock:
                self._busy = False

    def _run(self, frame: npt.NDArray[np.uint8]) -> None:
        try:
            self._check_impl(frame)
        except Exception:
            logger.exception("[%s] check error", type(self).__name__)
        finally:
            with self._lock:
                self._busy = False

    @abstractmethod
    def _check_impl(self, frame: npt.NDArray[np.uint8]) -> None:
        """Run detection on a single frame. Called in the shared thread pool."""
