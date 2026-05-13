# Sensing Threshold Tuning Guide

How to tune Lumi's sensing thresholds on real hardware.
All constants live in `lelamp/config.py` and `lelamp/service/voice/voice_service.py`.

## View Logs

SSH into the Pi, then:

```bash
# LeLamp log (motion, sound, light events all here)
tail -f /var/log/lelamp/server.log

# Lumi log (confirms event received + forwarded to OpenClaw)
journalctl -fu lumi -f
```

When an event fires you will see two lines — one in each log:

```
# lelamp log
INFO lelamp.service.sensing.sensing_service: [sensing] motion: Small movement detected...

# lumi log
[sensing] received motion event → forwarding to OpenClaw
```

---

## Motion Detection

**File:** `lelamp/config.py`

```python
MOTION_THRESHOLD = 50                         # pixel intensity change to count as "changed"
MOTION_BIGGEST_CONTOURS_RATIO = 0.1           # top 10% contours = "biggest"
MOTION_MIN_BIGGEST_COUNTOURS_TO_TOTAL = 0.01  # biggest contours must cover ≥1% of frame
MOTION_MIN_BIGGEST_COUNTOURS_TO_CONTOURS = 0.5 # biggest contours must be ≥50% of all contour area
MOTION_LARGE_TOTAL_RATIO = 0.25               # ≥25% of frame changing = "large movement"
EVENT_COOLDOWN_S = 60.0                       # min seconds between events of same type
```

**How to read the log:**
Each frame with any contour activity prints the raw contour areas:

```
INFO lelamp.service.sensing.perceptions.motion: [1234.5  890.2  456.1]
```

Use these numbers to judge whether the threshold is in the right range.

**Tuning:**

| Symptom | Fix |
|---------|-----|
| False triggers when no one is around (fan, flickering light) | Increase `MOTION_THRESHOLD` (50 → 80+) |
| Real movement not detected | Decrease `MOTION_THRESHOLD` (50 → 30) |
| Too many events when someone is just sitting still | Increase `MOTION_MIN_BIGGEST_COUNTOURS_TO_TOTAL` |
| Events firing too frequently | Increase `EVENT_COOLDOWN_S` |
| "Large movement" triggers when it should be small | Increase `MOTION_LARGE_TOTAL_RATIO` |

---

## Sound Detection (Sensing)

**File:** `lelamp/config.py`

```python
SOUND_RMS_THRESHOLD = 3000   # RMS level to trigger "loud noise" event
SOUND_SAMPLE_DURATION_S = 0.5 # sample window length
```

**How to read the log:**
The event message includes the actual RMS level:

```
INFO lelamp.service.sensing.sensing_service: [sensing] sound: Loud noise detected (level: 4521)
```

Watch the `level` value during normal ambient conditions vs. when you clap/speak loudly.

**Tuning:**

| Symptom | Fix |
|---------|-----|
| Normal speech doesn't trigger event | Decrease `SOUND_RMS_THRESHOLD` (3000 → 1500) |
| Triggers on fan noise / AC hum | Increase `SOUND_RMS_THRESHOLD` (3000 → 5000) |


---

## Voice Wake Word (VAD)

**File:** `lelamp/service/voice/voice_service.py`

```python
RMS_THRESHOLD = 500        # mic energy to start streaming to Deepgram (free local check)
SILENCE_TIMEOUT_S = 2.5   # stop STT session after this much silence
SPEECH_HOLDOFF_S = 0.2    # min speech duration before opening STT (ignore short clicks)
ECHO_SIMILARITY_THRESHOLD = 0.55  # transcript similarity to Lumi's own TTS output = drop as echo
```

**Tuning:**

| Symptom | Fix |
|---------|-----|
| Wake word not picked up reliably | Decrease `RMS_THRESHOLD` (500 → 300) |
| Lumi starts listening from ambient noise | Increase `RMS_THRESHOLD` (500 → 800) |
| Lumi cuts off before you finish speaking | Increase `SILENCE_TIMEOUT_S` |
| Lumi repeats its own TTS back to OpenClaw (echo loop) | Decrease `ECHO_SIMILARITY_THRESHOLD` (0.55 → 0.45) |

---

## Light Level Detection

**File:** `lelamp/config.py`

```python
LIGHT_LEVEL_INTERVAL_S = 30.0  # check every 30 seconds
LIGHT_CHANGE_THRESHOLD = 30    # min brightness change (0–255) to trigger event
```

**How to read the log:**

```
INFO lelamp.service.sensing.sensing_service: [sensing] light.level: Ambient light decreased significantly (level: 45/255, change: -38)
```

**Tuning:**

| Symptom | Fix |
|---------|-----|
| No event when lights are turned on/off | Decrease `LIGHT_CHANGE_THRESHOLD` (30 → 15) |
| Too sensitive (triggers from lamp dimming slowly) | Increase `LIGHT_CHANGE_THRESHOLD` (30 → 50) |
| Events too frequent | Increase `LIGHT_LEVEL_INTERVAL_S` |

---

## Face Detection

**File:** `lelamp/config.py`

