from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Type, TYPE_CHECKING, Union
from collections import defaultdict
import shutil
import urllib.request
import warnings
import logging

import numpy as np
try:
    import onnxruntime as ort
except ImportError:  # pragma: no cover - handled at runtime
    ort = None  # type: ignore[assignment]

try:
    import soundfile as sf
except ImportError:  # pragma: no cover - handled at runtime
    sf = None  # type: ignore[assignment]

try:
    from scipy.signal import resample_poly
except ImportError:  # pragma: no cover - handled at runtime
    resample_poly = None  # type: ignore[assignment]

if TYPE_CHECKING:
    import onnxruntime as ort_types
from .speaker_db import BaseSpeakerDB, SpeakerDB
from . import audio_preprocess

logger = logging.getLogger(__name__)

AudioInput = Union[str, Path]
ChunkType = Union[np.ndarray, Sequence[float]]

AUDIO_RECOGNITION_BASE_DIR = Path(__file__).parent
DEFAULT_DB_PATH = AUDIO_RECOGNITION_BASE_DIR / "speaker_db" / "speaker_db.json"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_WINDOW_TYPE = "hamming"
DEFAULT_DITHER = 0.0
DEFAULT_WAVEFORM_NORM = False
DEFAULT_INTRA_OP_THREADS = 4
DEFAULT_BATCH_SIZE = 8

# Robust embedding preprocessing defaults (see audio_preprocess.py).
DEFAULT_USE_NOISEREDUCE = True
DEFAULT_USE_VAD = True
DEFAULT_USE_HPF = False
DEFAULT_USE_RMS_NORMALIZE = True
DEFAULT_HPF_CUTOFF_HZ = 80.0
DEFAULT_RMS_TARGET = 0.1

# Speech-gate thresholds applied after VAD strips head/tail silence.
DEFAULT_MIN_DURATION_SEC = 0.5
DEFAULT_MIN_VOICE_RATIO = 0.7

# Desired per-chunk duration range when splitting long audio. Short audio
# (<= max, or <= 2*min when that exceeds max) stays as a single window.
DEFAULT_MIN_CHUNK_SEC = 5.0
DEFAULT_MAX_CHUNK_SEC = 8.0

# Environment variable used by `create_audio_recognizer` to pick the engine.
ENV_AUDIO_RECOGNIZER_ENGINE = "AUDIO_RECOGNIZER_ENGINE"


