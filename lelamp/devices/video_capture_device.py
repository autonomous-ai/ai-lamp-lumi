import logging
import threading
import time
from typing import cast, override

import cv2
import numpy as np
import numpy.typing as npt

from .base import IDevice
from .models import VideoCaptureDeviceInfo, VideoCaptureDeviceResponse


class VideoCaptureDeviceBase(
    IDevice[VideoCaptureDeviceInfo, VideoCaptureDeviceResponse]
):
    def __init__(
        self,
        device_info: VideoCaptureDeviceInfo,
        name: str | None = None,
    ):
        super().__init__(device_info, name)

        self._fps: int | None = device_info.fps
        self._max_width: int | None = device_info.max_width
        self._max_height: int | None = device_info.max_height
        self._rotate: float | None = device_info.rotate

    def capture(
        self, need_description: bool = False
    ) -> VideoCaptureDeviceResponse | None:
        """Capture the image (sync mode)"""
        raise NotImplementedError("capture method is not implemented")


class LocalVideoCaptureDevice(VideoCaptureDeviceBase):
    runable: bool = True

    def __init__(
        self,
        device_info: VideoCaptureDeviceInfo,
        name: str | None = None,
    ):
        super().__init__(device_info, name)

        self._last_response: VideoCaptureDeviceResponse | None = None

        self._thread: threading.Thread | None = None
        self._lock: threading.Lock = threading.Lock()
        self._stopped: threading.Event = threading.Event()

        # When > 0, capture runs at full FPS; otherwise throttles to save CPU
        self._active_consumers: int = 0
        self._consumers_lock: threading.Lock = threading.Lock()

        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    @property
    def last_frame(self) -> npt.NDArray[np.uint8] | None:
        with self._lock:
            if self._last_response and self._last_response.frame is not None:
                return self._last_response.frame.copy()
            else:
                return None

    @property
    def last_frame_description(self) -> str | None:
        with self._lock:
            if self._last_response:
                return self._last_response.frame_description
            else:
                return None

    @property
    def last_response(self) -> VideoCaptureDeviceResponse | None:
        with self._lock:
            if self._last_response:
                return self._last_response.model_copy(deep=True)
            else:
                return None

    @last_response.setter
    def last_response(self, new_frame_info: VideoCaptureDeviceResponse | None):
        with self._lock:
            if new_frame_info:
                self._last_response = new_frame_info.model_copy(deep=True)
            else:
                self._last_response = None

    @override
    def capture(
        self, need_description: bool = False
    ) -> VideoCaptureDeviceResponse | None:
        if self._thread is None:
            msg = f"{self.__class__.__name__} has not started"
            self._logger.info(msg)
            raise RuntimeError(msg)

        return self.last_response

    @override
    def start(self) -> None:
        if self._thread is not None:
            self._logger.info(f"{self.__class__.__name__} has already started")
            return

        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._video_capture_loop,
            name=f"{self.__class__.__name__} video capture loop",
            daemon=True,
        )
        self._thread.start()

    def _video_capture_loop(self):

        device_id = self.device_info.device_id

        if isinstance(device_id, str) and device_id.isdigit():
            device_id = int(device_id)

        video_capture = cv2.VideoCapture(device_id, cv2.CAP_V4L2)
        if not video_capture.isOpened():
            # Fallback: try default backend in case hardware changes
            video_capture = cv2.VideoCapture(device_id)

        if not video_capture.isOpened():
            raise ValueError(
                f"Failed to open video capture device: {self.device_info.device_id}"
            )

        # Force MJPEG format — some USB webcams (e.g. Generalplus) fail read()
        # with the default YUYV format on Pi 5 but work fine with MJPEG.
        video_capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        w = int(video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        device_fps = video_capture.get(cv2.CAP_PROP_FPS)

        new_w = min(w, self._max_width) if self._max_width else w
        new_h = min(h, self._max_height) if self._max_height else h

        size_ratio = min(new_w / w, new_h / h)

        last_time_frame = time.time()
        skip_time = (
            1 / self._fps if self._fps is not None and self._fps < device_fps else 0
        )

        # Idle capture interval — only grab a frame every 2s when no streaming clients
        idle_interval = 2.0

        self._logger.info("Starting video capture device loop")
        try:
            while not self._stopped.is_set():
                # Throttle when no active consumers — sleep BEFORE read to avoid
                # burning CPU on blocking video_capture.read() at device FPS
                with self._consumers_lock:
                    has_consumers = self._active_consumers > 0
                if not has_consumers:
                    elapsed = time.time() - last_time_frame
                    if elapsed < idle_interval:
                        self._stopped.wait(min(idle_interval - elapsed, 0.5))
                        continue
                    # Flush stale frames from device buffer after idle sleep
                    video_capture.grab()
                    video_capture.grab()

                ret, frame = video_capture.read()

                if not ret:
                    # Some webcams need a few warmup reads before producing frames
                    self._logger.warning("Camera read() failed, retrying in 1s...")
                    time.sleep(1)
                    ret, frame = video_capture.read()
                    if not ret:
                        self._logger.error("Camera read() failed twice, exiting loop")
                        break

                frame_ts = time.time()

                if frame_ts - last_time_frame < skip_time:
                    continue
                else:
                    last_time_frame = frame_ts

                if size_ratio < 1.0:
                    frame = cv2.resize(frame, None, fx=size_ratio, fy=size_ratio)

                if self._rotate is not None:
                    if self._rotate == 180.0:
                        frame = cv2.rotate(frame, cv2.ROTATE_180)
                    elif self._rotate == 90.0:
                        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                    elif self._rotate == -90.0:
                        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    else:
                        h, w = frame.shape[:2]
                        center = (w // 2, h // 2)
                        M = cv2.getRotationMatrix2D(center, self._rotate, 1.0)
                        frame = cv2.warpAffine(frame, M, (w, h))

                frame = cast(npt.NDArray[np.uint8], frame)
                response = VideoCaptureDeviceResponse(frame=frame)

                for callback in self.callbacks:
                    callback(self.device_info, response)

                self.last_response = response
        finally:
            video_capture.release()

    def acquire_consumer(self):
        """Register an active consumer (e.g. MJPEG stream) for full-FPS capture."""
        with self._consumers_lock:
            self._active_consumers += 1

    def release_consumer(self):
        """Unregister an active consumer — throttles capture when none remain."""
        with self._consumers_lock:
            self._active_consumers = max(0, self._active_consumers - 1)

    @override
    def stop(self):
        super().stop()
        self._stopped.set()
