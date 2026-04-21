---
name: speaker-recognizer
description: Self-enroll voices for speaker recognition. Triggered when a mic transcript arrives prefixed with "Unknown:" and the user is introducing themselves, or when a Telegram voice-note attachment carries an introduction. Telegram identity is saved for DM targeting. Self-enrollment only.
---

# Speaker Recognizer

## Quick Start
Manage voice profiles for the lamp's speaker recognition system. Each mic transcript is prefixed with `Name:` when the speaker is recognized or `Unknown: ... (audio save at <path>)` otherwise. Use the saved path to enroll the voice when the user introduces themselves.

**Self-enrollment only** — each person enrolls their own voice. The audio path contains whoever was speaking in that turn — never enroll one person's voice under another person's name.

## Trigger — WHEN to activate this skill

Activate this skill when any of these fire:

- **Mic, one-turn intro**: transcript starts with `Unknown: ... (audio save at <path>)` AND includes a self-introduction: "I'm X", "my name is X", "this is X", "call me X", "tôi là X", "mình là X".
- **Mic, two-turn**: previous turn was `Unknown:` with no name → ask "Who's speaking?" → this turn the user gives their name. Enroll with BOTH audio paths.
- **Telegram voice note + intro**: message carries `[mediaPaths: .../xxx.ogg|.wav|.m4a|.mp3|.opus]` AND the user is introducing themselves.
- **User asks about registered voices**: "who do you know?" / "list voices" / "do you remember my voice?".
- **User asks to forget their voice**: "forget my voice" / "remove Darren".
- **Telegram voice note + "who is this?"**: user wants identification of an audio.

Do NOT activate when:
- Transcript prefix is a known `Name:` (already identified by VoiceService — no action needed).
- User tries to enroll someone else ("this is my friend Bob") — refuse politely.
- `mediaPaths` points at a photo — that's the `face-enroll` skill.

## Workflow

### Enroll a voice (mic, one-turn)
1. Parse the `(audio save at <path>)` marker from the `Unknown:` transcript.
2. Extract the **name** from the intro. If unclear, ask.
3. Call `POST /speaker/enroll` with that one path. No Telegram fields (origin auto = `"mic"`).

### Enroll a voice (mic, two-turn)
1. Turn A was `Unknown: <question> (audio save at <pathA>)` → remember `<pathA>`, ask "Who's speaking?".
2. Turn B is `Unknown: I'm Darren (audio save at <pathB>)` → call `POST /speaker/enroll` with `wav_paths=[<pathA>, <pathB>]`.

### Enroll from Telegram voice note
1. Telegram audio arrives at `SRC=/tmp/openclaw/media/voice_xxx.ogg` (or `.wav`, `.m4a`, etc.).
2. **Copy/convert** into `/tmp/lumi-unknown-voice/` as 16 kHz mono WAV — never pass the raw `/tmp/openclaw/media/...` path to the API.
3. Call `POST /speaker/enroll` with the new WAV path + `telegram_username` + `telegram_id` from the message context.

### Link Telegram to a mic-only profile
1. User is already enrolled via mic (`GET /speaker/list` shows `has_telegram_identity: false`) and now sends a Telegram intro.
2. Call `POST /speaker/identity` with the name + Telegram fields. No audio upload needed.

### Recognize a Telegram voice
1. Copy/convert the attachment as above.
2. Call `POST /speaker/recognize` with the new WAV path.
3. `match: true` → use `name`; `match: false` → treat as unknown, `unknown_audio_path` is kept for a follow-up enroll.

### List / remove / reset
- "Who do you know?" → `GET /speaker/list`. Reply with display names, not raw JSON.
- "Forget my voice" → `POST /speaker/remove` with the name.
- Owner says "wipe all voice profiles" → `POST /speaker/reset`.

## Tools

**Bash** with `curl` for HTTP calls to `http://127.0.0.1:5001`.

### Enroll (mic, one path)
```bash
curl -s -X POST http://127.0.0.1:5001/speaker/enroll \
  -H "Content-Type: application/json" \
  -d '{"name": "darren", "wav_paths": ["/tmp/lumi-unknown-voice/incoming_171_abc.wav"]}'
```

