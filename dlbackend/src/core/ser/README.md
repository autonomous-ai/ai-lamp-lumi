# Speech Emotion Recognition (SER)

Classify the emotion of one utterance using
[emotion2vec_plus_large](https://huggingface.co/iic/emotion2vec_plus_large)
on ONNX Runtime. Input: mono 16 kHz waveform. Output: softmax over 9
emotion classes.

## Layout

```
core/ser/
├── prepare_onnx.py           # cold-start fallback: FunASR -> ONNX export
├── speech_emotion_recognizer/
│   ├── base.py               # ABC, label loading, dispatch
│   ├── audio_utils.py        # load / resample / mono / normalize
│   ├── onnx_base.py          # ORT session + provider auto-detect
│   ├── emotion2vec.py        # concrete engine
│   └── factory.py            # create_speech_emotion_recognizer()
└── models/<engine>/          # local cache (.onnx + labels.txt)
```

## Path resolution (highest priority first)

**Model**: arg `model_path` → `SER_MODEL_PATH` env (or
`SER_RECOGNITION_CKPT_PATH` config) → local cache → remote URL →
FunASR export fallback (writes `.onnx` **and** `labels.txt`).

**Labels**: arg `labels_path` → `SER_LABELS_PATH` env (or
`SER_RECOGNITION_LABELS_PATH` config) → engine `DEFAULT_LABELS_PATH`.

## Execution providers

Auto-detect order: `CUDA → ROCm → DirectML → CoreML → CPU`, filtered
by what ORT actually has compiled (always falls back to CPU). Override
with `SER__PROVIDERS=cuda,cpu` (aliases accepted: `cuda`, `coreml`,
`cpu`, ...). The actual provider list ORT selected is exposed as
`recognizer.providers`.

## Configuration (`.env`)

```bash
SER_RECOGNITION_MODEL=emotion2vec_plus_large
SER_RECOGNITION_CKPT_PATH=/abs/path/emotion2vec.onnx   # optional
SER_RECOGNITION_LABELS_PATH=/abs/path/labels.txt       # optional
SER__SAMPLE_RATE=16000
SER__INTRA_OP_THREADS=8
SER__PROVIDERS=                                         # empty = auto
```

## HTTP API

All endpoints live under `/api/dl/` and require header `X-API-Key`.

### `GET /api/dl/ser/labels`

```json
{
  "engine": "emotion2vec_plus_large",
  "labels": ["angry", "disgusted", "fearful", "happy", "neutral",
             "other", "sad", "surprised", "<unk>"]
}
```

### `POST /api/dl/ser/recognize`

Accepts audio in one of three ways:

| Mode | `Content-Type` | Payload |
|---|---|---|
| Upload | `multipart/form-data` | field `wav` (WAV file). Optional `return_scores=false`. |
| Base64 WAV | `application/json` | `{"audio_b64": "<b64 WAV bytes>", "return_scores": true}` |
| URL       | `application/json` | `{"wav_path": "https://.../clip.wav"}` (http/https only) |

Response 200:

```json
{
  "label": "happy",
  "confidence": 0.9981,
  "scores": { "angry": 1.3e-05, "happy": 0.9998, "...": "..." }
}
```

`scores` is `null` when `return_scores=false`.

Error codes: `400` (bad body / bad audio / local path rejected),
`401`/`403` (api key), `422` (multipart missing `wav`), `503`
(engine init failed).

## Example calls

### curl

```bash
# multipart
curl -X POST "$BASE/api/dl/ser/recognize" \
  -H "X-API-Key: $DL_API_KEY" \
  -F "wav=@happy.wav"

# base64
B64=$(base64 -i happy.wav | tr -d '\n')
curl -X POST "$BASE/api/dl/ser/recognize" \
  -H "X-API-Key: $DL_API_KEY" -H "Content-Type: application/json" \
  -d "{\"audio_b64\":\"$B64\"}"

# URL
curl -X POST "$BASE/api/dl/ser/recognize" \
  -H "X-API-Key: $DL_API_KEY" -H "Content-Type: application/json" \
  -d '{"wav_path":"https://cdn.example.com/clip.wav"}'
```

### Python (`httpx`)

```python
import httpx, base64, os

URL  = "http://localhost:8008/api/dl/ser/recognize"
HEAD = {"X-API-Key": os.environ["DL_API_KEY"]}

# multipart
with open("happy.wav", "rb") as f:
    r = httpx.post(URL, headers=HEAD,
                   files=[("wav", ("happy.wav", f, "audio/wav"))])

# base64
b64 = base64.b64encode(open("happy.wav", "rb").read()).decode()
r = httpx.post(URL, headers=HEAD,
               json={"audio_b64": b64, "return_scores": False})

print(r.json())
```

## In-process usage

```python
from core.ser import create_speech_emotion_recognizer

ser = create_speech_emotion_recognizer()             # all defaults
result = ser.predict("clip.wav")                     # path / URL
# or
import soundfile as sf
wav, sr = sf.read("clip.wav", dtype="float32")
result = ser.predict(wav, sample_rate=sr)            # ndarray
print(result["label"], result["confidence"])
```

## Cold start

First run with no cached `.onnx`: engine downloads the FunASR
checkpoint, exports ONNX into `models/<engine>/emotion2vec.onnx`, and
writes a fresh `labels.txt` from the snapshot's `tokens.txt`. Requires
`torch` + `funasr` (installed via the `[cpu]` / `[gpu]` extras). After
the first build, those heavy deps can be uninstalled — only
`onnxruntime` is needed at serve time.

## Tests

```bash
pytest -v -s tests/ser_local/test_ser_local.py    # in-process
pytest -v -s tests/ser_api/test_ser_api.py        # needs running server
```

Mock audio: `tests/mock_data/audio/ser/{happy,sad}.wav`.

## Adding a new engine

1. Subclass `OnnxSpeechEmotionRecognizer` under
   `speech_emotion_recognizer/`. Set `ENGINE_NAME`, `MODEL_ID`,
   `DEFAULT_LOCAL_MODEL_PATH`, `DEFAULT_LABELS_PATH` (and optionally
   `DEFAULT_REMOTE_MODEL_PATH`).
2. Register the class in `factory.SER_ENGINES`.
3. Add a matching entry to `enums/speech_emotion_recognizer.py`.
