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

1. `/emotion greeting` (0.9) for friend — `/emotion curious` (0.8) for stranger
2. `/servo/aim {"direction": "user"}` for friend — `/servo/play {"recording": "scanning"}` for stranger
3. Speak: warm greeting for friend (by name), cautious acknowledgment for stranger

The system handles cooldowns on the LeLamp side. If the event reached the agent, enough time has passed — react fully.

### Leave (`presence.leave`)

Agent calls `/emotion idle` (0.4) and replies **NO_REPLY** (silent — no TTS). This avoids noisy loops when people come and go frequently. The agent still processes the event internally to cancel wellbeing crons and update daily logs.

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

When guard mode is enabled (`guard_mode: true` in config), Lumi becomes an **alert watchdog** — reacting dramatically to strangers and broadcasting alerts to Telegram.

### Flow
1. `presence.enter` or `motion` event arrives while `guard_mode: true`.
2. Go handler tags the event `[guard-active]` and marks the runID as a guard run (with snapshot path). If `guard_instruction` is set in config, it is appended as `[guard-instruction: ...]`.
3. The agent processes the event — **dramatic** emotion, servo, TTS response, plus any custom guard instruction (e.g. play music, flash LEDs).
4. When the agent's response arrives (SSE lifecycle end), the Go SSE handler detects the guard run.
5. The agent's natural response text + camera snapshot are sent directly via **Telegram Bot API** (`sendPhoto`) to all connected Telegram chats.
6. Delivery is 100% reliable — bypasses OpenClaw agent processing entirely.

### Guard mode emotions (dramatic)

When guard mode is active, stranger/motion events trigger **much stronger** emotions than normal sensing:

| Guard event | HW markers | Voice |
|---|---|---|
| Stranger detected | `shock` (1.0) → `curious` (0.9) + servo shock | Genuinely scared/startled reaction |
| Motion (no known face) | `shock` (0.9) → `curious` (0.8) + servo scanning | Nervous/alert reaction |
| Stranger left | `curious` (0.7) + scanning | Report they left, stay vigilant |
| Friend returns | `greeting` (0.9) + servo aim | Greet + recap what happened during guard + ask to disable |

The agent's **spoken words must also carry emotion** — not dry security reports. Examples: "Oh no, who is that?!", "Someone's here... I'm shaking...", "Hey, this person looks really suspicious...". Each reaction should feel different.

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

**Auto-enrollment suggestion:** When a stranger reaches 3+ visits, the sensing skill suggests face enrollment — this person is likely a regular visitor who should be registered as a friend.

---

## Wellbeing (AI-Driven Hydration + Break Reminders)

Lumi proactively cares for the user's health using AI-driven cron jobs managed by the OpenClaw agent. Instead of hardcoded timers, the agent decides reminder intervals based on scientific recommendations and the user's historical patterns.

### How it works

The agent maintains **per-person wellbeing data** under `/root/local/users/{name}/`:

- **`wellbeing.md`** — summary of accumulated habits and patterns (e.g., "ignores hydration before lunch", "responds well to break reminders after 15:00")
- **`wellbeing/YYYY-MM-DD.md`** — daily log, appended throughout the day on `motion.activity` resets (e.g. `14:30 — drinking beer (hydration reset)`) and summarized on `presence.leave`

The agent reads the summary + today's daily log on `presence.enter` to quickly recall the person and know what happened earlier today (e.g. if the user left and came back). Daily log is updated continuously during `motion.activity` and finalized on `presence.leave`.

When a known person arrives (`presence.enter`), the agent:

1. **Reads their notebook** (`wellbeing.md`) to recall what it has learned about their patterns.
2. **Reads today's daily log** (`wellbeing/YYYY-MM-DD.md`) to know what happened earlier today — how many times they drank, took breaks, etc. Used to adjust cron intervals.
3. **Decides intervals and approach** based on its observations, time of day, and how they looked when arriving. First-time defaults are science-based (~25 min hydration, ~50 min break), but the agent adapts over sessions.
4. **Cleans up stale crons** — removes any leftover wellbeing crons from previous sessions (crash recovery).
5. **Schedules two cron jobs** via `cron.add` (kind: `every`), named per-user to avoid collisions:
   - `"Wellbeing: {name} hydration"` — every 6 min (360000ms), takes a camera snapshot, checks presence, reminds if appropriate
   - `"Wellbeing: {name} break"` — every 5 min (300000ms), takes a camera snapshot, assesses posture/fatigue, reminds if appropriate

> **Note:** Wellbeing is now a standalone skill (`wellbeing/SKILL.md`). The sensing handler injects a nudge message into `presence.enter` events reminding the agent to follow the Wellbeing and Music skills for cron setup.

### Cron sessionTarget rules

OpenClaw cron has two valid combos — do NOT mix:

| sessionTarget | payload.kind | payload field | Use case |
|---|---|---|---|
| `main` | `systemEvent` | `text` | Needs conversation context (music, wellbeing) |
| `isolated` | `agentTurn` | `message` | Fresh session each fire |

`main` + `agentTurn` is **rejected** by OpenClaw. Do NOT add a `delivery` field — it causes errors.

**Important limitation:** `systemEvent` payload is wrapped by OpenClaw as "Handle this reminder internally. Do not relay it to the user unless explicitly requested." — causing the agent to NO_REPLY. **Workaround:** Prefix payload text with `[MUST-SPEAK]` to force the agent to reply out loud despite the wrapper. All wellbeing and music cron payloads must start with `[MUST-SPEAK]`.

### Priority: Skills > Knowledge > History

AGENTS.md enforces a strict priority: **SKILL.md instructions always override KNOWLEDGE.md and conversation history**. This is critical because the agent self-accumulates "learnings" in KNOWLEDGE.md via heartbeat, and these can contain incorrect rules that conflict with developer-maintained skills. If the agent notices a conflict, it must update KNOWLEDGE.md to match the skill, not the other way around.

This rule was added after discovering that the agent had written incorrect cron format rules into KNOWLEDGE.md ("NEVER use systemEvent") that overrode the correct Scheduling SKILL instructions.

When they leave (`presence.leave`), the agent silently cancels both cron jobs, appends a session summary to the daily log (`wellbeing/YYYY-MM-DD.md`), and updates the summary (`wellbeing.md`) if new patterns emerged.

### Cron-fired behavior

Each cron fires an agent turn. The agent:
1. Takes a camera snapshot (`GET http://127.0.0.1:5001/camera/snapshot`)
2. Checks presence (`GET http://127.0.0.1:5001/presence`)
3. If user is present and the reminder is warranted → one short sentence, varied phrasing
4. If user is absent, already has a drink, or looks fine → no response
5. Always emits `[HW:/emotion:{...}]` marker
6. If speaking, adds `[HW:/broadcast:{}]` — forces TTS + sends text to Telegram so the user sees it on their phone too

### Agent behavior

| Reminder | Emotion | Voice |
|---|---|---|
| Hydration cron | `caring` (0.5) | YES (remind water) or silent |
| Break cron | `caring` (0.6) | YES (remind stretch/walk) or silent |

The agent uses the camera snapshot to make a judgment call — it does NOT always speak. This prevents spamming the user when they seem fine.

### Music Suggestions (AI-Driven)

Music suggestions are **no longer** triggered by a hardcoded timer. Instead, the AI agent **self-schedules** music checks via OpenClaw cron jobs and **learns** the user's habits over time:

- **Self-scheduling:** On first `presence.enter` of the day, the AI creates a cron job (default: every 7 min / 420000ms, `sessionTarget: "main"`, `payload.kind: "systemEvent"`). It adjusts the interval based on user response patterns.
- **Data-driven decisions:** Before suggesting, the AI queries:
  - `GET /presence` — is user present?
  - `GET /camera/snapshot` — visual mood assessment
  - `GET /api/openclaw/mood-history` — presence patterns, past suggestion outcomes
  - `GET /audio/history` — listening history (genre preference, duration, satisfaction)
