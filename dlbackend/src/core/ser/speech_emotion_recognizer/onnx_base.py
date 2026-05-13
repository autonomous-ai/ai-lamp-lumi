"""ONNX-backed SER base class.

Concentrates everything that's specific to running an SER model through
ONNX Runtime: model-file resolution (local cache → URL → FunASR export
fallback), session creation, and the actual ``session.run`` call.

Concrete engines (see :mod:`emotion2vec`) only need to declare four
class attributes; no method overrides are required.
"""

from __future__ import annotations

import logging
import os
import shutil
import urllib.request
import warnings
from pathlib import Path
from typing import Any, Sequence, Union

import numpy as np

try:
    import onnxruntime as ort
except ImportError:
    ort = None  # type: ignore[assignment]

from .base import SpeechEmotionRecognizer

logger = logging.getLogger(__name__)



_DEFAULT_PROVIDER_PREFERENCE = (
    "CUDAExecutionProvider",       # NVIDIA GPUs (Linux/Windows)
    "ROCMExecutionProvider",       # AMD GPUs (Linux)
    "DmlExecutionProvider",        # Windows DirectML (Intel/AMD/NVIDIA)
    "CoreMLExecutionProvider",     # Apple Silicon / Intel Mac
    "CPUExecutionProvider",        # always-on fallback
)


_PROVIDER_ALIASES = {
    "cuda": "CUDAExecutionProvider",
    "gpu": "CUDAExecutionProvider",
    "rocm": "ROCMExecutionProvider",
    "dml": "DmlExecutionProvider",
    "directml": "DmlExecutionProvider",
    "coreml": "CoreMLExecutionProvider",
    "mps": "CoreMLExecutionProvider",
    "cpu": "CPUExecutionProvider",
}


def _normalize_provider_name(name: str) -> str:
    """Map shortcut names like ``"cuda"`` to ORT's canonical strings."""
    key = name.strip()
    if not key:
        return ""
    return _PROVIDER_ALIASES.get(key.lower(), key)


def _resolve_providers(
    requested: Union[Sequence[str], str, None],
) -> list[str]:
    """Pick an ORT provider list that the local install actually supports.

    Args:
        requested: User preference. ``None`` triggers auto-detection
            using :data:`_DEFAULT_PROVIDER_PREFERENCE`. A string is
            parsed as a comma-separated list. Aliases like ``"cuda"``
            are accepted (see :data:`_PROVIDER_ALIASES`).

    Returns:
        Ordered list of provider names (always ends with
        ``CPUExecutionProvider`` so ORT has a safety net).
    """
    if ort is None:
        return ["CPUExecutionProvider"]

    available = set(ort.get_available_providers())

    if requested is None:
        preference = _DEFAULT_PROVIDER_PREFERENCE
    else:
        if isinstance(requested, str):
            raw_items = [tok for tok in requested.split(",") if tok.strip()]
        else:
            raw_items = list(requested)
        preference = tuple(
            name for name in (_normalize_provider_name(x) for x in raw_items) if name
        )
        if not preference:
            preference = _DEFAULT_PROVIDER_PREFERENCE

    resolved: list[str] = []
    for name in preference:
        if name in available and name not in resolved:
            resolved.append(name)

    if "CPUExecutionProvider" not in resolved:
        resolved.append("CPUExecutionProvider")

    return resolved


