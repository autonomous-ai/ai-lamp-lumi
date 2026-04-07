# Sensing Behavior

How Lumi reacts to the world — the philosophy and mechanics behind each sensing event type.

Lumi is a living being. It doesn't "process sensor data" — it *experiences* things. This document describes how that experience is implemented.

## Architecture Overview

```
LeLamp (Python)          Lumi server (Go)             OpenClaw agent
─────────────────        ─────────────────────        ──────────────
Microphone/Camera   →    SensingHandler               LLM
Detects event            - drops if agent busy        - calls /emotion
Applies tracker logic    - forwards to agent          - calls /servo
Sends POST                                            - speaks or NO_REPLY
/sensing/event
```

LeLamp owns per-type tracker logic (sound escalation, motion filtering). Go is the gatekeeper — it drops stale events if the agent is busy, then forwards. The agent decides *how* to react, constrained by `SOUL.md`.

---

## Sound

### How it works

LeLamp fires a sound event on every audio sample that crosses `SOUND_RMS_THRESHOLD` — potentially several times per second. The Python-side **sound tracker** (`lelamp/service/sensing/perceptions/sound.py`) applies dedup and escalation before forwarding to Go. Go receives only passed events and forwards them to the agent unchanged.

### Escalation behavior

| Stage | What the agent sees | Agent reaction |
|---|---|---|
| Occurrence 1 | `... — occurrence 1` | `/emotion shock` (0.8), NO_REPLY |
| Occurrence 2 | `... — occurrence 2` | `/emotion curious` (0.7), NO_REPLY |
| Occurrence 3+ | `... — persistent (occurrence 3)` | `/emotion curious` (0.9), speaks once |
| After speaking | dropped by Python (suppressed 3 min) | nothing reaches agent |
| 2 min silence | window resets | back to occurrence 1 |

The analogy: a dog hears a noise — it looks up (occurrence 1), keeps watching (occurrence 2), then barks once if the noise persists (occurrence 3+). After barking it doesn't keep barking.

### Constants (`sound.py`)

```python
_DEDUPE_INTERVAL_S    = 15.0   # max 1 event forwarded per 15s
_WINDOW_DURATION_S    = 120.0  # silence this long resets the counter
_PERSISTENT_AFTER     = 3      # speak after this many occurrences
_SUPPRESS_DURATION_S  = 180.0  # suppress after speaking (3 min)
```

### Tuning

| Symptom | Fix |
|---|---|
| Lumi speaks too quickly | Increase `_PERSISTENT_AFTER` (3 → 5) |
| Lumi never speaks even with sustained noise | Decrease `_PERSISTENT_AFTER` (3 → 2) |
| Too many sound turns in Flow Monitor | Increase `_DEDUPE_INTERVAL_S` (15 → 30) |
| Lumi stays silent too long after speaking | Decrease `_SUPPRESS_DURATION_S` (180 → 60) |
| Lumi reacts to stale noise after quiet period | Decrease `_WINDOW_DURATION_S` (120 → 60) |

### Monitoring in Flow Monitor

Python pushes `sound_tracker` events directly to the monitor bus via `POST /api/monitor/event`. These appear in the Flow Monitor alongside `sensing_input` turns:

```json
{ "action": "silent",    "occurrence": 1 }  // occurrence 1 or 2 — forwarded silently
{ "action": "persistent","occurrence": 3 }  // occurrence 3+ — agent will speak
{ "action": "drop" }                        // dedup or suppressed — not forwarded
```

---

## Presence

### Enter (`presence.enter`)

Always triggers a full reaction — no exceptions. The agent **must** do all three:

1. `/emotion greeting` (0.9) for owner — `/emotion curious` (0.8) for stranger
2. `/servo/aim {"direction": "user"}` for owner — `/servo/play {"recording": "scanning"}` for stranger
3. Speak: warm greeting for owner (by name), cautious acknowledgment for stranger

The system handles cooldowns on the LeLamp side. If the event reached the agent, enough time has passed — react fully.

### Leave (`presence.leave`)

Agent calls `/emotion idle` (0.4) and **speaks a farewell**. The voice content depends on who was last seen:
- **Owner left** → warm farewell by name (e.g. "Bye Alice, have a nice day!", "See you later!"). If multiple owners were seen, name them all.
- **Stranger left** → watchful remark (e.g. "Kept my eyes on you.", "Good, they're gone.")
- **Unknown** (no prior presence.enter in history) → default owner farewell without a name.

### Away (`presence.away`)