- **Learning loop:** The AI correlates suggestions with `music.play` events in mood history. Accepted suggestions reinforce timing/genre; rejected suggestions trigger schedule adjustments.
- **Personalization:** Over time, the AI learns when the user prefers music, what genres they enjoy, and how long they typically listen — adapting its suggestions accordingly.

See the Music skill (`resources/openclaw-skills/music/SKILL.md`) for full implementation details.

### Proactive care (piggyback on sensing events)

Beyond scheduled reminders, the agent is encouraged to **notice things** when receiving any event where the user is visible (presence.enter, motion.activity). Based on time of day, how long the user has been sitting, and what it sees, the agent may proactively mention meals, fatigue, or late nights — one short sentence, only when it feels natural. This is not mandatory but encouraged.

Examples: "Morning! Had breakfast?" on early `presence.enter`, "It's past noon — grab some lunch?" on `motion.activity` at 12:20, "It's almost 11 PM..." on late-night `motion.activity`.

### Broadcast marker (`[HW:/broadcast:{}]`)

A special HW marker that forces the agent's spoken text to also be sent to all Telegram channels. Used by wellbeing crons, music suggestions, and any cron-fired turn where the user should see the message on their phone. Also forces TTS for non-voice turns (e.g., cron-triggered agent turns that would otherwise be silent). Works like guard mode alerts.

### Per-user mood history

Mood history tracks the **user's emotional state** only — not system events or lamp emotions. Stored per-user at `/root/local/users/{name}/mood/YYYY-MM-DD.jsonl` (30-day retention). Mood is logged by the agent via the Mood skill when it detects emotional actions (camera) or infers mood from conversation.

```bash
# Write (agent calls this)
POST /api/mood/log  {"mood":"happy","source":"camera","trigger":"laughing"}

# Read
GET /api/openclaw/mood-history?user=gray&date=2026-04-09&last=100
```

Each entry: `{"ts":...,"hour":10,"mood":"happy","source":"camera","trigger":"laughing"}`

### Cross-channel identity

The agent links face recognition names to Telegram usernames by observing timing and context (e.g., "gray" is at the desk and "@GrayDev" messages on Telegram simultaneously). Confirmed mappings are stored in `USER.md` (for the enrolled person) or the user's folder notes. The agent asks for confirmation if unsure.

---

## Motion Activity Analysis (while present)

When the user is already present (PRESENT state), foreground motion triggers a `motion.activity` event instead of `motion`. Same cooldown (`MOTION_EVENT_COOLDOWN_S`, 3 min) — no separate timer. The system sends the detected action name(s) (no images — action names are sufficient for the agent to infer behavior).

### How it works

`MotionPerception` buffers snapshots and action names, flushing them periodically (`MOTION_FLUSH_S`). On flush it checks `PresenceService.state`:
- **PRESENT** → sends `motion.activity` with action names only (e.g. `'drinking', 'stretching'`). No images attached — saves tokens.
- **NOT PRESENT** (AWAY/IDLE) → sends `motion` with images (enter/leave detection needs visual confirmation)

Both share the same flush interval cooldown.

### Wellbeing cron reset (LLM-driven)

The agent infers from the **action name** (not images) whether to reset wellbeing crons:

1. **Read today's daily log** for context (how many times they drank, took breaks today)
2. **Infer from action name:**
   - User drinking something (water, beer, coffee, etc.) → reset hydration cron
   - User NOT sedentary (standing, stretching, walking, etc.) → reset break cron
   - Both apply → reset both
   - Sedentary (sitting, typing, etc.) → NO_REPLY
3. **Append to daily log:** `HH:MM — [action] (hydration reset / break reset / both reset)`
4. **Respond with caring observation** using context from log (e.g. "3rd glass today, nice!"). Observe, don't instruct. NEVER mention crons/timers/reminders.

