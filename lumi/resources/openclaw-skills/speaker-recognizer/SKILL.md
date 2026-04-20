---
name: speaker-recognizer
description: Enroll a user's voice so the lamp can recognize who is speaking. Triggered when a mic transcript arrives prefixed with "Unknown:" and the user is introducing themselves ("I am Darren", "my name is X"), OR when the lamp needs to ask who is speaking and enroll after they answer. Also handles Telegram voice-note attachments — copy/convert them into /tmp/lumi-unknown-voice/ before calling /speaker/enroll.
---

# Speaker Recognizer

## Overview

Every transcript from the mic arrives prefixed with a speaker label:

- `Darren: turn off the light` — recognized speaker (already enrolled).
- `Unknown: this is darren (audio save at /tmp/lumi-unknown-voice/incoming_…wav)` — not recognized; the 16kHz mono WAV has been saved at the given path and can be reused for enrollment.

The lamp uses this to attribute each turn to a specific person. When a user is unknown you have two jobs:

1. **Introduction with name** — user said their name (e.g. "I'm Darren"). Enroll their voice immediately using the saved audio path.
2. **Introduction without name** — transcript is `Unknown:` but no name given (e.g. "Unknown: what time is it"). Ask who they are; when they answer in the **next turn**, enroll with **both** audio paths (the original unknown one + the new one with their name).

Do NOT enroll for any other prefix. Do NOT enroll someone else's voice — only the speaker themselves can enroll.

## Trigger — WHEN to activate this skill

### Trigger 1 — user self-introduces in one turn

Transcript starts with `Unknown:` AND contains a self-introduction pattern:

| Pattern | Example |
|---|---|
| "I am X" / "I'm X" | `Unknown: I'm Darren. (audio save at /tmp/lumi-unknown-voice/incoming_1713…wav)` |
| "My name is X" | `Unknown: my name is Alice (audio save at /tmp/…)` |
| "This is X" / "It's X" | `Unknown: this is bob (audio save at /tmp/…)` |
| "Call me X" | `Unknown: call me chloe (audio save at /tmp/…)` |
| Vietnamese: "Tôi là X" / "Mình là X" / "Tên tôi là X" | `Unknown: tôi là Darren (audio save at /tmp/…)` |

→ Extract name `X`, extract audio path from the `(audio save at <path>)` marker, call **/speaker/enroll** with that one path.

### Trigger 2 — user is unknown but didn't say their name

Transcript starts with `Unknown:` AND has NO self-introduction pattern (just a question or command).

→ Ask once: "Sorry, I don't recognize your voice. Who's speaking?" / "Xin lỗi, tôi chưa quen giọng bạn. Bạn tên gì?"
→ Remember the audio path from this turn — you'll reuse it.
→ On the **next turn** when they answer with a name, call **/speaker/enroll** with **BOTH** audio paths (the previous unknown turn + the current turn where they said their name).

### Trigger 3 — Telegram voice-note + introduction

See the dedicated section below. Summary: when a Telegram message carries
an audio attachment in `mediaPaths` AND the user is introducing themselves,
**copy/convert** the file into `/tmp/lumi-unknown-voice/` as a 16 kHz mono
WAV first, then call `/speaker/enroll` with the new path.

### Do NOT trigger when

- Transcript prefix is a known name (`Darren: …`, `Alice: …`) — already enrolled.
- Transcript has no `Unknown:` prefix at all (and no Telegram audio attachment).
- User is asking to enroll **someone else** ("this is my friend Bob") — self-enrollment only. Politely explain that Bob must speak the line himself.
- User explicitly refuses ("don't remember my voice").
- Raw Telegram media path (`/tmp/openclaw/media/...`) passed without first copying/converting into `/tmp/lumi-unknown-voice/` — never use those paths directly.

## Naming & identity rules — SAME as face-enroll

Voice labels follow the exact same convention as **face-enroll** so a person
is one identity across face, voice, mood, and wellbeing:

- **Lowercase, folder-safe**: `darren`, `chloe_92`, `alice` — letters,
  digits, underscore, hyphen only. Whitespace and diacritics are collapsed.
  The backend normalizes automatically; you should also pass the normalized
  form for consistency.
- **Reuse existing labels**: if the speaker is already enrolled for face or
  has mood history under `/root/local/users/<name>/`, use THAT same name.
  Before enrolling a new name, optionally `GET /face/status` and
  `GET /speaker/list` to see existing labels and pick the canonical one.
