# Speech Emotion Recognition (SER)

Recognize the **user's** emotion from their voice (not the lamp's). Runs alongside speaker identification at the end of every STT session: the same WAV used to identify the speaker is forwarded to a dedicated `SpeechEmotionService`, which buffers per-user, dedups by polarity bucket, and fires `speech_emotion.detected` sensing events to Lumi.

This is the voice-side twin of facial emotion detection (`emotion.detected`). The architecture, polarity bucketing, and dedup window are intentionally symmetric so both modalities land in the same downstream skills (`user-emotion-detection/SKILL.md`, mood logging, music suggestion).

> Not to be confused with **Emotion Expression** (`emotion/SKILL.md`) — that controls the lamp's own emotional output (servo + LED + eyes). SER is about sensing what the *user* feels through speech; expression is how *Lumi* shows its feelings.

---

## Architecture

```
voice_service._identify_and_decorate(transcript)
    │  wav_bytes (the same bytes sent to speaker recognition)
    │  name      (from speaker_recognizer.recognize)
    ▼
SpeechEmotionService.submit(user, wav_bytes, duration_s)   ← non-blocking
    │  queue.put_nowait
    ▼
worker thread (daemon)
    │  Emotion2VecRecognizer.recognize(wav_bytes)
    │     POST {DL_BACKEND_URL}/lelamp/api/dl/ser/recognize
    │     ← { "label": "happy", "confidence": 0.78 }
    ▼
buffer[user].append(Inference)               ← per-user accumulation
    ▲
    │  (flush thread wakes every SPEECH_EMOTION_FLUSH_S)
    ▼
flush:
    ① drop neutral / <unk> / other labels
    ② mode(label) across this user's buffered samples
    ③ bucket = polarity(mode)                ← positive | negative | other
    ④ TTL dedup: key=(user, bucket) over SPEECH_EMOTION_DEDUP_WINDOW_S
    ⑤ POST Lumi /api/sensing/event with type="speech_emotion.detected"
```

LeLamp's voice pipeline **only calls `submit()`**. All HTTP I/O to dlbackend, buffering, bucketing, dedup, retry, and Lumi POST are contained inside the `speech_emotion/` module — they never block the STT path.

---

## File Layout

```
lelamp/service/voice/speech_emotion/
├── __init__.py        # public API: SpeechEmotionService + ABC + engine + result type
├── constants.py       # defaults, label vocabulary, bucket map, event type
├── base.py            # BaseSpeechEmotionRecognizer (ABC), SpeechEmotionResult dataclass
├── emotion2vec.py     # Emotion2VecRecognizer — HTTP wrapper for dlbackend /api/dl/ser/recognize
├── utils.py           # normalize_label, is_neutral, bucket_for, hedge_for, format_message
└── service.py         # SpeechEmotionService — queue + worker + flush + dedup + send-to-lumi
```

Adding a new engine: subclass `BaseSpeechEmotionRecognizer` (one method: `recognize(wav_bytes) -> SpeechEmotionResult | None`) and swap it in via `SpeechEmotionService(recognizer=...)` at construction time. Default factory builds `Emotion2VecRecognizer` from `lelamp.config.SPEECH_EMOTION_API_URL`.

---

## Threading Model

Two daemon threads, started in `SpeechEmotionService.__init__` only when `recognizer.available` is true:

| Thread | Loop | Drains | Produces |
|--------|------|--------|----------|
| `speech-emotion-worker` | `_worker_loop` | submission queue (`queue.Queue`, maxsize 32) | per-user buffer entries |
| `speech-emotion-flush` | `_flush_loop` (wait + tick every `SPEECH_EMOTION_FLUSH_S`) | per-user buffer | `speech_emotion.detected` POSTs to Lumi |

Both threads exit cleanly on `stop()` — the worker is poisoned with a `None` sentinel, the flush thread observes the stop event during its `Event.wait`.

`submit()` is non-blocking by design. If the worker queue is full (32 jobs backlog) the new submission is dropped with a warning — this signals real overload (dlbackend wedged or down) and the caller should not retry. Audio is single-utterance, not streaming, so a one-second drop is acceptable.

---

## Wire Format

### Submission (in-process)