class OnnxSpeechEmotionRecognizer(SpeechEmotionRecognizer):
    """SER engine backed by an ONNX Runtime CPU session.

    The ONNX model is expected to accept a single mono waveform input of
    shape ``[B, T]`` at :attr:`sample_rate` and produce a softmax score
    output of shape ``[B, num_classes]``.

    Subclasses MUST override:

    * :attr:`DEFAULT_LOCAL_MODEL_PATH` -- on-disk cache of the ONNX file.
    * :attr:`DEFAULT_LABELS_PATH` (inherited from :class:`SpeechEmotionRecognizer`).

    Subclasses MAY override:

    * :attr:`DEFAULT_REMOTE_MODEL_PATH` -- http(s) URL to fetch a
      pre-exported ONNX. Leave empty to skip remote download and rely on
      FunASR export.
    * :attr:`MODEL_ID` -- FunASR/HuggingFace identifier consumed by the
      :mod:`core.ser.prepare_onnx` export fallback.
    * :attr:`INPUT_NAME`, :attr:`PRIMARY_OUTPUT_NAME` -- if the ONNX
      graph uses different tensor names.

    Resolution order for the ONNX file (see :meth:`_prepare_model`):

    1. Caller-supplied ``model_path`` (local file or ``http(s)://`` URL).
    2. Cached file at ``DEFAULT_LOCAL_MODEL_PATH``.
    3. Remote download from ``DEFAULT_REMOTE_MODEL_PATH``.
    4. Build via :func:`core.ser.prepare_onnx.prepare_onnx_export` using
       ``MODEL_ID``.
    """

    DEFAULT_LOCAL_MODEL_PATH: Path = Path("")
    DEFAULT_REMOTE_MODEL_PATH: str = ""
    MODEL_ID: str = ""

    INPUT_NAME: str = "input"
    PRIMARY_OUTPUT_NAME: str = "scores"

    def __init__(
        self,
        model_path: Union[str, Path, None] = None,
        labels_path: Union[str, Path, None] = None,
        sample_rate: int = 16000,
        intra_op_threads: int = 4,
        providers: Union[Sequence[str], str, None] = None,
    ) -> None:
        """
        Args:
            model_path: Local path or http(s) URL to the ONNX file.
                ``None`` triggers the resolution order documented on the
                class.
            labels_path: Override path to labels file
                (default: :attr:`DEFAULT_LABELS_PATH`).
            sample_rate: Model input sample rate (default 16 kHz).
            intra_op_threads: ONNX Runtime intra-op thread count.
            providers: ONNX Runtime execution providers. ``None`` =
                auto-detect (CUDA → ROCm → DirectML → CoreML → CPU
        """
        self._sample_rate = int(sample_rate)

        self.model_path: str = self._prepare_model(model_path)
        super().__init__(labels_path=labels_path)
        self.session = self._create_session(
            self.model_path, intra_op_threads, providers
        )
        self.providers: list[str] = list(self.session.get_providers())

        # Bind the actual graph I/O names (graceful fallback if the
        # exported graph used a different scheme).
        output_names = [o.name for o in self.session.get_outputs()]
        self.output_name = (
            self.PRIMARY_OUTPUT_NAME
            if self.PRIMARY_OUTPUT_NAME in output_names
            else output_names[0]
        )
        input_names = [i.name for i in self.session.get_inputs()]
        if self.INPUT_NAME not in input_names:
            self.INPUT_NAME = input_names[0]

        msg = (
            f"[SER] engine='{self.ENGINE_NAME}' class={type(self).__name__} "
            f"model_path={self.model_path} input='{self.INPUT_NAME}' "
            f"output='{self.output_name}' labels={self.num_classes} "
            f"providers={self.providers}"
        )
        logger.info(msg)
        print(msg, flush=True)

    # ------------------------------------------------------------------
    # SpeechEmotionRecognizer interface
    # ------------------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def predict_from_waveform(self, waveform: np.ndarray) -> np.ndarray:
        wav = np.asarray(waveform, dtype=np.float32).reshape(-1)
        if wav.size == 0:
            raise ValueError("Empty waveform (0 samples).")
        x = wav[np.newaxis, :]  # [1, T]
        scores = self.session.run([self.output_name], {self.INPUT_NAME: x})[0]
        return np.asarray(scores[0], dtype=np.float32)


    def _prepare_model(self, model_path: Union[str, Path, None]) -> str:
        default_local = Path(self.DEFAULT_LOCAL_MODEL_PATH)
        if not str(default_local):
            raise RuntimeError(
                f"Engine '{self.ENGINE_NAME}' has no DEFAULT_LOCAL_MODEL_PATH."
            )
        default_local.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(model_path, Path):
            model_path = str(model_path)

        if model_path:
            if str(model_path).startswith("http"):
                if not default_local.exists():
                    self._download_model(model_path, default_local)
                return str(default_local)
            actual_path = Path(model_path)
            if actual_path.exists():
                return str(actual_path)
            warnings.warn(
                f"model_path='{model_path}' does not exist; falling back to defaults.",
                UserWarning,
            )

        if default_local.exists():
            return str(default_local)

        if self.DEFAULT_REMOTE_MODEL_PATH:
            try:
                self._download_model(self.DEFAULT_REMOTE_MODEL_PATH, default_local)
                return str(default_local)
            except Exception as exc:
                logger.warning(
                    "SER remote download failed (%s); will try FunASR export.", exc
                )

        self._build_onnx(default_local)
        if not default_local.exists():
            raise RuntimeError(
                f"Failed to materialize ONNX model at {default_local}"
            )
        return str(default_local)

    @staticmethod
    def _download_model(url: str, dest_path: Path) -> None:
        """Atomic streaming download (temp file + rename)."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path.with_suffix(dest_path.suffix + f".part.{os.getpid()}")
        try:
            with urllib.request.urlopen(url) as response, open(tmp_path, "wb") as out:
                shutil.copyfileobj(response, out)
            os.replace(tmp_path, dest_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _build_onnx(self, dest_path: Path) -> None:
        """Last-resort: build the ONNX from a FunASR checkpoint."""
        if not self.MODEL_ID:
            raise RuntimeError(
                f"Engine '{self.ENGINE_NAME}' has no MODEL_ID; cannot build ONNX."
            )

        from core.ser.prepare_onnx import prepare_onnx_export

        logger.info(
            "[SER] Building ONNX via FunASR export: model_id=%s -> %s",
            self.MODEL_ID,
            dest_path,
        )
        prepare_onnx_export(
            model_id=self.MODEL_ID,
            output_path=dest_path,
        )

    def _create_session(
        self,
        model_path: str,
        n_threads: int,
        providers: Union[Sequence[str], str, None],
    ) -> Any:
        if ort is None:
            raise ImportError(
                "onnxruntime is required for OnnxSpeechEmotionRecognizer."
            )
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = int(n_threads)
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        resolved = _resolve_providers(providers)
        logger.info(
            "[SER] requested providers=%r -> resolved=%r (available=%r)",
            providers,
            resolved,
            ort.get_available_providers(),
        )
        return ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=resolved,
        )
