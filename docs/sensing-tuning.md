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

## Apply Changes

After editing `lelamp/config.py` or `voice_service.py` on the Pi:

```bash
sudo systemctl restart lelamp
tail -f /var/log/lelamp/server.log
```

No reboot needed — just restart the service.
