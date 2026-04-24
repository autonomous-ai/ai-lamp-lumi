# Speaker Voice Enrollment — Technical Spec

**Status: IMPLEMENTED** (2026-04)

## Overview

Lumi identifies who is speaking via **WeSpeaker ResNet34** (256-dim embedding, ONNX Runtime). When a speaker is not recognized, LeLamp saves the audio and optionally nudges the AI agent to enroll the voice. Enrollment is **self-service only** — each person enrolls their own voice.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  LeLamp (Python, port 5001)                                         │
│                                                                     │
│  VoiceService._stream_session()                                     │
│    ├─ STT transcript ready                                          │
│    ├─ _identify_and_decorate(transcript)                            │
│    │   ├─ audio_buffer → WAV bytes → base64                        │
│    │   ├─ POST /audio-recognizer/embed → dlbackend (RunPod)        │
│    │   │   └─ WeSpeaker ResNet34 ONNX → 256-dim L2-normalized      │
│    │   ├─ Per-chunk voting vs enrolled embeddings                   │
│    │   ├─ Match ≥ 0.7 → "Speaker - Name: transcript"               │
│    │   └─ No match → _format_unknown_speaker()                     │
│    │       ├─ _should_request_enroll() gate                         │
│    │       │   ├─ ≥ 25 words in transcript                          │
│    │       │   └─ ≥ 5s audio duration                               │
│    │       ├─ PASS → "Unknown Speaker: ... (audio save at <path>,   │
│    │       │          auto enroll ...)"                              │
│    │       └─ FAIL → "Unknown Speaker: ..." (no enroll instruction) │
│    └─ POST /api/sensing/event → Lumi (Go)                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Lumi (Go, port 5000)                                               │
│                                                                     │
│  Two paths (both call domain.AppendEnrollNudge):                    │
│                                                                     │
│  1. Direct path (handler.go)                                        │
│     └─ Agent idle → send immediately to OpenClaw                    │
│                                                                     │
│  2. Drain path (service.go)                                         │
│     └─ Agent busy → queue → replay when idle                        │
│                                                                     │
│  AppendEnrollNudge(msg) — domain/voice.go:                          │
│    ├─ Check: contains "Unknown Speaker:" + "audio save at"          │
│    ├─ Cooldown: skip if < 5 min since last nudge                    │
│    └─ Append: "[REQUIRED: Follow speaker-recognizer/SKILL.md ...]"  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  OpenClaw Agent                                                     │
│                                                                     │
│  speaker-recognizer/SKILL.md                                        │
│    ├─ Detects self-introduction ("I'm X", "my name is X")           │
│    ├─ curl POST /speaker/enroll with wav_path + name                │
│    ├─ Two-turn: ask "Who are you?" → enroll with both paths         │
│    └─ Confirm: "Nice to meet you, Name!"                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Anti-Spam Gates

Three layers prevent the agent from repeatedly asking "who are you?":

| Layer | Where | Gate | Purpose |
|-------|-------|------|---------|
| **Audio duration** | LeLamp `voice_service.py` | `duration_s < SPEAKER_MIN_AUDIO_S` (0.8s) | Skip recognition entirely for very short audio |
| **Enroll instruction** | LeLamp `_should_request_enroll()` | `≥ 25 words AND ≥ 5s audio` | Don't append enroll instruction for short utterances |
| **Nudge cooldown** | Lumi `domain/voice.go` | `5 min since last nudge` | Don't inject SKILL.md instruction more than once per 5 min |

## Model & Embedding

| Property | Value |
|----------|-------|
| Model | WeSpeaker ResNet34 (VoxCeleb trained) |
| Embedding dim | 256 |
| Runtime | ONNX Runtime (CPU) on dlbackend (RunPod) |
| Endpoint | `POST {DL_BACKEND_URL}/lelamp/api/dl/audio-recognizer/embed` |
| Auth | `X-API-Key` header |
| Timeout | 15s |

### Recognition Algorithm

1. Audio → preprocess (noise reduce, VAD, HPF, RMS normalize)
2. Extract per-chunk embeddings `[M, 256]`
3. Cosine similarity against all enrolled speaker embeddings
4. Per-chunk voting: each chunk votes for its closest match
5. Winner = most votes (tiebreak by average confidence)
6. `confidence ≥ 0.7` → match; else unknown

### Enrollment Quality

1. Each WAV sample → embedding via dlbackend
2. Filter by consistency threshold `0.7` (cosine similarity between samples)
3. Aggregate remaining embeddings via weighted average
4. Store L2-normalized vector at `/root/local/users/{name}/voice/embedding.npy`

## Configuration

