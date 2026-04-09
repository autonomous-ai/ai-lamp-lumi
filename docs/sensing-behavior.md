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

When guard mode is enabled (`guard_mode: true` in config), sensing events are tagged `[guard-active]` and the **agent broadcasts alerts directly** using its `message` tool.

### Flow
1. `presence.enter` or `motion` event arrives while `guard_mode: true`.
2. Go handler tags the event `[guard-active]` and marks the runID as a guard run (with snapshot path). If `guard_instruction` is set in config, it is appended as `[guard-instruction: ...]`.
3. The agent processes the event — emotion, servo, TTS response, plus any custom guard instruction (e.g. play music, flash LEDs).
4. When the agent's response arrives (SSE lifecycle end), the Go SSE handler detects the guard run.
5. The agent's natural response text + camera snapshot are sent directly via **Telegram Bot API** (`sendPhoto`) to all connected Telegram chats.
6. Delivery is 100% reliable — bypasses OpenClaw agent processing entirely.

### Custom guard instructions
The owner can provide a custom instruction when enabling guard mode (e.g. "play scary sound when stranger appears"). The instruction is saved in `guard_instruction` in config and injected into every guard sensing event as `[guard-instruction: ...]`. The agent follows this instruction using available skills (music, LED, etc.).

### Why this approach?
After trying 6 different approaches (see below), this hybrid proved the most reliable:
- **Agent crafts the message** → natural, context-aware, with personality
- **Go side delivers** → direct Telegram Bot API, guaranteed delivery, no agent NO_REPLY risk
- **Agent follows custom guard instructions** → owner can combine guard mode with any skill (music, LED, etc.)

### Solution evolution (2026-04-07)
| # | Approach | Why it failed |
|---|----------|---------------|
| 1 | `BroadcastAlert` via WS `chat.send` RPC | `chat.send` goes through agent → 2/3 NO_REPLY |
| 2 | Agent-driven via `[guard-active]` tag | Haiku ignored SKILL instruction (buried at line 222) |
| 3 | Move instruction to top of SKILL.md | Haiku still ignored |
| 4 | Go-side emotional templates + `BroadcastAlert` | Agents recognize `sender: node-host` → ignore. No image attached |
| 5 | Agent-driven + SOUL.md enforcement | Better compliance but not 100%. Token mismatch issues |
| 6 | **Hook agent response + Telegram Bot API** | ✅ Agent crafts message naturally, Go delivers 100% |

> **Note:** `BroadcastAlert` (WS RPC approach) has been removed. All broadcasting now uses `Broadcast()` which sends directly via Telegram Bot API.

### Manual alerts
Manual alerts can be sent via `POST /api/guard/alert` with a message and optional image. This now uses `Broadcast()` (direct Bot API) instead of the old WS-based `BroadcastAlert`.

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

## Wellbeing (AI-Driven Hydration + Break Reminders)

Lumi proactively cares for the user's health using AI-driven cron jobs managed by the OpenClaw agent. Instead of hardcoded timers, the agent decides reminder intervals based on scientific recommendations and the user's historical patterns.

### How it works

The agent maintains a personal notebook **per person** at `/root/local/wellbeing-notes-{name}.md` (e.g., `wellbeing-notes-alice.md`) where it writes observations about each person's habits over time (e.g., "ignores hydration before lunch", "responds well to break reminders after 15:00", "prefers gentle phrasing"). This notebook is the agent's own — it creates, updates, and learns from it.

When a known person arrives (`presence.enter`), the agent:

1. **Reads their notebook** to recall what it has learned about their patterns.
2. **Decides intervals and approach** based on its observations, time of day, and how they looked when arriving. First-time defaults are science-based (~25 min hydration, ~50 min break), but the agent adapts over sessions.
3. **Schedules two cron jobs** via `cron.add` (kind: `every`):
   - `"Wellbeing: hydration check"` — takes a camera snapshot, checks presence, reminds if appropriate
   - `"Wellbeing: break check"` — takes a camera snapshot, assesses posture/fatigue, reminds if appropriate

When they leave (`presence.leave`), the agent cancels both cron jobs and updates their notebook with observations from the session (which reminders landed, which were ignored, timing insights).

### Cron-fired behavior

Each cron fires an agent turn. The agent:
1. Takes a camera snapshot (`GET http://127.0.0.1:5001/camera/snapshot`)
2. Checks presence (`GET http://127.0.0.1:5001/presence`)
3. If user is present and the reminder is warranted → one short sentence, varied phrasing
4. If user is absent, already has a drink, or looks fine → no response
5. Always emits `[HW:/emotion:{...}]` marker

### Agent behavior

| Reminder | Emotion | Voice |
|---|---|---|
| Hydration cron | `caring` (0.5) | YES (remind water) or silent |
| Break cron | `caring` (0.6) | YES (remind stretch/walk) or silent |

The agent uses the camera snapshot to make a judgment call — it does NOT always speak. This prevents spamming the user when they seem fine.

### Music Suggestions (AI-Driven)

Music suggestions are **no longer** triggered by a hardcoded timer. Instead, the AI agent **self-schedules** music checks via OpenClaw cron jobs and **learns** the user's habits over time:

- **Self-scheduling:** On first `presence.enter` of the day, the AI creates a cron job (default: every 60 min). It adjusts the interval based on user response patterns.
- **Data-driven decisions:** Before suggesting, the AI queries:
  - `GET /presence` — is user present?
  - `GET /camera/snapshot` — visual mood assessment
  - `GET /api/openclaw/mood-history` — presence patterns, past suggestion outcomes
  - `GET /audio/history` — listening history (genre preference, duration, satisfaction)
- **Learning loop:** The AI correlates suggestions with `music.play` events in mood history. Accepted suggestions reinforce timing/genre; rejected suggestions trigger schedule adjustments.
- **Personalization:** Over time, the AI learns when the user prefers music, what genres they enjoy, and how long they typically listen — adapting its suggestions accordingly.

See the Music skill (`resources/openclaw-skills/music/SKILL.md`) for full implementation details.

---

## Motion Activity Analysis (while present)

When the user is already present (PRESENT state), foreground motion triggers a `motion.activity` event instead of `motion`. Same cooldown (`MOTION_EVENT_COOLDOWN_S`, 3 min) — no separate timer. The system sends a camera snapshot asking the LLM to analyze what the user is doing.

### How it works

`MotionPerception` checks `PresenceService.state` after the cooldown gate:
- **PRESENT** → sends `motion.activity` with prompt: "describe what the user appears to be doing"
- **NOT PRESENT** (AWAY/IDLE) → sends `motion` (enter/leave detection)

Both share the same `MOTION_EVENT_COOLDOWN_S` (3 min) cooldown.

### Wellbeing cron reset (LLM-driven)

When the agent responds to `motion.activity`, it visually assesses what the user is doing and resets the appropriate wellbeing cron job:

- User stretching/standing → `cron.remove` the break check job, then `cron.add` it again with the same interval (resets the timer to zero)
- User drinking water → `cron.remove` the hydration check job, then `cron.add` it again with the same interval

The agent uses consistent job names (`"Wellbeing: hydration check"`, `"Wellbeing: break check"`) to find and reset them. This way the LLM decides *which* cron to reset based on what it actually sees — stretching ≠ drinking water.

### Agent behavior

| Event | Emotion | Voice |
|---|---|---|
| `motion.activity` | `curious` (0.4) | YES (brief comment on activity) or NO_REPLY |

---

## Snapshot Storage (two-tier)

Sensing events that include a camera frame (motion, presence.enter, presence.leave, music.mood, motion.activity) save snapshots in two locations:

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
