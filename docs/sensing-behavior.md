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

### How it works (event-driven — no cron)

Wellbeing is **event-driven**. There are NO wellbeing cron jobs. On every `motion.activity`, the agent logs what happened and reads back recent history to decide whether to nudge.

**Per-user activity JSONL** at `/root/local/users/{user}/wellbeing/YYYY-MM-DD.jsonl` — one line per activity transition:

```jsonc
{"ts": 1776658657.23, "seq": 42, "hour": 11, "action": "sedentary", "notes": ""}
```

`action` values:

| Action | Written by | Purpose |
|---|---|---|
| `drink`, `break` | **LeLamp** (`motion.py` POSTs `/api/wellbeing/log` right before firing `motion.activity`) | Reset point for the corresponding nudge timer |
| `using computer`, `writing`, `texting`, `reading book`, `reading newspaper`, `drawing`, `playing controller` | **LeLamp** (`motion.py`, same path) | Timeline + nudge phrasing. **Not** a reset point. |
| `enter`, `leave` | Backend (sensing handler, on `presence.*` events) | Session boundary — Lumi dedups against the last presence row so consecutive enters without an intervening leave (stranger-ID churn) collapse to one. |
| `nudge_hydration`, `nudge_break` | Agent (after speaking a reminder) | Records when Lumi actually reminded — purely for timeline visibility. Only the agent knows when it actually spoke, so only the agent writes these. |

**Dedup lives in two places.**

*Activity dedup (5-min window).* `lelamp/service/sensing/perceptions/motion.py` keeps a `_last_sent_key = (current_user, frozenset(labels))` and a `_last_sent_ts`, where `labels` matches the outbound message (bucket names for drink/break, raw Kinetics labels for sedentary). Before emitting `motion.activity` **and before POSTing the rows to `/api/wellbeing/log`**, it drops the cycle if the key hasn't changed **and** the gap since the last send is still under `MOTION_DEDUP_WINDOW_S = 300` seconds (5 min). So `eating burger → eating cake` collapses to the same `break` key and is dropped, while `writing → drawing` flips the key (sedentary is raw) and passes through.

- User change (owner→owner, owner→unknown, unknown→owner) flips the key immediately → event passes through.
- Different strangers (e.g. `stranger_46` → `stranger_54`) collapse to `"unknown"` via `FaceRecognizer.current_user()`, so swapping strangers alone doesn't break dedup.
- After 5 min on the same state, the next event passes through even if nothing changed — this keeps the Lumi agent "woken up" periodically so the wellbeing threshold check still runs.

*Presence dedup (at-log).* `lumi/lib/wellbeing/wellbeing.go::LogForUser` scans the user's JSONL bottom-up for the most recent **presence** row (enter/leave, ignoring activity rows in between). `enter` while the last presence is already `enter` is dropped; `leave` with no matching open session is dropped. This is what keeps a single open session for `unknown` even when stranger_37 → stranger_38 → stranger_39 each fire their own raw `presence.enter` upstream.

**Retention:** 7 days on the Lumi side. A goroutine started by `wellbeing.Init()` sweeps files older than the cutoff daily.

### On `motion.activity` — what the agent does

By the time the agent sees the event, LeLamp has already logged the activity rows for it (see "Written by" in the table above). The agent's job is just: read the history, decide whether to nudge, and log the nudge if it fired.

1. **Read recent history** via `GET /api/openclaw/wellbeing-history?user={current_user}&last=50`.
2. **Compute deltas** from the log, using the most recent reset point for each:

   ```
   hydration_reset = max(last drink entry, last enter entry, last nudge_hydration entry)
   break_reset     = max(last break entry, last enter entry, last nudge_break entry)
   ```

   Three reset points: the actual activity (`drink` / `break`), a fresh arrival (`enter`), or the last nudge of that kind (`nudge_*`). The nudge reset is the key: after Lumi reminds, the delta drops back to 0 so the next reminder only fires after another full threshold window — no separate cooldown variable needed.