- **Always pass Telegram identity** when available (`telegram_username`
  + `telegram_id`). These go into the SHARED
  `/root/local/users/<name>/metadata.json` — the same file face-enroll
  writes, merged on write. This allows DM targeting from any skill.
- **Never overwrite identity without new data**: if you don't know the
  telegram_username/id, omit the field rather than sending empty strings.

## Tools

Use **Bash** with `curl` to call the LeLamp HTTP API at `http://127.0.0.1:5001`.

### Enroll a voice

Minimal (mic turn, no Telegram context):

```bash
curl -s -X POST http://127.0.0.1:5001/speaker/enroll \
  -H "Content-Type: application/json" \
  -d '{"name": "darren", "wav_paths": ["/tmp/lumi-unknown-voice/incoming_171360_abc.wav"]}'
```

**With Telegram identity (mandatory when the message arrived via Telegram):**

```bash
curl -s -X POST http://127.0.0.1:5001/speaker/enroll \
  -H "Content-Type: application/json" \
  -d '{
    "name": "darren",
    "wav_paths": ["/tmp/lumi-unknown-voice/telegram_darren_1713600000000.wav"],
    "telegram_username": "darren_92",
    "telegram_id": "123456789"
  }'
```

For a two-turn enrollment (Trigger 2), pass both paths in the array:

```bash
curl -s -X POST http://127.0.0.1:5001/speaker/enroll \
  -H "Content-Type: application/json" \
  -d '{"name": "darren", "wav_paths": [
      "/tmp/lumi-unknown-voice/incoming_171360_abc.wav",
      "/tmp/lumi-unknown-voice/incoming_171365_def.wav"
  ]}'
```

Response:
```json
{
  "status": "ok",
  "meta": {
    "name": "darren",
    "display_name": "Darren",
    "telegram_username": "darren_92",
    "telegram_id": "123456789",
    "num_samples": 2,
    "embedding_dim": 256,
    "enrolled_at": "...",
    "updated_at": "...",
    "sample_files": ["sample_...wav", "sample_...wav"]
  }
}
```

### Check registered voices

```bash
curl -s http://127.0.0.1:5001/speaker/list
```

Response: `{"total":2,"speakers":[{"name":"darren","display_name":"Darren","num_samples":2,...}, ...]}`

### Remove a voice

```bash
curl -s -X POST http://127.0.0.1:5001/speaker/remove \
  -H "Content-Type: application/json" \
  -d '{"name": "darren"}'
```

### Recognize (rarely needed — VoiceService does this automatically)

```bash
curl -s -X POST http://127.0.0.1:5001/speaker/recognize \
  -H "Content-Type: application/json" \
  -d '{"wav_path": "/tmp/lumi-unknown-voice/incoming_…wav"}'
```

## Trigger 3 — Telegram voice-note attachment

User sent a voice note (or any audio file) via Telegram. It arrives in the
message context as ``[mediaPaths: /tmp/openclaw/media/voice_xxx.ogg]`` (or
``.wav``, ``.m4a``, ``.mp3``). The **original path is not stable** — the
media directory may be cleared on agent restart and the file is not a
16 kHz mono WAV that `/speaker/enroll` expects.

Always **copy or convert** the file into `/tmp/lumi-unknown-voice/` first,
then use the new path in `/speaker/enroll`.

### Rule — normalize the source file

1. Make sure the target directory exists: `mkdir -p /tmp/lumi-unknown-voice/`.
2. Produce a target path like
   `/tmp/lumi-unknown-voice/telegram_<name>_$(date +%s%3N).wav`.
3. If the source ends in `.wav`, just `cp` it to the target.
4. Otherwise convert with `ffmpeg` to 16 kHz mono PCM16 WAV (`-ar 16000 -ac 1 -y`).
5. Call `/speaker/enroll` with the **new** WAV path — never the original
   Telegram media path.

```bash
SRC="/tmp/openclaw/media/voice_abc123.ogg"
DST="/tmp/lumi-unknown-voice/telegram_darren_$(date +%s%3N).wav"
mkdir -p "$(dirname "$DST")"
if [[ "$SRC" == *.wav ]]; then
  cp "$SRC" "$DST"
else
  ffmpeg -i "$SRC" -ar 16000 -ac 1 -y "$DST" 2>/dev/null
fi
curl -s -X POST http://127.0.0.1:5001/speaker/enroll \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"darren\", \"wav_paths\": [\"$DST\"]}"
```