### Agent behavior

| Event | Emotion | Voice |
|---|---|---|
| `motion.activity` | `curious` (0.4) | YES (caring observation with context) or NO_REPLY (sedentary) |

---

## Emotion Detection — User Emotion (Lightweight UC-M1)

Lumi detects the **user's** emotional state from `motion.activity` actions using the existing X3D action recognition model — no separate facial expression model needed. This is a lightweight proxy for UC-M1 (Facial Expression & Wellness Detection).

> **Not to be confused with Emotion Expression** (`emotion/SKILL.md`) — which controls Lumi's own emotional output (servo + LED + eyes). Emotion Detection is about sensing what the *user* feels; Emotion Expression is how *Lumi* shows its feelings.

### Detected emotional actions

The X3D model already classifies these emotional actions from the motion activity whitelist:

| Action | Inferred state | Agent emotion |
|---|---|---|
| `laughing` | Happy/amused | `laugh` (0.8) |
| `crying` | Sad/upset | `caring` (0.9) |
| `yawning` | Tired/fatigued | `sleepy` (0.6) |
| `singing` | Happy/relaxed | `happy` (0.7) |

### Always speak

Unlike regular `motion.activity` events (which may result in NO_REPLY for sedentary actions), emotional actions **always get a spoken response**. Silence is never appropriate when Lumi notices the user laughing, crying, yawning, or singing.

### Context-aware intensity

The default response is light (brief remark). Context escalates the intensity:

- **Time of day**: yawning after 22:00 → suggest winding down + dim light. Yawning before 10:00 → just a light remark.
- **Sitting duration**: yawning after 2+ hours sitting → suggest a break.
- **Repetition**: crying detected a second time in the session → gently offer to talk. Laughing 3+ times → comment on their good mood.
- **Cross-skill**: singing with no music playing → offer music via Music skill.

### Logging

- **Mood history** (agent logs): Agent calls `POST /api/mood/log` via Mood skill to record the user's emotional state (e.g. `{"mood":"happy","source":"camera","trigger":"laughing"}`).
- **Wellbeing daily log** (agent writes): Agent appends `HH:MM — [emotion] {action} detected (observation)` to the user's wellbeing daily log, alongside hydration/break entries.

### Limitations (vs full UC-M1)

- Only 4 discrete actions — no continuous emotion spectrum (surprise, anger, fear, disgust not detected)
- Requires visible body movement (X3D is video-based action recognition, not facial close-up)
- Cannot detect micro-expressions or subtle stress
- Full UC-M1 would require a dedicated FER (Facial Expression Recognition) ONNX model added to the face recognition pipeline

See `emotion-detection/SKILL.md` for the agent's full response rules.

---

## Snapshot Storage (two-tier)

Sensing events that include a camera frame (motion, presence.enter, presence.leave, music.mood) save snapshots in two locations. Note: `motion.activity` no longer sends images — only action names.

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

- **Pending event replay**: When the agent is busy, `presence.enter`, `presence.leave`, and `voice` events are queued and replayed when the agent becomes idle. The replay path (`drainPendingEvents` in `service.go`) applies the same nudge messages as the live handler (cron setup for presence.enter, cleanup for presence.leave, etc.).
- **Passive sensing events** (`[sensing:*]`) are dropped if the agent is already busy with another turn (except presence and voice events which are queued).
- **Voice events** always pass through — the user is explicitly speaking.
- The `[sensing:type]` prefix in the message is how the agent knows it's an ambient event, not a user message.
- Sensing events are exempt from the "call `/emotion thinking` first" rule — each type has its own defined first emotion.
- **Image pruning echo**: OpenClaw strips old image payloads from conversation history to save tokens. Smaller models (Haiku) may echo the pruning markers as `[image description removed]` in their response text. `SOUL.md` instructs the agent to never echo these markers.