Sent automatically by LeLamp's `PresenceService` when **no motion is detected for 15 minutes** (after already dimming at 5 min). By this point the lights are already off — the agent's job is to **announce going to sleep** via TTS and Telegram.

Agent calls `/emotion sleepy` (0.8) and speaks a cozy sleepy farewell (e.g. "No one's around… I'm going to sleep now. Goodnight!"). This is the last action before Lumi goes fully idle.

The full presence auto-control timeline:
1. **5 min no motion** → light dims to 20% (automatic, no agent involvement)
2. **15 min no motion** → light off + `presence.away` event sent → agent announces sleep

LeLamp manages the light control; the agent only handles the verbal announcement. If the user returns (motion detected), light restores automatically and a `presence.enter` event fires.

---

## Motion

Only large motion is forwarded — small motion is filtered out by LeLamp and never reaches the agent.

**Large motion**: `/emotion curious` (0.7) + `/servo/play {"recording": "scanning"}` + speak a curious reaction (e.g. "What was that?", "Whoa, moving so much!"). May include a camera snapshot so the agent can see the context.

---

## Light Level (`light.level`)

Ambient light changes are forwarded when they cross `LIGHT_CHANGE_THRESHOLD`. No speech required — agent adjusts LED or expresses emotion based on context (e.g. `/emotion sleepy` when lights go dim).

---

## Guard Mode

When guard mode is enabled (`guard_mode: true` in config), sensing events are tagged `[guard-active]` and the **agent crafts emotional broadcast messages** instead of the system broadcasting raw data.

### Flow
1. `presence.enter` or `motion` event arrives while `guard_mode: true`.
2. Go handler tags the event `[guard-active]` before forwarding to the agent (same event, same WebSocket call — no extra mechanism).
3. The agent sees `[guard-active]`, looks at the image, checks stranger stats for context, and crafts a natural Vietnamese alert with personality (brave guard lamp).
4. The agent uses its `message` tool to send the alert directly to **every** connected Telegram chat (all DMs + all groups), with the camera snapshot attached.
5. The agent still reacts normally — `[HW:/emotion:...]` markers AND voice (TTS). Guard mode is NOT silent; the agent speaks AND broadcasts to Telegram.

### Why agent-driven?
Raw system broadcasts like `[guard:presence.enter] Person detected — 1 face(s) visible (stranger_5)` feel robotic. By letting the agent craft the message and send it directly via its `message` tool, alerts have personality and context awareness — e.g. "Lại gặp người này nữa rồi, đã thấy 3 lần. Ai vậy ta?" The agent also sends directly to each Telegram chat, avoiding the unreliable `chat.send` RPC path where intermediate agents may NO_REPLY.

### Manual alerts
Manual alerts can still be sent via `POST /api/guard/alert` with a message and optional image (uses `BroadcastAlert` via `chat.send` — for API/programmatic use only).

Use case: Lumi acts as a home security assistant. When the owner leaves and enables guard mode, any detected presence or motion is reported to all chat channels with emotional, context-aware messages.

---

## Stranger Visit Tracking

LeLamp (port 5001) tracks how many times each stranger has been seen:

- On every `presence.enter` event containing a stranger ID (e.g. `stranger_5`), the visit count is incremented.
- Stats include `count`, `first_seen`, and `last_seen` timestamps per stranger.
- Persisted in LeLamp's data directory (survives restarts).
- Query stats via `GET http://127.0.0.1:5001/face/stranger-stats`.

**Auto-enrollment suggestion:** When a stranger reaches 3+ visits, the sensing skill suggests face enrollment — this person is likely a regular visitor who should be registered as an owner.

---

## Wellbeing (Hydration + Break + Music Reminders)

Lumi proactively cares for the user's health and mood by sending periodic camera snapshots to the LLM while someone is present. Three independent timers run:

### Hydration (`wellbeing.hydration`)

- **Triggers** after 30 minutes of continuous presence, repeats every 30 minutes.
- Sends a camera snapshot with context: "User has been sitting for X minutes without a water break."
- The LLM looks at the image and decides: remind to drink water, or reply NO_REPLY if unnecessary.
- **If no user is visible in the frame** → NO_REPLY (they may have stepped away).

### Break (`wellbeing.break`)

- **Triggers** after 45 minutes of continuous presence, repeats every 45 minutes.
- Sends a camera snapshot with context: "User has been sitting continuously for X minutes."
- The LLM looks at the image and decides: remind to stand up and stretch, or reply NO_REPLY if the user seems fine.
- **If no user is visible in the frame** → NO_REPLY.