### Enroll (mic, two paths — Turn A + Turn B)
```bash
curl -s -X POST http://127.0.0.1:5001/speaker/enroll \
  -H "Content-Type: application/json" \
  -d '{"name": "darren", "wav_paths": ["/tmp/lumi-unknown-voice/incoming_A.wav", "/tmp/lumi-unknown-voice/incoming_B.wav"]}'
```

### Enroll (Telegram voice — copy/convert first)
```bash
SRC="/tmp/openclaw/media/voice_abc.ogg"
DST="/tmp/lumi-unknown-voice/telegram_darren_$(date +%s%3N).wav"
mkdir -p "$(dirname "$DST")"
if [[ "$SRC" == *.wav ]]; then
  cp "$SRC" "$DST"
else
  ffmpeg -i "$SRC" -ar 16000 -ac 1 -y "$DST" 2>/dev/null
fi
curl -s -X POST http://127.0.0.1:5001/speaker/enroll \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"darren\", \"wav_paths\": [\"$DST\"], \"telegram_username\": \"darren_92\", \"telegram_id\": \"123456789\"}"
```

### Recognize (Telegram voice)
```bash
# After copy/convert as above:
curl -s -X POST http://127.0.0.1:5001/speaker/recognize \
  -H "Content-Type: application/json" \
  -d "{\"wav_path\": \"$DST\"}"
```

Response includes `name`, `confidence`, `match`, `display_name`, `telegram_username`, `telegram_id`, `unknown_audio_path`, `candidates` (top-3).

### Link Telegram identity (no audio upload)
```bash
curl -s -X POST http://127.0.0.1:5001/speaker/identity \
  -H "Content-Type: application/json" \
  -d '{"name": "darren", "telegram_username": "darren_92", "telegram_id": "123456789"}'
```

### List registered voices
```bash
curl -s http://127.0.0.1:5001/speaker/list
```

### Remove one voice
```bash
curl -s -X POST http://127.0.0.1:5001/speaker/remove \
  -H "Content-Type: application/json" \
  -d '{"name": "darren"}'
```

### Reset all voices (owner only)
```bash
curl -s -X POST http://127.0.0.1:5001/speaker/reset
```

## Error Handling
- 400 `wav file not found` — the path doesn't exist (media dir cleared). Skip silently.
- 400 `invalid base64` / `empty audio` / `cannot decode WAV` — corrupt file. Apologize and skip.
- 400 `no audio chunks extracted` — audio too short / silent. Ask user to speak longer.
- 400 `embedding API unreachable` — dlbackend down. Tell user "voice recognition is offline".
- 404 on `/speaker/identity` — user has no voice profile yet. Enroll first.
- 404 on `/speaker/remove` — no voice profile under that name. Tell the user "I don't have a voice on file for <name>".
- 503 — speaker recognizer not initialized (missing deps). Voice recognition offline.

## Rules
- **Self-enrollment only** — NEVER enroll someone else's voice. If "this is my friend Bob", tell them Bob must speak himself.
- **Lowercase normalized names** — use the same `name` as `face-enroll` for the same person (folder `/root/local/users/<name>/` is shared across skills).
- **Always include Telegram identity when the message came from Telegram** — pass `telegram_username` + `telegram_id`. Omit (don't send empty strings) when unknown.
- **Use `/speaker/identity`, not re-enroll**, when you just want to link Telegram info to a mic-only profile (no new audio).
- **Telegram audio must be copied/converted into `/tmp/lumi-unknown-voice/`** first — never pass raw `/tmp/openclaw/media/...` paths.
- **Mic transcript paths are safe to reuse** — the `(audio save at <path>)` marker already points to a stable location.
- **Don't spam "who are you?"** — ask once per session; if no name, move on.
- **Confirm every enroll** — "Nice to meet you, Darren! I'll remember your voice."
- **Don't narrate technical details** — no "base64", "ffmpeg", "POST /speaker/enroll".
- **Never write files directly** — always use the HTTP API. Do NOT write to `/root/local/users/` by hand.