class BaseAudioRecognizer:
    """ONNX speaker recognition base service using NumPy-based preprocessing.

    Concrete engines (WeSpeaker ResNet34, ECAPA-TDNN-512, ...) are implemented
    as subclasses overriding ``ENGINE_NAME``, ``DEFAULT_REMOTE_MODEL_PATH`` and
    ``DEFAULT_LOCAL_MODEL_PATH``. All other logic (fbank extraction, ONNX
    session, register / recognize, batching, aggregation) is shared here.
    """

    # Subclasses must override.
    ENGINE_NAME: str = "base"
    DEFAULT_REMOTE_MODEL_PATH: str = ""
    DEFAULT_LOCAL_MODEL_PATH: Path = Path("")

    def __init__(
        self,
        model_path: str | Path | None = None,
        db_path: str | Path = DEFAULT_DB_PATH,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        window_type: str = DEFAULT_WINDOW_TYPE,
        dither: float = DEFAULT_DITHER,
        waveform_norm: bool = DEFAULT_WAVEFORM_NORM,
        intra_op_threads: int = DEFAULT_INTRA_OP_THREADS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        *,
        use_noisereduce: bool = DEFAULT_USE_NOISEREDUCE,
        use_vad: bool = DEFAULT_USE_VAD,
        use_hpf: bool = DEFAULT_USE_HPF,
        use_rms_normalize: bool = DEFAULT_USE_RMS_NORMALIZE,
        hpf_cutoff_hz: float = DEFAULT_HPF_CUTOFF_HZ,
        rms_target: float = DEFAULT_RMS_TARGET,
        min_duration_sec: float = DEFAULT_MIN_DURATION_SEC,
        min_voice_ratio: float = DEFAULT_MIN_VOICE_RATIO,
        min_chunk_sec: float = DEFAULT_MIN_CHUNK_SEC,
        max_chunk_sec: float = DEFAULT_MAX_CHUNK_SEC,
    ) -> None:
        """
        Args:
            model_path: Path to ONNX model file.
            db_path: Path to local JSON embedding database.
            sample_rate: Target sample rate used by the model.
            window_type: Window type used in fbank extraction.
            dither: Dither value used in fbank extraction.
            waveform_norm: Whether to peak-normalize input waveform.
            intra_op_threads: ONNX Runtime intra-op thread count.
            batch_size: Mini-batch size for ONNX embedding inference.
            use_noisereduce: Enable ``noisereduce`` before VAD.
            use_vad: Enable silero-VAD to strip head/tail non-voice and gate.
            use_hpf: Enable 80 Hz high-pass filter (rumble / DC removal).
            use_rms_normalize: Scale waveform to a fixed RMS loudness.
            hpf_cutoff_hz: High-pass cutoff frequency in Hz.
            rms_target: Target RMS magnitude after normalization.
            min_duration_sec: Reject audio shorter than this after strip-VAD.
            min_voice_ratio: Reject audio when voice/total ratio is below.
            min_chunk_sec: Lower bound for per-chunk duration when splitting
                long audio. Short/mid-length audio is kept as one window.
            max_chunk_sec: Upper bound for per-chunk duration when splitting;
                audio longer than ``max(max_chunk_sec, 2*min_chunk_sec)`` is
                split into equal contiguous chunks in
                ``[min_chunk_sec, max_chunk_sec]``.
        """
        self.model_path = self._prepare_model(model_path)
        self.db_path = Path(db_path)
        self.sample_rate = sample_rate
        self.window_type = window_type
        self.dither = dither
        self.waveform_norm = waveform_norm
        self.batch_size = max(1, int(batch_size))

        self.use_noisereduce = bool(use_noisereduce)
        self.use_vad = bool(use_vad)
        self.use_hpf = bool(use_hpf)
        self.use_rms_normalize = bool(use_rms_normalize)
        self.hpf_cutoff_hz = float(hpf_cutoff_hz)
        self.rms_target = float(rms_target)
        self.min_duration_sec = float(min_duration_sec)
        self.min_voice_ratio = float(min_voice_ratio)
        self.min_chunk_sec = float(min_chunk_sec)
        self.max_chunk_sec = float(max_chunk_sec)

        self.session = self._create_session(self.model_path, intra_op_threads)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.db: BaseSpeakerDB = SpeakerDB(db_path)

        # Visibility: surface which engine + model path is loaded. Use the
        # standard logger so callers can route it, and also print() so CLI
        # users see it even without a logging config.
        msg = (
            f"[AudioRecognizer] engine='{self.ENGINE_NAME}' "
            f"class={type(self).__name__} model_path={self.model_path}"
        )
        logger.info(msg)
        print(msg, flush=True)

    def _prepare_model(self, model_path: str | None = None) -> str:
        """Prepares and ensures local model file is present. If not,
        downloads from remote and saves to default local path.

        Args:
            model_path: Path to local model file or remote URL. When ``None``,
                falls back to engine defaults declared on the subclass.

        Returns:
            Path string to actual local model.
        """
        default_local = Path(self.DEFAULT_LOCAL_MODEL_PATH)
        default_remote = self.DEFAULT_REMOTE_MODEL_PATH

        if not str(default_local) or not default_remote:
            raise RuntimeError(
                f"Engine '{self.ENGINE_NAME}' is missing DEFAULT_LOCAL_MODEL_PATH "
                "or DEFAULT_REMOTE_MODEL_PATH. Use a concrete subclass."
            )

        def download_to_local(url, dest_path: Path) -> None:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url) as response, open(dest_path, "wb") as out_file:
                shutil.copyfileobj(response, out_file)

        if model_path is None:
            warnings.warn(
                f"model_path is None, switching to default local model path at {default_local}",
                UserWarning,
            )
            model_path = str(default_local)

        if isinstance(model_path, Path):
            model_path = str(model_path)
        if model_path.startswith("http"):
            if not default_local.exists():
                try:
                    download_to_local(model_path, default_local)
                except Exception:
                    download_to_local(default_remote, default_local)
            return str(default_local)

        # Local path given
        actual_path = Path(model_path)
        if actual_path.exists():
            return str(actual_path)

        if not default_local.exists():
            try:
                download_to_local(default_remote, default_local)
            except Exception as e:
                raise RuntimeError(f"Failed to download model from remote: {e}")
        return str(default_local)
    
    def _create_session(self, model_path: str, n_threads: int) -> Any:
        """Create ONNX Runtime session for CPU inference."""
        if ort is None:
            raise ImportError("onnxruntime is required to create AudioRecognizer session.")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = n_threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.add_session_config_entry("session.dynamic_block_base", "4")
        return ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
    def load_from_onnx(self, model_path: Union[str, Path], intra_op_threads: int = 4) -> None:
        """Reload ONNX model and refresh I/O tensor names."""
        self.model_path = str(model_path)
        self.session = self._create_session(self.model_path, intra_op_threads)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def _load_db(self) -> None:
        """Deprecated: DB is managed by SpeakerDB."""
        return None

    def _save_db(self) -> None:
        """Deprecated: DB is managed by SpeakerDB."""
        return None

    # Audio loading and preprocessing
    def _load_waveform(self, wav_path: AudioInput) -> np.ndarray:
        """Load audio file, convert to mono, normalize/resample to target rate.

        Args:
            wav_path: Path to wav/audio file.

        Returns:
            1D float32 NumPy waveform.
        """
        if sf is None:
            raise ImportError("soundfile is required to load waveform audio files.")
        waveform, orig_sr = sf.read(str(wav_path), dtype="float32")  # [T] or [T, C]
        waveform = self._to_mono(waveform)
        if self.waveform_norm:
            peak = float(np.max(np.abs(waveform))) if waveform.size > 0 else 0.0
            if peak > 1e-12:
                waveform = waveform / peak
        if orig_sr != self.sample_rate:
            waveform = self._resample(waveform, orig_sr=orig_sr, new_sr=self.sample_rate)
        return waveform.astype(np.float32)  # [T]

    @staticmethod
    def _to_mono(waveform: np.ndarray) -> np.ndarray:
        """Convert waveform to mono channel."""
        if waveform.ndim == 1:
            return waveform  # [T]
        if waveform.ndim == 2:
            return waveform.mean(axis=1)  # [T, C] -> [T]
        raise ValueError("Waveform must be 1D [time] or 2D [time, channels].")

    @staticmethod
    def _resample(waveform: np.ndarray, orig_sr: int, new_sr: int) -> np.ndarray:
        """Resample waveform from orig_sr to new_sr using polyphase filter."""
        if orig_sr == new_sr:
            return waveform  # [T]
        if resample_poly is None:
            raise ImportError("scipy is required for waveform resampling.")
        gcd = math.gcd(int(orig_sr), int(new_sr))
        up = int(new_sr // gcd)
        down = int(orig_sr // gcd)
        return resample_poly(waveform, up, down).astype(np.float32)  # [T']

    def _compute_fbank(
        self, waveform: np.ndarray
    ) -> np.ndarray:
        """
        Compute Kaldi fbank with kaldi-native-fbank.
        Input supports np.ndarray, return matches _compute_fbank:
        np.ndarray with shape [1, T, 80], dtype float32.
        """
        try:
            import kaldi_native_fbank as knf
        except ImportError as exc:
            raise ImportError(
                "kaldi-native-fbank is not installed. "
                "Install it to use _compute_fbank_with_native."
            ) from exc

        wav = np.asarray(waveform, dtype=np.float32)  # [T] or [T, C]

        if wav.ndim == 2:
            # [time, channels] -> mono [time]
            wav = wav.mean(axis=1)  # [T]
        elif wav.ndim != 1:
            raise ValueError("waveform must be 1D [time] or 2D [time, channels].")

        opts = knf.FbankOptions()
        opts.frame_opts.samp_freq = float(self.sample_rate)
        opts.frame_opts.frame_length_ms = 25.0
        opts.frame_opts.frame_shift_ms = 10.0
        opts.frame_opts.dither = float(self.dither)
        opts.frame_opts.window_type = self.window_type
        opts.mel_opts.num_bins = 80

        fbank = knf.OnlineFbank(opts)
        fbank.accept_waveform(self.sample_rate, wav)
        fbank.input_finished()

        if fbank.num_frames_ready <= 0:
            return np.zeros((1, 0, 80), dtype=np.float32)

        frames = [fbank.get_frame(i) for i in range(fbank.num_frames_ready)]  # list[[80]]
        feat = np.stack(frames, axis=0).astype(np.float32)  # [T, 80]
        feat = feat - np.mean(feat, axis=0, keepdims=True)  # CMN
        return np.asarray(feat[None, :, :], dtype=np.float32)  # [1, T, 80]


    def _preprocess_and_split(self, waveform: np.ndarray) -> List[np.ndarray]:
        """Run preprocess + speech gate, then emit one or a few windows.

        Short / mid-length audio yields a single window (matches WeSpeaker
        CLI behavior); longer audio is split into equal contiguous chunks
        in ``[self.min_chunk_sec, self.max_chunk_sec]``.

        Raises:
            audio_preprocess.PreprocessRejected: Speech gate rejected the
                clip. Propagated up so the HTTP layer can surface the
                structured measurements (duration, voice_ratio, ...).
        """
        clean = audio_preprocess.preprocess_for_embedding(
            np.asarray(waveform, dtype=np.float32),
            self.sample_rate,
            use_hpf=self.use_hpf,
            use_noisereduce=self.use_noisereduce,
            use_vad=self.use_vad,
            use_rms=self.use_rms_normalize,
            hpf_cutoff_hz=self.hpf_cutoff_hz,
            rms_target=self.rms_target,
            min_duration_sec=self.min_duration_sec,
            min_voice_ratio=self.min_voice_ratio,
        )
        return audio_preprocess.split_by_duration(
            clean,
            self.sample_rate,
            min_sec=self.min_chunk_sec,
            max_sec=self.max_chunk_sec,
        )

    def _prepare_waveforms_from_paths(self, wav_paths: List[AudioInput]) -> List[np.ndarray]:
        """Load each wav path, preprocess + gate, emit one-or-few windows.

        Multi-file tolerance: a single file that fails the speech gate is
        logged and skipped so a good file can still enroll. If **every**
        file is rejected the first rejection is re-raised so the client
        gets the concrete measurements back.

        Raises:
            audio_preprocess.PreprocessRejected: Every input path was
                rejected by the speech gate.
        """
        out: List[np.ndarray] = []
        first_rejection: audio_preprocess.PreprocessRejected | None = None
        for path in wav_paths:
            waveform = self._load_waveform(path)
            try:
                out.extend(self._preprocess_and_split(waveform))
            except audio_preprocess.PreprocessRejected as exc:
                logger.warning(
                    "[AudioRecognizer] Skip %s: %s", path, exc
                )
                if first_rejection is None:
                    first_rejection = exc
        if not out and first_rejection is not None:
            raise first_rejection
        return out

    def _prepare_waveforms_from_chunks(
        self, chunks: List[ChunkType], chunk_sample_rate: int
    ) -> List[np.ndarray]:
        """Concatenate input chunks, preprocess + gate, emit one-or-few windows.

        Incoming ``chunks`` are often mic frames (20-40 ms each). We join
        them into a single waveform so VAD / noisereduce / RMS see the full
        signal before gating and any length-cap split.

        Raises:
            audio_preprocess.PreprocessRejected: Empty chunks input or the
                speech gate rejected the merged waveform.
        """
        pieces: List[np.ndarray] = []
        for chunk in chunks:
            arr = self._chunk_to_numpy(chunk)
            if arr.size == 0:
                continue
            if chunk_sample_rate != self.sample_rate:
                arr = self._resample(arr, orig_sr=chunk_sample_rate, new_sr=self.sample_rate)
            pieces.append(arr)
        if not pieces:
            raise audio_preprocess.PreprocessRejected(
                audio_preprocess.REJECT_EMPTY_INPUT,
                input_duration_sec=0.0,
                min_duration_sec=self.min_duration_sec,
                min_voice_ratio=self.min_voice_ratio,
            )
        waveform = np.concatenate(pieces).astype(np.float32)
        return self._preprocess_and_split(waveform)

    def _extract_embeddings_from_paths_batch(self, wav_paths: List[AudioInput]) -> List[np.ndarray]:
        """Extract embeddings from many paths using batched ONNX inference.

        For simplicity, features are zero-padded to the max frame length in batch,
        then one ONNX call is used with shape [B, T_max, 80].
        """
        if not wav_paths:
            return []

        waveforms = self._prepare_waveforms_from_paths(wav_paths)
        if not waveforms:
            return []
        feats_list: List[np.ndarray] = [self._compute_fbank(waveform)[0] for waveform in waveforms]

        all_embeddings: List[np.ndarray] = []
        for start in range(0, len(feats_list), self.batch_size):
            chunk_feats = feats_list[start : start + self.batch_size]
            max_t = max(int(feat.shape[0]) for feat in chunk_feats)
            batch = np.zeros((len(chunk_feats), max_t, 80), dtype=np.float32)  # [B, T_max, 80]
            for i, feat in enumerate(chunk_feats):
                t = int(feat.shape[0])
                batch[i, :t, :] = feat
            batch_embs = self.session.run([self.output_name], {self.input_name: batch})[0]  # [B, D]
            all_embeddings.extend(self._l2_normalize(emb) for emb in batch_embs)
        return all_embeddings

    def _extract_embedding_from_chunks(
        self, chunks: List[ChunkType], chunk_sample_rate: int
    ) -> np.ndarray:
        """Extract embedding from a list of audio chunks.

        Args:
            chunks: List of 1D chunks as arrays/sequences.
            chunk_sample_rate: Sample rate of provided chunks.

        Returns:
            L2-normalized embedding vector.
        """
        if not chunks:
            raise ValueError("chunks is empty.")

        # Speech-gate failures raise PreprocessRejected with concrete
        # measurements; let the HTTP layer translate it into a 400 body.
        waveforms = self._prepare_waveforms_from_chunks(chunks, chunk_sample_rate)

        # Run chunk embeddings in mini-batches, then aggregate into one query embedding.
        query_embeddings = self._extract_embeddings_from_waveforms_batch(waveforms)
        return self._aggregate_embeddings(query_embeddings)

    def _extract_embeddings_from_waveforms_batch(self, waveforms: List[np.ndarray]) -> List[np.ndarray]:
        """Extract embeddings from waveforms using mini-batches."""
        if not waveforms:
            return []
        feats_list = [self._compute_fbank(waveform)[0] for waveform in waveforms]  # each [T, 80]
        all_embeddings: List[np.ndarray] = []
        for start in range(0, len(feats_list), self.batch_size):
            chunk_feats = feats_list[start : start + self.batch_size]
            max_t = max(int(feat.shape[0]) for feat in chunk_feats)
            batch = np.zeros((len(chunk_feats), max_t, 80), dtype=np.float32)  # [B, T_max, 80]
            for i, feat in enumerate(chunk_feats):
                t = int(feat.shape[0])
                batch[i, :t, :] = feat
            batch_embs = self.session.run([self.output_name], {self.input_name: batch})[0]  # [B, D]
            all_embeddings.extend(self._l2_normalize(emb) for emb in batch_embs)
        return all_embeddings

    @staticmethod
    def _l2_normalize(vec: np.ndarray) -> np.ndarray:
        """L2-normalize vector, preserving original if norm is near zero."""
        vec = np.asarray(vec, dtype=np.float32)  # [D]
        norm = np.linalg.norm(vec)
        if norm < 1e-12:
            return vec
        return vec / norm

    @staticmethod
    def _cosine_similarity(e1: np.ndarray, e2: np.ndarray) -> float:
        """Compute cosine similarity in range [-1, 1]."""
        # e1/e2: [D]
        return float(np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2) + 1e-12))

    def _aggregate_embeddings(self, embeddings: List[np.ndarray]) -> np.ndarray:
        """Mean-pool then L2-normalize.

        Matches WeSpeaker's "one embedding per utterance" assumption: when
        audio fits in one window this is a no-op on the single embedding;
        for very long audio split into a few same-length chunks a simple
        mean is the expected aggregator.
        """
        return audio_preprocess.mean_aggregate(embeddings)

    @staticmethod
    def _chunk_to_numpy(chunk: ChunkType) -> np.ndarray:
        """Convert chunk to 1D float32 NumPy array.

        Integer chunks are scaled to approximately [-1, 1].
        """
        arr = np.asarray(chunk)  # expected [T] per chunk

        if arr.ndim > 1:
            arr = np.squeeze(arr)  # reduce singleton dims
        if arr.ndim != 1:
            raise ValueError("Each audio chunk must be 1D after squeeze.")

        if np.issubdtype(arr.dtype, np.integer):
            max_val = np.iinfo(arr.dtype).max
            arr = arr.astype(np.float32) / float(max_val if max_val > 0 else 32767)
        else:
            arr = arr.astype(np.float32)
        return arr

    def register(self, name: str, wav_paths: Union[AudioInput, Iterable[AudioInput]]) -> Dict:
        """Register or overwrite one speaker with one/many enrollment files.

        Args:
            name: Speaker identifier.
            wav_paths: Single path or iterable of paths.

        Returns:
            Dict with keys:
                - name
                - num_samples
                - embedding_dim
        """
        if isinstance(wav_paths, (str, Path)):
            wav_paths = [wav_paths]
        paths = list(wav_paths)
        if not paths:
            raise ValueError("wav_paths is empty.")

        # Speech-gate failures raise PreprocessRejected with concrete
        # measurements; let the HTTP layer translate it into a 400 body.
        embeddings = self._extract_embeddings_from_paths_batch(paths)
        if not embeddings:
            # Defensive: _prepare_waveforms_from_paths should have raised
            # already; this only fires if an engine returns empty batches.
            raise RuntimeError("Embedding batch produced no vectors.")
        self.db.set(name, self._aggregate_embeddings(embeddings))
        saved = self.db.get(name)
        if saved is None:
            raise RuntimeError("Failed to store speaker embedding.")
        return {
            "name": name,
            "num_samples": len(paths),
            "embedding_dim": int(saved.shape[0]),
        }

    def remove(self, name: str) -> bool:
        """Remove one speaker from local DB.

        Returns:
            True if removed, False if speaker does not exist.
        """
        return self.db.delete(name)

    def recognize(
        self, audio: Union[AudioInput, List[ChunkType]], chunk_sample_rate: int = 16000
    ) -> Dict:
        """Recognize speaker from file path or list of chunks.

        Args:
            audio: Audio file path or list of chunks.
            chunk_sample_rate: Sample rate for chunk input.

        Returns:
            Dict with keys:
                - name: best matched speaker or empty string
                - confidence: score in [0, 1]
        """
        if len(self.db) == 0:
            return {"name": "", "confidence": 0.0}

        # Recognize keeps the "no speech -> empty result with 200" contract
        # for backwards compat; we log the rejection reason for debugging
        # but do not surface it to the client. Clients that want details
        # should use the /embed endpoint instead.
        try:
            if isinstance(audio, (str, Path)):
                query_waveforms = self._prepare_waveforms_from_paths([audio])
            else:
                query_waveforms = self._prepare_waveforms_from_chunks(audio, chunk_sample_rate)
        except audio_preprocess.PreprocessRejected as exc:
            logger.info("[AudioRecognizer] recognize gated: %s", exc)
            return {"name": "", "confidence": 0.0}

        if not query_waveforms:
            return {"name": "", "confidence": 0.0}

        query_embs = self._extract_embeddings_from_waveforms_batch(query_waveforms)
        if not query_embs:
            return {"name": "", "confidence": 0.0}

        vote_count: Dict[str, int] = defaultdict(int)
        conf_sum: Dict[str, float] = defaultdict(float)

        import logging

        for idx, query_emb in enumerate(query_embs):
            seg_best_name = ""
            seg_best_conf = 0.0
            confidences_for_this_query = {}
            for name, ref_emb in self.db.items():
                cos = self._cosine_similarity(query_emb, ref_emb)
                confidence = (cos + 1.0) / 2.0
                confidences_for_this_query[name] = confidence
                if confidence > seg_best_conf:
                    seg_best_conf = confidence
                    seg_best_name = name
            # Log confidence for all speakers for this query
            logging.info(f"[AudioRecognizer] Query {idx}: confidences per speaker: {confidences_for_this_query}")
            if seg_best_name:
                vote_count[seg_best_name] += 1
                conf_sum[seg_best_name] += seg_best_conf

        if not vote_count:
            return {"name": "", "confidence": 0.0}

        best_name = max(vote_count.keys(), key=lambda n: (vote_count[n], conf_sum[n] / vote_count[n]))
        avg_conf = conf_sum[best_name] / max(1, vote_count[best_name])
        return {"name": best_name, "confidence": float(avg_conf)}
 

    @property
    def speaker_db(self) -> Dict[str, np.ndarray]:
        """Compatibility view for existing callers/tests."""
        return self.db.to_dict()