```python
service.submit(
    user="alice",                 # normalized lowercase identity from speaker recognizer
    wav_bytes=b"RIFF....WAVE...", # exact bytes that were POSTed to speaker /embed
    duration_s=2.4,               # length of audio for the MIN_AUDIO_S gate
)
```

### Engine call → dlbackend

```http
POST {DL_BACKEND_URL}/lelamp/api/dl/ser/recognize
Headers:
  X-API-Key: <key>
  Content-Type: application/json
Body:
  {"audio_b64": "<base64 WAV (mono 16 kHz)>", "return_scores": false}
```

Response:

```json
{ "label": "happy", "confidence": 0.9981, "scores": null }
```

Labels (emotion2vec_plus_large, from `/api/dl/ser/labels`):

```
angry, disgusted, fearful, happy, neutral, other, sad, surprised, <unk>
```

### Sensing event → Lumi

```http
POST http://127.0.0.1:5000/api/sensing/event
Content-Type: application/json
```

```json
{
  "type": "speech_emotion.detected",
  "message": "Speech emotion detected: Sad. (weak voice cue; confidence=0.72; bucket=negative; treat as uncertain, do not assume the user is distressed.)",
  "current_user": "alice"
}
```

The raw `Speech emotion detected: <Label>.` prefix is the parser anchor for Lumi-side routing. The parenthetical is a hedge clause to stop the LLM from over-committing on noisy SER reads — same pattern as the facial `Emotion detected: …` message.