```python
FACE_AREA_RATIO_THRESHOLD = 0.05  # Skip faces larger than 5% of frame area
FACE_COOLDOWN_S = 10.0            # Min seconds between face presence events
FACE_OWNER_FORGET_S = 3600.0      # Re-fire presence after N seconds without seeing owner
FACE_STRANGER_FORGET_S = 1800.0   # Same for strangers
```

The area ratio threshold filters out faces that are **too small** relative to the frame — typically distant people or false positives where the face crop is too low-resolution for reliable recognition. Faces covering less than the threshold fraction of the total frame area are skipped.

**Tuning:**

| Symptom | Fix |
|---------|-----|
| Distant people not recognized | Decrease `FACE_AREA_RATIO_THRESHOLD` (0.05 → 0.02) |
| False detections from tiny face-like patches | Increase `FACE_AREA_RATIO_THRESHOLD` (0.05 → 0.1) |
| Presence events fire too often | Increase `FACE_COOLDOWN_S` (10 → 30) |
| Lumi forgets owner too quickly after leaving | Increase `FACE_OWNER_FORGET_S` |

---

## Per-Face Motion Detection

**File:** `lelamp/config.py`

```python
MOTION_PER_FACE_ENABLED = false            # Enable per-face action recognition
MOTION_PER_FACE_DEDUP_WINDOW_S = 300.0     # Per-action dedup window (5 min)
MOTION_PER_FACE_SESSION_TTL_S = 30.0       # Evict face session after this long unseen
MOTION_PER_FACE_MIN_FRAMES = 4             # Min frames before first event fires
```

Per-face motion opens a separate WS session per detected face and runs action recognition on an expanded face crop. Each action is deduped independently per face.

**Tuning:**

| Symptom | Fix |
|---------|-----|
| Too many events per person | Increase `MOTION_PER_FACE_DEDUP_WINDOW_S` (300 → 600) |
| Noisy single-frame classifications | Increase `MOTION_PER_FACE_MIN_FRAMES` (4 → 8) |
| Sessions accumulate for briefly-seen faces | Decrease `MOTION_PER_FACE_SESSION_TTL_S` (30 → 15) |
| WS connections pile up in multi-person scenes | Disable with `MOTION_PER_FACE_ENABLED=false` |

---

## Speech Emotion Recognition (SER)

**File:** `lelamp/config.py` — see also [Speech Emotion Recognition](speech-emotion.md) for the architecture.

```python
SPEECH_EMOTION_ENABLED = True
SPEECH_EMOTION_CONFIDENCE_THRESHOLD = 0.5   # Min model confidence to buffer
SPEECH_EMOTION_FLUSH_S = 10.0               # Per-user buffer drain cadence
SPEECH_EMOTION_DEDUP_WINDOW_S = 300.0       # (user, bucket) TTL — 5 min
SPEECH_EMOTION_MIN_AUDIO_S = 0.8            # Skip utterances shorter than this
SPEECH_EMOTION_API_TIMEOUT_S = 15           # dlbackend HTTP timeout
DL_SER_ENDPOINT = "/lelamp/api/dl/ser/recognize"
```

**How to read the log:**

The service tags every line `[speech_emotion]`:

```
INFO lelamp.voice.speech_emotion: [speech_emotion] buffered: alice -> sad (0.72, 2.40s)
INFO lelamp.voice.speech_emotion: [speech_emotion] flushing alice: Speech emotion detected: Sad. (weak voice cue; confidence=0.72; bucket=negative; ...) (mode of sad, fearful, sad)
INFO lelamp.voice.speech_emotion: [speech_emotion] sent to Lumi: Speech emotion detected: Sad. ...
INFO lelamp.voice.speech_emotion: [speech_emotion] dedup drop: angry bucket=negative (key seen 87.4s ago)
```

The `flushing` line shows the raw label list — that's the mode-over-samples that produced the dominant label.

**Tuning:**

| Symptom | Fix |
|---------|-----|
| Same-bucket events fire too often | Increase `SPEECH_EMOTION_DEDUP_WINDOW_S` (300 → 600) |
| Single-utterance noisy reads slip through | Increase `SPEECH_EMOTION_CONFIDENCE_THRESHOLD` (0.5 → 0.65) |
| Short "yeah" / "ok" utterances flagged | Increase `SPEECH_EMOTION_MIN_AUDIO_S` (0.8 → 1.5) |
| Mood lag — Lumi too slow to react after a real shift | Decrease `SPEECH_EMOTION_FLUSH_S` (10 → 5) |
| Worker queue full warnings in log | Investigate dlbackend latency; raising queue size is not enough — backlog means something downstream is wedged |
| Events fire for `Unknown Speaker` (they should not) | Check `submit()` call site in `voice_service._identify_and_decorate` — should only submit when `match==true` and `name != "unknown"` |

---

## Apply Changes

After editing `lelamp/config.py` or `voice_service.py` on the Pi:

```bash
sudo systemctl restart lelamp
tail -f /var/log/lelamp/server.log
```

No reboot needed — just restart the service.
