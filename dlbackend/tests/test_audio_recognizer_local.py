from pathlib import Path
import time

import numpy as np
import pytest
import soundfile as sf

from core.audio_recognition.audio_recognizer import AudioRecognizer


DATA_DIR = Path(__file__).parent / "mock_data" / "audio"

BAO_1 = DATA_DIR / "Bao" / "Bao_1.wav"
BAO_2 = DATA_DIR / "Bao" / "Bao_2.wav"
KHANH_1 = DATA_DIR / "Khanh" / "Khanh_1.wav"
KHANH_2 = DATA_DIR / "Khanh" / "Khanh_2.wav"
KHANH_3 = DATA_DIR / "Khanh" / "Khanh_3.wav"
KHANH_4 = DATA_DIR / "Khanh" / "Khanh_4.wav"
DARREN_0 = DATA_DIR / "Darren" / "record_0.wav"
DARREN_1 = DATA_DIR / "Darren" / "record_1.wav"
DARREN_2 = DATA_DIR / "Darren" / "record_2.wav"
DARREN_3 = DATA_DIR / "Darren" / "record_3.wav"
DARREN_4 = DATA_DIR / "Darren" / "record_4.wav"


def _deps_ready() -> bool:
    try:
        import onnxruntime  # noqa: F401
        import kaldi_native_fbank  # noqa: F401
        import scipy  # noqa: F401
        import soundfile  # noqa: F401
    except Exception:
        return False
    return True


def _files_ready() -> bool:
    required = [BAO_1, BAO_2, KHANH_1, KHANH_2, KHANH_3, KHANH_4]
    return all(p.exists() for p in required)


def _wav_to_chunks(wav_path: Path, chunk_seconds: float = 0.5):
    waveform, sr = sf.read(str(wav_path), dtype="float32")
    if waveform.ndim == 2:
        mono = waveform.mean(axis=1).astype(np.float32)
    else:
        mono = waveform.astype(np.float32)

    chunk_size = max(1, int(sr * chunk_seconds))
    chunks = []
    for i in range(0, len(mono), chunk_size):
        chunk = mono[i : i + chunk_size]
        if len(chunk) > 0:
            chunks.append(chunk)
    return chunks, sr