class WeSpeakerResNet34Recognizer(BaseAudioRecognizer):
    """WeSpeaker VoxCeleb ResNet34-LM engine (256-dim embedding)."""

    ENGINE_NAME = "wespeaker-resnet34"
    DEFAULT_REMOTE_MODEL_PATH = (
        "https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM/resolve/main/voxceleb_resnet34_LM.onnx"
    )
    DEFAULT_LOCAL_MODEL_PATH = (
        AUDIO_RECOGNITION_BASE_DIR
        / "models"
        / "wespeaker-voxceleb-resnet34-LM"
        / "voxceleb_resnet34_LM.onnx"
    )


class EcapaTdnn512Recognizer(BaseAudioRecognizer):
    """WeSpeaker VoxCeleb ECAPA-TDNN-512-LM engine (emb-192, c512 channels).

    Input pipeline is identical to WeSpeaker ResNet34 (80-dim Kaldi fbank,
    16kHz mono), so only the ONNX weights differ.
    """

    ENGINE_NAME = "ecapa-tdnn512"
    DEFAULT_REMOTE_MODEL_PATH = (
        "https://huggingface.co/Wespeaker/wespeaker-ecapa-tdnn512-LM/resolve/main/voxceleb_ECAPA512_LM.onnx"
    )
    DEFAULT_LOCAL_MODEL_PATH = (
        AUDIO_RECOGNITION_BASE_DIR
        / "models"
        / "wespeaker-ecapa-tdnn512-LM"
        / "voxceleb_ECAPA512_LM.onnx"
    )