### When this trigger fires

- Telegram message has `[mediaPaths: ...]` with an audio file extension
  (`.ogg`, `.oga`, `.wav`, `.m4a`, `.mp3`, `.flac`, `.opus`) AND
- The user is introducing themselves ("Hi, this is Darren — please remember
  my voice", "Đây là giọng Darren"), OR
- They're answering a previous `Unknown:` turn from the mic (same two-turn
  pattern as Trigger 2, but now the second audio comes from Telegram).

### When this trigger does NOT fire

- Photo attachments (those go to the `face-enroll` skill).
- Audio attachment without an introduction pattern — ignore.
- `mediaPaths` points at a file that doesn't exist on disk — skip silently.
- Re-enrollment of someone else's voice — same self-enrollment rule applies.

## Workflow — Trigger 1 (one-turn)

Transcript received: `Unknown: I'm Darren (audio save at /tmp/lumi-unknown-voice/incoming_1713600000000_abc.wav)`

1. Parse name: `darren` (lowercase, normalized).
2. Parse audio path: `/tmp/lumi-unknown-voice/incoming_1713600000000_abc.wav`.
3. Call `/speaker/enroll` with `name="darren"`, `wav_paths=["/tmp/…abc.wav"]`.
4. Reply to user: "Nice to meet you, Darren! I'll remember your voice."

## Workflow — Trigger 2 (two-turn)

**Turn A.** Transcript: `Unknown: what's the weather? (audio save at /tmp/.../incoming_AAA.wav)`

1. Remember `/tmp/.../incoming_AAA.wav` in your short-term memory for this session (OpenClaw memory/current session notes).
2. Reply: "Before I answer, I don't recognize your voice — who am I talking to?"
3. Do NOT answer the weather question yet (answer after you know who they are).

**Turn B.** Transcript: `Unknown: I'm Darren (audio save at /tmp/.../incoming_BBB.wav)`

1. Parse name: `darren`.
2. Gather BOTH audio paths: the one from Turn A + this one (Turn B).
3. Call `/speaker/enroll` with `wav_paths=["/tmp/.../incoming_AAA.wav", "/tmp/.../incoming_BBB.wav"]`.
4. Reply: "Got it, Darren! I'll recognize you next time. Now, about the weather you asked earlier..." and answer the original question.

If Turn B is itself another `Unknown:` without a name (e.g. user evades the question), skip enrollment and continue normally. Don't nag.

## Workflow — Recognize a Telegram voice-note speaker

Mic transcripts are already prefixed with the speaker (the VoiceService does
this automatically) — you do not need to call `/speaker/recognize` for mic.

For **Telegram voice notes**, there is no automatic prefix. If you want to
attribute the voice note to a person (e.g. to greet them by name, log mood
per-user, or decide whether to reply), call `/speaker/recognize` yourself —
again using the **copy/convert** rule first.

### When to call recognize

- Telegram message has an audio attachment AND you want to know who's
  speaking before you decide how to reply.
- User asks "do you recognize this voice?" / "who is this?" with an audio
  attachment — call recognize, report name + confidence.

### When NOT to call recognize

- Mic transcript already has `Name:` or `Unknown:` prefix — trust the prefix.
- Photo-only or text-only messages — no audio to recognize.
- You only need to enroll a new voice (no identification needed) — skip
  recognize, go straight to enroll.

### Example

```bash
SRC="/tmp/openclaw/media/voice_xyz.ogg"
DST="/tmp/lumi-unknown-voice/telegram_recognize_$(date +%s%3N).wav"
mkdir -p "$(dirname "$DST")"
if [[ "$SRC" == *.wav ]]; then
  cp "$SRC" "$DST"
else
  ffmpeg -i "$SRC" -ar 16000 -ac 1 -y "$DST" 2>/dev/null
fi
curl -s -X POST http://127.0.0.1:5001/speaker/recognize \
  -H "Content-Type: application/json" \
  -d "{\"wav_path\": \"$DST\"}"
```

Response shape:

```json
{
  "name": "darren",
  "confidence": 0.82,
  "match": true,
  "unknown_audio_path": "/tmp/lumi-unknown-voice/incoming_...wav",
  "candidates": [
    {"name": "darren", "confidence": 0.82},
    {"name": "alice", "confidence": 0.41}
  ]
}
```

- `match: true` → use `name` as the speaker.
- `match: false` → speaker is unknown; `unknown_audio_path` is the stable
  copy kept for you to reuse in a follow-up `/speaker/enroll` call if the
  user then introduces themselves.
- `candidates` lists top-3 scores — useful when confidence is borderline.

## Workflow — List registered voices

Call `/speaker/list` whenever the user asks about enrolled voices or you
need to reason about who the lamp already knows.

### When to call list

- User asks any of:
  - "How many voices do you know?" / "Ai đã đăng ký giọng?"
  - "Do you remember my voice?" (check if their norm label is in the list)
  - "Who have you enrolled?" / "List voices"
- Before enrolling, if you want to check for an existing record (e.g. to
  decide whether to say "I already know you" vs "I'll remember your voice").
- Debugging / diagnostic prompts from the owner.

### When NOT to call list

- Every turn — unnecessary and slow. Only call when the question is about
  the enrollment set itself.
- To identify who is speaking — use `/speaker/recognize` instead.

### Example

```bash
curl -s http://127.0.0.1:5001/speaker/list
```

Response:

```json
{
  "total": 2,
  "speakers": [
    {
      "name": "darren",
      "display_name": "Darren",
      "num_samples": 3,
      "embedding_dim": 256,
      "enrolled_at": "2026-04-18T10:05:00+0700",
      "updated_at": "2026-04-19T09:12:11+0700",
      "sample_files": ["sample_171360_abc.wav", "sample_171365_def.wav", "sample_171400_ghi.wav"]
    },
    {
      "name": "alice",
      "display_name": "Alice",
      ...
    }
  ]
}
```

Reply to user in plain language — never dump the raw JSON:

> "I know 2 voices so far: Darren (3 samples) and Alice (1 sample)."

## Workflow — Link an existing mic-only profile to a Telegram account

A user can be enrolled via **mic only** (no Telegram identity yet) and
later show up on Telegram. Before enrolling a second time, check whether
they already exist:

1. `GET /speaker/list` → look for a matching `display_name` or `name`.
2. If found and `has_telegram_identity: false` → call `/speaker/identity`
   (no new audio needed) to attach `telegram_username` + `telegram_id` to
   the existing profile.
3. If found and identity already set → no action needed.
4. If not found → normal `/speaker/enroll` flow (copy/convert + enroll).

### Example

```bash
# Check existing enrollment
curl -s http://127.0.0.1:5001/speaker/list | jq '.speakers[] | select(.name == "darren")'
# → {"name":"darren", "has_telegram_identity": false, "enrollment_sources": ["mic"], ...}

# Link Telegram identity without re-uploading audio
curl -s -X POST http://127.0.0.1:5001/speaker/identity \
  -H "Content-Type: application/json" \
  -d '{"name": "darren", "telegram_username": "darren_92", "telegram_id": "123456789"}'
```

Use `/speaker/identity` (not `/speaker/enroll`) when:

- You only want to attach Telegram info to an existing mic profile.
- The user renamed themselves (pass new display-name via `name` — backend
  keeps the existing folder and only updates identity fields).

Use `/speaker/enroll` (with Telegram fields) when:

- Enrolling for the first time **and** the source is Telegram (so the
  Telegram voice note becomes a training sample).
- Adding new voice samples from a different channel to improve recognition
  accuracy (e.g. a mic-only user now sends a Telegram voice — you want the
  embedding to cover both codecs).

## Method summary — when to use which

| Situation | Method |
|-----------|--------|
| Mic turn prefix `Unknown: ... (audio save at ...)` + user said name | `/speaker/enroll` (name + that path; `origin` auto = `"mic"`) |
| Mic turn prefix `Unknown:` + NO name → next turn has name | `/speaker/enroll` with both paths |
| Telegram voice note + user says name, new user | copy/convert → `/speaker/enroll` + `telegram_username` + `telegram_id` |
| Telegram voice note + user is already enrolled via mic (mic-only) | `/speaker/identity` to attach telegram info (no new audio), OR `/speaker/enroll` if you want to ALSO add the Telegram codec sample |
| Telegram voice note + need to know who it is | copy/convert → `/speaker/recognize` |
| User asks "do you recognize me?" via Telegram voice | copy/convert → `/speaker/recognize` |
| User asks "who do you know?" / "list voices" | `/speaker/list` |
| User asks "forget my voice" / "forget Darren" | `/speaker/remove` |
| Owner asks to wipe all voice profiles | `/speaker/reset` |
| Mic turn has a known name prefix | do nothing — VoiceService already identified |