def _timed_call(label: str, fn, *args, **kwargs):
    start = time.perf_counter()
    out = fn(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    print(f"[Timing] {label}: {elapsed_ms:.2f} ms")
    return out


@pytest.mark.integration
@pytest.mark.skipif(
    not _deps_ready() or not _files_ready(),
    reason="Missing runtime dependencies or required model/audio files.",
)
def test_register_single_wav_persist_local_db(tmp_path):
    print("==========================================test_register_single_wav_persist_local_db==========================================")
    # Arrange
    db_path = tmp_path / "speaker_db_test.json"
    recognizer = AudioRecognizer(db_path=db_path)       

    print("\n[Arrange] Register Bao from Bao_1.wav")
    # Action
    out = _timed_call("register(Bao, Bao_1.wav)", recognizer.register, "Bao", BAO_1)
    print("[Action] register Bao ->", out)

    # Assert
    assert out["name"] == "Bao"
    assert out["num_samples"] == 1
    assert db_path.exists()
    assert "Bao" in recognizer.speaker_db


@pytest.mark.integration
@pytest.mark.skipif(
    not _deps_ready() or not _files_ready(),
    reason="Missing runtime dependencies or required model/audio files.",
)
def test_register_multi_wavs_use_median_centroid(tmp_path):
    print("==========================================test_register_multi_wavs_use_median_centroid==========================================")
    # Arrange
    db_path = tmp_path / "speaker_db_test.json"
    recognizer = AudioRecognizer(db_path=db_path)
    wavs = [KHANH_1, KHANH_2, KHANH_3]
    print("\n[Arrange] Register Khanh from:", [str(x) for x in wavs])

    # Action
    out = _timed_call("register(Khanh, 3 wavs)", recognizer.register, "Khanh", wavs)
    print("[Action] register Khanh ->", out)

    # Assert
    assert out["name"] == "Khanh"
    assert out["num_samples"] == 3
    assert "Khanh" in recognizer.speaker_db
    vec = recognizer.speaker_db["Khanh"]
    assert vec.ndim == 1
    assert np.isclose(np.linalg.norm(vec), 1.0, atol=1e-3)


@pytest.mark.integration
@pytest.mark.skipif(
    not _deps_ready() or not _files_ready(),
    reason="Missing runtime dependencies or required model/audio files.",
)
def test_recognize_from_wav_path(tmp_path):
    print("==========================================test_recognize_from_wav_path==========================================")
    # Arrange
    db_path = tmp_path / "speaker_db_test.json"
    recognizer = AudioRecognizer(db_path=db_path)
    _timed_call("register(Bao, Bao_1.wav)", recognizer.register, "Bao", BAO_1)
    _timed_call(
        "register(Khanh, 3 wavs)",
        recognizer.register,
        "Khanh",
        [KHANH_1, KHANH_2, KHANH_3],
    )
    print("\n[Arrange] DB speakers:", list(recognizer.speaker_db.keys()))

    # Action
    result = _timed_call("recognize(Khanh_4.wav)", recognizer.recognize, KHANH_4)
    print("[Action] recognize(Khanh_4.wav) ->", result)

    # Assert
    assert result["name"] == "Khanh"
    assert 0.0 <= result["confidence"] <= 1.0


@pytest.mark.integration
@pytest.mark.skipif(
    not _deps_ready() or not _files_ready(),
    reason="Missing runtime dependencies or required model/audio files.",
)
def test_recognize_from_audio_chunks(tmp_path):
    print("==========================================test_recognize_from_audio_chunks==========================================")
    # Arrange
    db_path = tmp_path / "speaker_db_test.json"
    recognizer = AudioRecognizer(db_path=db_path)
    _timed_call("register(Bao, Bao_1.wav)", recognizer.register, "Bao", BAO_1)
    _timed_call(
        "register(Khanh, 3 wavs)",
        recognizer.register,
        "Khanh",
        [KHANH_1, KHANH_2, KHANH_3],
    )
    _timed_call(
        "register(Darren, 4 wavs)",
        recognizer.register, "Darren", 
        [DARREN_0, DARREN_1, DARREN_2, DARREN_3],
    )
    
    # BAO_2
    chunks_bao_2, sr_bao_2 = _timed_call("wav_to_chunks(Bao_2.wav)", _wav_to_chunks, BAO_2, 0.5)
    print(f"\n[Arrange] Chunks from Bao_2.wav: count={len(chunks_bao_2)}, sr={sr_bao_2}")
    
    # DARREN_4
    chunks_darren_4, sr_darren_4 = _timed_call("wav_to_chunks(record_4.wav)", _wav_to_chunks, DARREN_4, 0.5)
    print(f"\n[Arrange] Chunks from record_4.wav: count={len(chunks_darren_4)}, sr={sr_darren_4}")

    # Action
    result_bao_2 = _timed_call(
        "recognize(chunks from Bao_2.wav)",
        recognizer.recognize,
        chunks_bao_2,
        sr_bao_2,
    )
    print("[Action] recognize(chunks Bao_2.wav) ->", result_bao_2)

    result_darren_4 = _timed_call(
        "recognize(chunks from record_4.wav)",
        recognizer.recognize,
        chunks_darren_4,
        sr_darren_4,
    )
    print("[Action] recognize(chunks record_4.wav) ->", result_darren_4)

    # Assert
    assert result_bao_2["name"] == "Bao"
    assert 0.0 <= result_bao_2["confidence"] <= 1.0    
    assert result_darren_4["name"] == "Darren"
    assert 0.0 <= result_darren_4["confidence"] <= 1.0


@pytest.mark.integration
@pytest.mark.skipif(
    not _deps_ready() or not _files_ready(),
    reason="Missing runtime dependencies or required model/audio files.",
)
def test_remove_speaker_success(tmp_path):
    print("==========================================test_remove_speaker_success==========================================")
    # Arrange
    db_path = DATA_DIR / "speaker_db_test_for_remove.json"
    recognizer = AudioRecognizer(db_path=db_path)
    _timed_call("register(Bao, Bao_1.wav)", recognizer.register, "Bao", BAO_1)
    _timed_call("register(Khanh, 3 wavs)", recognizer.register, "Khanh", [KHANH_1, KHANH_2, KHANH_3])
    _timed_call("register(Darren, 4 wavs)", recognizer.register, "Darren", [DARREN_0, DARREN_1, DARREN_2, DARREN_3])
    print("\n[Arrange] Before remove speakers:", list(recognizer.speaker_db.keys()))

    # Action
    ok = _timed_call("remove(Bao)", recognizer.remove, "Bao")
    print("[Action] remove('Bao') ->", ok)

    # Assert
    assert ok is True
    assert "Bao" not in recognizer.speaker_db


@pytest.mark.integration
@pytest.mark.skipif(
    not _deps_ready() or not _files_ready(),
    reason="Missing runtime dependencies or required model/audio files.",
)
def test_remove_speaker_not_found(tmp_path):
    print("==========================================test_remove_speaker_not_found==========================================")
    # Arrange
    db_path = tmp_path / "speaker_db_test.json"
    recognizer = AudioRecognizer(db_path=db_path)
    _timed_call("register(Khanh, Khanh_1.wav)", recognizer.register, "Khanh", KHANH_1)
    print("\n[Arrange] Existing speakers:", list(recognizer.speaker_db.keys()))

    # Action
    ok = _timed_call("remove(NotExist)", recognizer.remove, "NotExist")
    print("[Action] remove('NotExist') ->", ok)

    # Assert
    assert ok is False


@pytest.mark.integration
@pytest.mark.skipif(
    not _deps_ready() or not _files_ready(),
    reason="Missing runtime dependencies or required model/audio files.",
)
def test_get_db():
    print("==========================================test_get_db==========================================")
    # Arrange
    db_path =  DATA_DIR / "speaker_db_test.json"
    recognizer = AudioRecognizer(db_path=db_path)
    _timed_call("register(Bao, Bao_1.wav)", recognizer.register, "Bao", BAO_1)
    _timed_call(
        "register(Khanh, 3 wavs)",
        recognizer.register,
        "Khanh",
        [KHANH_1, KHANH_2, KHANH_3],
    )
    _timed_call(
        "register(Darren, 4 wavs)",
        recognizer.register, "Darren", 
        [DARREN_0, DARREN_1, DARREN_2, DARREN_3],
    )
    print("\n[Arrange] DB speakers:", list(recognizer.speaker_db.keys()))
    

    # Action
    db = recognizer.speaker_db
    print("DB speakers:", list(db.keys()))

    # Assert
    assert db is not None
    assert len(db) == 3