# Registry of all concrete engines. Keyed by ENGINE_NAME for env-based lookup.
AUDIO_RECOGNIZER_ENGINES: Dict[str, Type[BaseAudioRecognizer]] = {
    WeSpeakerResNet34Recognizer.ENGINE_NAME: WeSpeakerResNet34Recognizer,
    EcapaTdnn512Recognizer.ENGINE_NAME: EcapaTdnn512Recognizer,
}

DEFAULT_AUDIO_RECOGNIZER_ENGINE = WeSpeakerResNet34Recognizer.ENGINE_NAME


def resolve_engine_name(engine: str | None = None) -> str:
    """Pick engine name from explicit arg, env var, or default."""
    if engine:
        return engine.strip().lower()
    env_value = os.getenv(ENV_AUDIO_RECOGNIZER_ENGINE, "").strip().lower()
    return env_value or DEFAULT_AUDIO_RECOGNIZER_ENGINE


def create_audio_recognizer(
    engine: str | None = None, **kwargs: Any
) -> BaseAudioRecognizer:
    """Instantiate the configured speaker recognition engine.

    Selection order:
        1. Explicit ``engine`` argument.
        2. Env var ``AUDIO_RECOGNIZER_ENGINE``.
        3. ``DEFAULT_AUDIO_RECOGNIZER_ENGINE`` (WeSpeaker ResNet34).

    Args:
        engine: Engine identifier. See ``AUDIO_RECOGNIZER_ENGINES`` keys.
        **kwargs: Forwarded to the engine constructor.
    """
    name = resolve_engine_name(engine)
    cls = AUDIO_RECOGNIZER_ENGINES.get(name)
    if cls is None:
        available = ", ".join(sorted(AUDIO_RECOGNIZER_ENGINES.keys()))
        raise ValueError(
            f"Unknown audio recognizer engine '{name}'. Available: {available}"
        )
    source = (
        "arg" if engine
        else ("env" if os.getenv(ENV_AUDIO_RECOGNIZER_ENGINE) else "default")
    )
    msg = (
        f"[AudioRecognizer] create_audio_recognizer engine='{name}' "
        f"source={source} class={cls.__name__}"
    )
    logger.info(msg)
    print(msg, flush=True)
    return cls(**kwargs)

AudioRecognizer = WeSpeakerResNet34Recognizer