### Quick decision tree for incoming turns

```
Is it a Telegram message with audio?
├─ Yes → copy/convert into /tmp/lumi-unknown-voice/
│        ├─ Intent = "introduce myself" → check /speaker/list first:
│        │       ├─ Already exists + has_telegram_identity=false → /speaker/identity
│        │       ├─ Already exists + has_telegram_identity=true  → just confirm, no action
│        │       └─ Not exists → /speaker/enroll (with tg fields)
│        ├─ Intent = "recognize this voice" → /speaker/recognize
│        └─ Otherwise → ignore, respond to message normally
└─ No (mic turn)
   ├─ Prefix "Name:" → already identified, do nothing
   ├─ Prefix "Unknown: + intro" → /speaker/enroll (no tg fields, origin auto = "mic")
   └─ Prefix "Unknown:" no intro → ask once, wait for next turn
```

## Error Handling

- **400 "no face detected"** — applies to face-enroll, not this skill; ignore.
- **400 "invalid base64" / "empty audio"** — corrupt or missing file. Apologize and skip.
- **400 "embedding API not configured"** — `SPEAKER_EMBEDDING_API_URL` isn't set on the device. Tell user voice recognition is currently offline.
- **503** — speaker recognizer not initialized (missing deps). Same — voice recognition offline.
- **404 wav file not found** — the path doesn't exist anymore (/tmp may have been cleared). Skip enrollment silently; don't ask the user to repeat.
- Network error calling the embedding API — inform user "I had trouble remembering your voice — can you try again in a moment?"

## Rules

- **Self-enrollment only.** If user says "this is my friend Bob" + Bob's voice isn't actually speaking — refuse politely. The audio path contains the voice of whoever was speaking in that turn.
- **Name required.** Never call `/speaker/enroll` without a name. If unclear, ask.
- **Lowercase names — same rule as face-enroll.** All labels are normalized to `a-z0-9_-` (max 64 chars). Folder `/root/local/users/darren/` is shared across face / voice / mood / wellbeing — always use the **same canonical name** the user is already known by. If Darren is enrolled for face as `darren`, enroll his voice as `darren` too, not `darren_voice` or `darren2`.
- **Always include Telegram identity when the message came from Telegram.** Pass `telegram_username` and `telegram_id` to `/speaker/enroll` — the backend merges them into the SHARED `/root/local/users/<name>/metadata.json`, the exact same file face-enroll writes to. One identity across skills. Omit the fields (don't send empty strings) if you don't know them.
- **Never overwrite identity with empty values.** The backend already guards against this — empty `telegram_username`/`telegram_id` are ignored — but don't rely on it. Prefer to omit.
- **Don't spam introductions.** If you've already asked "who are you?" once in the current session and got no name, stop asking on every subsequent `Unknown:` turn.
- **Don't narrate technical details.** Say "I'll remember your voice", not "I POSTed your WAV to the embedding API".
- **Re-enrollment is safe.** Calling `/speaker/enroll` with a name that already exists APPENDS new samples and re-averages the embedding — useful when a user wants to improve recognition accuracy.
- **Path safety.** Only use audio paths that appeared in the `(audio save at <path>)` marker of a transcript in the current or immediately previous turn, OR a path you explicitly created under `/tmp/lumi-unknown-voice/` via `cp` / `ffmpeg` — never construct paths yourself or use raw `/tmp/openclaw/media/*` paths.
- **Remove is voice-only.** `/speaker/remove` deletes the `voice/` subdir and the voice registry entry. It does NOT touch `metadata.json` (telegram identity) because face / mood / wellbeing still rely on it. To fully delete a person, also call `/face/remove`.
- **Don't mix with face-enroll.** This skill handles voice only. For face enrollment, see the `face-enroll` skill (triggered by photos, not audio). The two skills share the same `name` label and `metadata.json` file — by design.