3. **Decide whether to nudge** (one nudge max per turn, hydration prioritised over break):
   - Hydration delta ≥ hydration threshold → hydration nudge.
   - Else break delta ≥ break threshold → break nudge.
   - Else → normal caring observation or `NO_REPLY`.
4. **After speaking a nudge**, log a `nudge_hydration` or `nudge_break` entry — this is what resets the delta for the next window (and makes the nudge visible on the user's timeline).
5. **Never guess** time-since from memory — always compute from the log.

### Thresholds

Hardcoded in `lumi/resources/openclaw-skills/wellbeing/SKILL.md`:

| Threshold | Test value | Production value |
|---|---|---|
| `HYDRATION_THRESHOLD_MIN` | **5** | 45 |
| `BREAK_THRESHOLD_MIN` | **7** | 30 |

> ⚠ **Release checklist:** before shipping, change both constants to the production values (45 / 30). Test values let us iterate within minutes instead of hours — hydration and break are intentionally offset (5 vs 7) so you can tell which path fired during testing.

**How re-nudge spam is prevented.** The `nudge_hydration` / `nudge_break` log entry the agent writes after speaking is also counted as a reset point for its threshold. After Lumi reminds, the delta drops back to 0 and the next reminder of that kind only fires after another full threshold window (45 min for hydration, 30 min for break in production).

```
10:45  hydration overdue → nudge 💧 + log nudge_hydration → hydration delta = 0
10:50  wake-up → delta = 5 min < 45 → SKIP
11:20  wake-up → delta = 35 min < 45 → SKIP
11:30  wake-up → delta = 45 min ≥ 45 → nudge 💧 again (user still hasn't drunk)
```

If the user drinks or takes a break before the next window, the regular `drink` / `break` entry resets the delta and nothing needs nudging.

### User attribution — `[context: current_user=X]`

The sensing handler injects a `[context: current_user=X]` tag into every `motion.activity` message. `X` is the **friend with the newest session_start** among friends still in the forget window (see `FaceRecognizer.current_user()`), or `"unknown"` when face sees **only** strangers (no friend is still present). Crucially: if a friend is still within their forget window, `current_user()` returns that friend even if the most recent raw `presence.enter` was for a stranger — stranger flicker does not kick a friend out of the session.

Sorting by `session_start` (the timestamp of the re-enter after the last leave) rather than `last_seen` makes the answer deterministic when two friends are continuously present (Chloe 18:00, An 18:30 → An wins because her session started later), instead of depending on dict iteration order.

The Wellbeing, Mood, and Music skills are all required to use this exact value for the `user` field in their API calls — never inferring from memory, KNOWLEDGE.md, chat history, or `senderLabel`.

### Presence markers written by backend

The sensing handler writes `enter` / `leave` entries to the same wellbeing JSONL — the agent is not involved:

- `presence.enter` (friend) → `{"action": "enter", "user": "<name>"}`
- `presence.enter` (stranger) → `{"action": "enter", "user": "unknown"}`
- `presence.leave` / `presence.away` → `{"action": "leave", "user": "<current_user_at_time_of_event>"}`

Presence events also reset the lelamp dedup key (since `current_user` changes), so a stranger leaving and a friend arriving will let the next activity event through immediately.

### Priority: Skills > Knowledge > History

AGENTS.md enforces a strict priority: **SKILL.md instructions always override KNOWLEDGE.md and conversation history**. This is critical because the agent self-accumulates "learnings" in KNOWLEDGE.md via heartbeat, and these can contain incorrect rules that conflict with developer-maintained skills. If the agent notices a conflict, it must update KNOWLEDGE.md to match the skill, not the other way around.

### On `presence.leave` / `presence.away`

Backend writes the `leave` marker to the log. Nothing else to do — there are no crons to cancel. The directive instructs the agent to stay quiet (`NO_REPLY`).

### Agent behavior

| Reminder | Emotion | Voice |
|---|---|---|
| Hydration cron | `caring` (0.5) | YES (remind water) or silent |
| Break cron | `caring` (0.6) | YES (remind stretch/walk) or silent |

The agent uses the camera snapshot to make a judgment call — it does NOT always speak. This prevents spamming the user when they seem fine.

### Music Suggestions (AI-Driven)

Music suggestions are **fully AI-driven** — no cron jobs, no backend triggers. The agent decides when to suggest based on two triggers:

- **Mood trigger:** After logging a suggestion-worthy mood (`sad`, `stressed`, `tired`, `excited`, `happy`, `bored`), the agent follows the Music skill to suggest music matching that mood.
- **Sedentary trigger:** When `motion.activity` carries a sedentary raw label (`using computer`, `writing`, `texting`, `reading book`, `reading newspaper`, `drawing`, `playing controller`), the agent suggests background music (lo-fi, ambient, instrumental).
- **Data-driven decisions:** Before suggesting, the agent queries:
  - `GET /audio/status` — is music already playing?
  - `GET /api/openclaw/music-suggestion-history` — the last entry is the reset point; fire only when `minutes_since_last_suggestion >= SUGGESTION_INTERVAL_MIN` (7 min test / 30 min prod)
  - `GET /audio/history?person={name}` — per-user listening history (genre preference, duration, satisfaction)
- **Learning loop:** Accepted suggestions reinforce genre/timing; rejected suggestions trigger approach adjustments. All logged via `/api/music-suggestion/log`.

See the Music skill (`resources/openclaw-skills/music/SKILL.md`) for full implementation details.

### Proactive care (piggyback on sensing events)

Beyond scheduled reminders, the agent is encouraged to **notice things** when receiving any event where the user is visible (presence.enter, motion.activity). Based on time of day, how long the user has been sitting, and what it sees, the agent may proactively mention meals, fatigue, or late nights — one short sentence, only when it feels natural. This is not mandatory but encouraged.

Examples: "Morning! Had breakfast?" on early `presence.enter`, "It's past noon — grab some lunch?" on `motion.activity` at 12:20, "It's almost 11 PM..." on late-night `motion.activity`.

### Speak and broadcast markers

Two control markers on channel-origin turns:

| Marker | Effect | When to use |
|---|---|---|
| `[HW:/speak:{}]` | Forces TTS on the speaker. No Telegram side-effect. | Proactive crons (wellbeing, music) running inside a Telegram/channel session so the reminder is also heard aloud. Usually combined with `[HW:/dm:{"telegram_id":"..."}]` for a targeted DM. |
| `[HW:/broadcast:{}]` | Forces TTS **and** fans out the reply text to every connected Telegram chat. | Guard mode alerts only. Never use in wellbeing/music — it will notify every chat, not just the person being reminded. |

By default, channel-origin turns (Telegram, webchat) suppress speaker TTS because the reply is routed as a channel message. `/speak` overrides that suppression without the fan-out side-effect.

**Cron-fire turns auto-force TTS.** When OpenClaw emits an `event:"cron"` with `action:"started"`, Lumi caches the `sessionKey` and the next `lifecycle_start` on that session within 10 s is marked as a cron fire — `isChannelRun` is overridden to `false` so the lamp speaker fires without requiring `[HW:/speak]` in the reply. The marker is still useful as a defense-in-depth fallback if the cron event is dropped (`dropIfSlow: true` on the OpenClaw side).

### Per-user mood history

Mood history tracks the **user's emotional state** only — not system events or lamp emotions. Stored per-user at `/root/local/users/{name}/mood/YYYY-MM-DD.jsonl` (7-day retention). Mood is logged by the agent via the Mood skill when it detects emotional actions (camera) or infers mood from conversation.

#### Mood sources

| Source | How it works |
|---|---|
| **Camera** (`source: "camera"`) | `motion.activity` detects emotional action (laughing, crying, yawning, singing) → Emotion Detection skill triggers → agent logs mood |
| **Conversation** (`source: "conversation"`) | Agent detects mood two ways: (1) **single message** — explicit ("I'm tired") or implied ("work is killing me" → stressed); (2) **conversation flow** — after chatting for a while, read the overall vibe (tone shifts, short/curt replies, repeated topics, rising/fading energy). Agent trusts its gut and infers boldly: a small hint is enough, better to log a maybe-mood than miss a real one. Works across all channels (Telegram, voice, web). |

#### Voice mood nudge

Voice events (`voice_command`, `voice`) include a `[MANDATORY: Follow Mood skill — log mood now.]` nudge in the message sent to the agent, plus `[Current user: {name}]` when face recognition knows who is present.

#### Storage format

JSONL (one JSON object per line) — chosen over JSON array for:
- **Append**: O(1) — just write a new line (no read-parse-rewrite)
- **Crash-safe**: worst case loses 1 line (array can corrupt entire file)
- **Read last N**: `Query()` reads all lines then slices — fast enough for daily files (tens of entries)

Each row carries a `kind` field — either a raw `signal` from one source or a
`decision` synthesized by the agent from the recent signals + previous decision.
The store never fuses anything; the Mood skill is responsible for writing both
rows on every detection.

```bash
# Write — raw signal (agent calls this on every camera/voice/telegram cue)
POST /api/mood/log  {"kind":"signal","mood":"happy","source":"camera","trigger":"laughing"}

# Write — synthesized decision (agent calls this right after, after reading recent history)
POST /api/mood/log  {"kind":"decision","mood":"happy","based_on":"3 signals last 20min","reasoning":"laughing reinforces previous happy decision"}

# Read — all kinds for a day (agent uses this to re-analyze)
GET /api/openclaw/mood-history?user=gray&date=2026-04-09&last=100

# Read — latest decision only (downstream skills use this for "current mood")
GET /api/openclaw/mood-history?user=gray&kind=decision&last=1
```

Each row: `{"ts":...,"seq":1,"hour":10,"kind":"signal","mood":"happy","source":"camera","trigger":"laughing"}` for signals,
or `{"ts":...,"seq":2,"hour":10,"kind":"decision","mood":"happy","source":"agent","based_on":"...","reasoning":"..."}` for decisions.

### Cross-channel identity

The agent links face recognition names to Telegram usernames by observing timing and context (e.g., "gray" is at the desk and "@GrayDev" messages on Telegram simultaneously). Confirmed mappings are stored in `USER.md` (for the enrolled person) or the user's folder notes. The agent asks for confirmation if unsure.

---

## Motion Activity Analysis (while present)

When the user is already present (PRESENT state), foreground motion triggers a `motion.activity` event instead of `motion`. Same cooldown (`MOTION_EVENT_COOLDOWN_S`, 3 min) — no separate timer. The system sends the detected action name(s) (no images — action names are sufficient for the agent to infer behavior).

### How it works

`MotionPerception` buffers snapshots and action names, flushing them periodically (`MOTION_FLUSH_S`). On flush it checks `PresenceService.state`:
- **PRESENT** → sends a single `motion.activity` event. Message format:
  - `Activity detected: <labels>.` — LeLamp already categorises: physical actions collapse to the bucket name (`drink`, `break`), sedentary activities keep the raw Kinetics label (`using computer`, `writing`, `texting`, `reading book`, `reading newspaper`, `drawing`, `playing controller`). The agent logs each label verbatim — no mapping required at the agent level.
  - Emotional X3D actions (`laughing`, `crying`, `yawning`, `singing`) are **intentionally dropped** here. A dedicated `motion.emotional` event type will be added later; until then emotional detections are silently ignored. `motion.activity` stays purely physical.
  - No images attached — saves tokens. Friend recognition is **not** required.
- **Otherwise** → event is **skipped** (logged, not sent). Lumi only expects `motion.activity` — plain `motion` from X3D/pose has no handler and wastes agent tokens.

Example messages:
```
Activity detected: drink, using computer.
Activity detected: break.
Activity detected: writing, reading book.
```

### Wellbeing nudge flow (event-driven)

The agent reads the `Activity detected:` line, splits on comma, and POSTs each label verbatim as the `action` field — LeLamp already categorised, so there is no bucket mapping in the agent.

1. **Log** each label via `POST /api/wellbeing/log` with `{action, notes:"", user}` — one entry per label. Backend-side no-op; LeLamp already deduped on the outbound label set.
2. **Read history** via `GET /api/openclaw/wellbeing-history?user={name}&last=50`.
3. **Compute deltas** against the latest reset point for each kind (see Wellbeing SKILL Step 3).
4. **Decide nudge** per Wellbeing SKILL Step 4 — at most one hydration or break nudge per turn.
5. **Respond**: a single short caring sentence if there's a nudge / suggestion, otherwise `NO_REPLY`.

### Agent behavior

| Event | Emotion | Voice |
|---|---|---|
| `motion.activity` | `curious` (0.4) | YES (caring observation with context) or NO_REPLY (sedentary) |

---

## Emotion Detection — User Emotion (UC-M1) ✅

Lumi detects the **user's** emotional state via two channels:

1. **Facial expression** (primary) — `emotion.detected` event from `lelamp/service/sensing/perceptions/emotion.py`. Uses a dedicated emotion classifier running on self-hosted dlbackend via WebSocket. Detects 7 emotions: Angry, Disgust, Fear, Happy, Sad, Surprise, Neutral. Configurable confidence threshold (`EMOTION_CONFIDENCE_THRESHOLD`).
2. **Body action** (secondary) — emotional X3D actions from action recognition are **intentionally dropped** from `motion.activity` (which is purely physical: sedentary/drink/break). A dedicated `motion.emotional` event type is planned for these.

> **Not to be confused with Emotion Expression** (`emotion/SKILL.md`) — which controls Lumi's own emotional output (servo + LED + eyes). Emotion Detection is about sensing what the *user* feels; Emotion Expression is how *Lumi* shows its feelings.

### `emotion.detected` event

Fired by LeLamp when the dlbackend emotion classifier detects a facial expression above the confidence threshold. Message format: `Emotion detected: Happy` (or Sad, Angry, etc.).

The sensing handler (`handler.go`) routes `emotion.detected` events to the agent. When the agent is busy, these events are queued and replayed when idle.

### Agent behavior

The `user-emotion-detection/SKILL.md` handles `emotion.detected` events:

1. Maps facial emotion → mood signal (e.g. Happy → happy, Sad → sad, Angry → frustrated)
2. Logs a `signal` row via `POST /api/mood/log`
3. **Silent by default** — no spoken reply unless warranted by normal sensing reply rules

### Mood pipeline

- **Mood history** (agent logs): On every signal the Mood skill writes a raw `signal` row, then reads recent history and writes a synthesized `decision` row (e.g. `{"kind":"decision","mood":"happy","based_on":"...","reasoning":"..."}`).
- Mood decisions trigger downstream skills: `music-suggestion` (proactive music), `wellbeing` (break/hydration nudges).

See `user-emotion-detection/SKILL.md` for the agent's full response rules.

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
- **Voice events** always pass through — the user is explicitly speaking. Voice messages include a mood scan nudge (`[MANDATORY: Follow Mood skill — log mood now.]`) so the agent remembers to detect mood from the conversation flow.
- The `[sensing:type]` prefix in the message is how the agent knows it's an ambient event, not a user message.
- Sensing events are exempt from the "call `/emotion thinking` first" rule — each type has its own defined first emotion.
- **Image pruning echo**: OpenClaw strips old image payloads from conversation history to save tokens. Smaller models (Haiku) may echo the pruning markers as `[image description removed]` in their response text. `SOUL.md` instructs the agent to never echo these markers.