Retry policy: 3 attempts with 2 s back-off on `ConnectionError` or HTTP `503`. Other 4xx/5xx are logged and dropped (the sample is gone — we don't retry-storm Lumi).

---

## Polarity Buckets

Bucketing mirrors the facial pipeline so `(user, bucket)` dedup keys are interpretable across modalities. The buckets are:

| Bucket | Labels |
|--------|--------|
| `positive` | happy, surprised |
| `negative` | angry, disgusted, fearful, sad |
| `other` | neutral, other, `<unk>` (these are **dropped before bucketing** — see anti-spam guard #4) |

Why bucket-level dedup, not label-level: emotion2vec on short utterances flips between sad/fearful/angry within the same affective state. Per-label dedup would over-deliver. Per-bucket dedup collapses within-bucket noise (sad ↔ fearful ↔ angry) into one negative event per window; cross-bucket flips (sad → happy) still fire as a genuine mood change.

---

## Anti-Spam Guards

Layered, matched 1-to-1 with the facial emotion processor:

| # | Stage | Drop condition |
|---|-------|----------------|
| 1 | `submit()` | `wav_bytes` empty / `duration_s < SPEECH_EMOTION_MIN_AUDIO_S` |
| 2 | `submit()` | `user` is empty (no subject to attribute emotion to — mirrors face `current_user==""`) |
| 3 | worker | `confidence < SPEECH_EMOTION_CONFIDENCE_THRESHOLD` |
| 4 | flush  | label is `neutral` / `other` / `<unk>` |
| 5 | flush  | `(user, bucket)` was sent less than `SPEECH_EMOTION_DEDUP_WINDOW_S` seconds ago |

Each bucket keeps its own independent TTL entry in `_last_sent_by_key`. Sending a positive event does NOT reset the negative window (and vice versa). Same semantics as facial emotion.

---

## Configuration

All knobs live in `lelamp/config.py` as `SPEECH_EMOTION_*`, overridable via env vars. Defaults mirror `EMOTION_*` so the two modalities behave identically out of the box.

| Constant | Env var | Default | Purpose |
|----------|---------|---------|---------|
| `SPEECH_EMOTION_ENABLED` | `LELAMP_SPEECH_EMOTION_ENABLED` | `true` | Master kill switch |
| `SPEECH_EMOTION_CONFIDENCE_THRESHOLD` | `LELAMP_SPEECH_EMOTION_CONFIDENCE_THRESHOLD` | `0.5` | Min model confidence to buffer |
| `SPEECH_EMOTION_FLUSH_S` | `LELAMP_SPEECH_EMOTION_FLUSH_S` | `10.0` | Buffer drain cadence |
| `SPEECH_EMOTION_DEDUP_WINDOW_S` | `LELAMP_SPEECH_EMOTION_DEDUP_WINDOW_S` | `300.0` | TTL for `(user, bucket)` |
| `SPEECH_EMOTION_MIN_AUDIO_S` | `LELAMP_SPEECH_EMOTION_MIN_AUDIO_S` | `0.8` | Min utterance length |
| `SPEECH_EMOTION_API_TIMEOUT_S` | `LELAMP_SPEECH_EMOTION_API_TIMEOUT_S` | `15` | dlbackend HTTP timeout |
| `DL_SER_ENDPOINT` | `DL_SER_ENDPOINT` | `/lelamp/api/dl/ser/recognize` | Path suffix on `DL_BACKEND_URL` |
| `SPEECH_EMOTION_API_URL` | — | derived | `DL_BACKEND_URL` + `DL_SER_ENDPOINT` |
| `SPEECH_EMOTION_API_KEY` | — | mirrors `DL_API_KEY` | Sent as `X-API-Key` |

Label vocabulary and bucket map are declared in `lelamp/service/voice/speech_emotion/constants.py` (not env-overridable — touching these requires a model swap on dlbackend).

---

## Integration Point

Single call-site in `lelamp/service/voice/voice_service.py::_identify_and_decorate`, immediately after `self._speaker.recognize(...)` returns:

```python
if (
    self._speech_emotion is not None
    and self._speech_emotion.available
    and result.get("match")
    and name
    and name != "unknown"
):
    self._speech_emotion.submit(user=name, wav_bytes=wav_bytes, duration_s=duration_s)
```

We submit **only when speaker ID succeeded** with a known name — unknown / cluster-only voices are skipped because there's no stable user to attribute emotion to. Same skip rule the facial pipeline applies for `current_user == ""`.

`wav_bytes` is the exact byte string that was base64-encoded for the speaker `/embed` POST — no recomputation, no extra copy (bytes are immutable in Python). `duration_s` is computed once from the int16 buffer size in the existing speaker block and reused.

Lazy init in `VoiceService.__init__` mirrors the speaker recognizer pattern: instance is created once, threads start only when the engine reports `available`.

---

## Failure Modes

| Failure | Effect | Recovery |
|---------|--------|----------|
| `DL_BACKEND_URL` not configured | `recognizer.available` is False, threads never start, `submit()` is a no-op | Set `llm_base_url` in Lumi config |
| dlbackend down (connection refused) | Worker logs warning, sample dropped, no retry | Next utterance retries automatically |
| dlbackend returns non-200 | Worker logs warning, sample dropped | Same as above |
| Worker queue full | `submit()` logs warning, returns immediately | Indicates backend overload; investigate |
| Lumi sensing endpoint down | 3 retries with 2 s back-off, then sample dropped | Buffer continues filling for next flush |
| `duration_s < MIN_AUDIO_S` | Dropped in `submit()` with debug log | Expected — short utterances aren't worth classifying |

Nothing here blocks the STT path or speaker recognition — SER failures are silent at the user level and visible only in `/var/log/lelamp/server.log`.

---

## Diagnostic Snapshot

`SpeechEmotionService.to_dict()` returns a runtime snapshot for the `/voice/status` (or any future) introspection endpoint:

```json
{
  "type": "speech_emotion",
  "available": true,
  "buffered_users": 2,
  "dedup_keys": 3,
  "queue_size": 0,
  "last_flush_ts": 1715587812.41
}
```

---

## Relationship to Other Pipelines

| Pipeline | Modality | Trigger | Event type | Same skill consumes? |
|----------|----------|---------|------------|----------------------|
| Facial emotion (`emotion.py` perception) | Camera frame → face crop | Every face seen | `emotion.detected` | yes — `user-emotion-detection/SKILL.md` |
| **Speech emotion (this doc)** | Mic → end-of-utterance WAV | Every speaker-identified turn | `speech_emotion.detected` | (pending Lumi-side routing) — same skill is the natural target |
| Mood synthesis (Mood skill) | — | Any emotion signal | mood `signal` / `decision` rows | — |
| Sound (`sound.py` perception) | Mic RMS | Loud noise | `sound` | dog-bark escalation, separate skill |

Speech emotion shares the polarity vocabulary with facial emotion deliberately. When Lumi's sensing handler is wired to also accept `speech_emotion.detected`, the existing `Happy → happy / Sad → sad / Angry → frustrated / Fear → stressed` mood mapping in `user-emotion-detection/SKILL.md` applies unchanged — only the event-type switch in `handler.go` changes.