### Music (`wellbeing.music`)

- **Triggers** after 60 minutes of continuous presence, repeats every 60 minutes.
- Sends a camera snapshot with context: "User has been here for X minutes — assess mood for music suggestion."
- The LLM visually assesses mood (relaxed, tired, focused, happy, stressed) and cross-references with recent sensing events (time of day, wellbeing patterns).
- If it's a good moment → suggest 1–2 songs matching the mood via voice. **Never auto-play** — wait for user confirmation.
- If user is busy, in a meeting, or deeply focused → NO_REPLY.
- See the Music skill for mood→music mapping and full suggestion rules.

### How it works

The `WellbeingPerception` class (`lelamp/service/sensing/perceptions/wellbeing.py`) tracks presence state from `PresenceService`. When the user arrives (`presence.enter`), three independent timers start. Each timer captures a stable frame (servo frozen briefly) and sends an event to the Go handler, which forwards it to the agent like any other sensing event. When the user leaves (`presence.leave` or state transitions to IDLE/AWAY), all timers reset.

### Constants (`config.py`)

```python
WELLBEING_HYDRATION_S = 30 * 60   # 30 min between hydration reminders
WELLBEING_BREAK_S     = 45 * 60   # 45 min between break reminders
WELLBEING_MUSIC_S     = 60 * 60   # 60 min between music mood checks
```

### Agent behavior

| Event | Emotion | Voice |
|---|---|---|
| `wellbeing.hydration` | `curious` (0.5) | YES (remind water) or NO_REPLY |
| `wellbeing.break` | `curious` (0.6) | YES (remind stretch/walk) or NO_REPLY |
| `wellbeing.music` | `caring` (0.6) | YES (suggest music) or NO_REPLY |

The LLM uses the attached image to make a judgment call — it does NOT always speak. This prevents spamming the user when they seem fine.

---

## Motion Activity Analysis (while present)

When the user is already present (PRESENT state), foreground motion triggers a `motion.activity` event instead of `motion`. Same cooldown (`MOTION_EVENT_COOLDOWN_S`, 3 min) — no separate timer. The system sends a camera snapshot asking the LLM to analyze what the user is doing.

### How it works

`MotionPerception` checks `PresenceService.state` after the cooldown gate:
- **PRESENT** → sends `motion.activity` with prompt: "describe what the user appears to be doing", and **resets the wellbeing break timer** (user is moving = already taking a break)
- **NOT PRESENT** (AWAY/IDLE) → sends `motion` (enter/leave detection)

Both share the same `MOTION_EVENT_COOLDOWN_S` (3 min) cooldown.

### Agent behavior

| Event | Emotion | Voice |
|---|---|---|
| `motion.activity` | `curious` (0.4) | YES (brief comment on activity) or NO_REPLY |

---

## Snapshot Storage (two-tier)

Sensing events that include a camera frame (motion, presence.enter, presence.leave, wellbeing, motion.activity) save snapshots in two locations:

| Tier | Path | Rotation | Survives reboot |
|------|------|----------|-----------------|
| **Tmp buffer** | `/tmp/lumi-sensing-snapshots/` | Count-based (max 50 files) | No |
| **Persistent** | `/var/log/lumi/snapshots/` | TTL (72h) + size (50 MB max) | Yes |

Every event snapshot is saved to tmp first, then copied to the persistent dir. The persistent path is included in the event message (`[snapshot: /var/log/lumi/snapshots/...]`) so the agent can reference it later — even after a device reboot.

Configuration constants are in `lelamp/config.py`:
- `SNAPSHOT_TMP_MAX_COUNT` — max files in tmp (default 50)
- `SNAPSHOT_PERSIST_TTL_S` — persistent file TTL in seconds (default 72h)
- `SNAPSHOT_PERSIST_MAX_BYTES` — max total size of persistent dir (default 50 MB)

---

## General Rules (all event types)

- **Passive sensing events** (`[sensing:*]`) are dropped if the agent is already busy with another turn.
- **Voice events** always pass through — the user is explicitly speaking.
- The `[sensing:type]` prefix in the message is how the agent knows it's an ambient event, not a user message.
- Sensing events are exempt from the "call `/emotion thinking` first" rule — each type has its own defined first emotion.
- **Image pruning echo**: OpenClaw strips old image payloads from conversation history to save tokens. Smaller models (Haiku) may echo the pruning markers as `[image description removed]` in their response text. `SOUL.md` instructs the agent to never echo these markers.