| Parameter | Default | Env var | Description |
|-----------|---------|---------|-------------|
| Match threshold | 0.7 | `SPEAKER_MATCH_THRESHOLD` | Min confidence for speaker match |
| Enroll consistency | 0.7 | `SPEAKER_ENROLL_CONSISTENCY_THRESHOLD` | Min cosine similarity between enrollment samples |
| API timeout | 15s | `SPEAKER_EMBEDDING_API_TIMEOUT_S` | HTTP timeout for embedding API |
| Min audio for recognition | 0.8s | `LELAMP_SPEAKER_MIN_AUDIO_S` | Skip recognition below this |
| Min words for enroll nudge | 25 | Hardcoded in `_should_request_enroll()` | Transcript word count gate |
| Min duration for enroll nudge | 5.0s | Hardcoded in `_should_request_enroll()` | Audio duration gate |
| Nudge cooldown | 5 min | Hardcoded in `domain/voice.go` | Lumi-side cooldown between enroll nudges |
| Speaker recognition enabled | false | `LELAMP_SPEAKER_RECOGNITION_ENABLED` | Master toggle |

## Storage

```
/root/local/users/{name}/
  metadata.json                      # Shared identity (telegram, display_name)
  voice/
    embedding.npy                    # L2-normalized aggregated vector [256]
    metadata.json                    # num_samples, dim, timestamps
    sample_{origin}_{ts}_{uuid}.wav  # Individual enrollment samples (16kHz mono)

/tmp/lumi-unknown-voice/
  incoming_{ts}_{uuid}.wav           # Unrecognized audio (auto-cleanup)
```

## API Endpoints (LeLamp, port 5001)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/speaker/enroll` | Enroll voice from wav_paths + name |
| `POST` | `/speaker/recognize` | Recognize speaker from wav_path |
| `POST` | `/speaker/identity` | Link Telegram identity to existing profile |
| `POST` | `/speaker/remove` | Remove voice profile by name |
| `POST` | `/speaker/reset` | Remove all voice profiles |
| `GET`  | `/speaker/list` | List enrolled speakers |

### Error contract

`/speaker/enroll` distinguishes two failure classes:

| HTTP | When | Skill behavior |
|------|------|----------------|
| `400` | Audio-level reject (too short, silent, VAD found no speech, dlbackend returned 4xx) | Ask user to re-record / speak more clearly |
| `503` | Embedding service unreachable (network, 5xx, malformed response) | Tell user to try again shortly — nothing on disk was modified |

`/speaker/recognize` never fails with 5xx for embedding outages — it returns `200` with `{name: "unknown", error: "<reason>"}` so the skill can gracefully degrade. Only input-level problems (missing WAV, bad base64) return `400`.

## Key Code Locations

| Component | File | Function/Struct |
|-----------|------|-----------------|
| STT → speaker ID | `lelamp/service/voice/voice_service.py` | `_identify_and_decorate()` |
| Enroll gate | `lelamp/service/voice/voice_service.py` | `_should_request_enroll()` |
| Message formatting | `lelamp/service/voice/voice_service.py` | `_format_unknown_speaker()` |
| Speaker recognizer | `lelamp/service/voice/speaker_recognizer/speaker_recognizer.py` | `SpeakerRecognizer` |
| Nudge injection + cooldown | `lumi/domain/voice.go` | `AppendEnrollNudge()` |
| Direct event path | `lumi/server/sensing/delivery/http/handler.go` | `PostEvent()` |
| Drain/replay path | `lumi/internal/openclaw/service.go` | `drainPendingEvents()` |
| Agent skill | `lumi/resources/openclaw-skills/speaker-recognizer/SKILL.md` | — |
| Embedding model | `dlbackend/src/core/audio_recognition/audio_recognizer.py` | `WeSpeakerResNet34Recognizer` |
| Embedding endpoint | `dlbackend/src/protocols/htpp/audio_recognizer.py` | `embed_audio()` |
| Config | `lelamp/config.py` | `SPEAKER_*` constants |

## Message Flow Examples

### Short utterance (blocked)
```
User says: "hey" (2 words, 0.9s audio)
→ LeLamp: skip recognition (< SPEAKER_MIN_AUDIO_S)
→ Message: "hey" (no prefix, no enroll instruction)
```

### Medium utterance (recognized but no enroll nudge)
```
User says: "turn on the lights please" (5 words, 3s audio)
→ LeLamp: recognize → unknown, _should_request_enroll(5 words, 3s) = false
→ Message: "Unknown Speaker: turn on the lights please"
→ Lumi: no "audio save at" in message → AppendEnrollNudge returns unchanged
→ Agent: responds normally, doesn't ask who user is
```

### Long utterance (full enroll flow)
```
User says: "Hi my name is Leo and I just got home from work..." (30 words, 8s audio)
→ LeLamp: recognize → unknown, _should_request_enroll(30 words, 8s) = true
→ Message: "Unknown Speaker: Hi my name is Leo... (audio save at /tmp/lumi-unknown-voice/incoming_xxx.wav, auto enroll...)"
→ Lumi: AppendEnrollNudge → cooldown OK → append "[REQUIRED: Follow speaker-recognizer/SKILL.md...]"
→ Agent: detects "my name is Leo" → POST /speaker/enroll → "Nice to meet you, Leo!"
```

### Cooldown (blocked)
```
Same unknown speaker, 2 minutes later:
→ LeLamp: _should_request_enroll = true (long enough)
→ Message has "audio save at"
→ Lumi: AppendEnrollNudge → cooldown NOT elapsed (< 5 min) → skip instruction
→ Agent: sees "Unknown Speaker: ..." without SKILL instruction → responds normally
```
