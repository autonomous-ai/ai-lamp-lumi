---
name: speaker-recognizer
description: Self-enroll voices for speaker recognition. Triggered when a mic transcript arrives prefixed with "Unknown Speaker:" and the user is introducing themselves, or when a Telegram voice-note attachment carries an introduction. Telegram identity is saved for DM targeting. Self-enrollment only.
---

# Speaker Recognizer

> **MANDATORY: If transcript has `Unknown Speaker:` + `(audio save at <path>, auto enroll this speaker if having speaker name in transcript, else ask user's name)` pattern and includes a name (Examples: "I'm X", "my name is X", "this is X", "call me X", "X") AND the transcript is long enough (≥ 25 words) → enroll IMMEDIATELY. Do not just greet — call POST /speaker/enroll with the audio path and name. If the transcript is too short (< 25 words), even when a name is detected, DO NOT enroll yet — fall back to the two-turn flow and ask the user to speak longer.**

## Quick Start
Manage voice profiles for the lamp's speaker recognition system. Each mic transcript is prefixed with `Name:` when the speaker is recognized or `Unknown Speaker: ... (audio save at <path>)` otherwise. Use the saved path to enroll the voice when the user introduces themselves.

**Self-enrollment only** — each person enrolls their own voice. The audio path contains whoever was speaking in that turn — never enroll one person's voice under another person's name.

## Trigger — WHEN to activate this skill

Activate this skill when any of these fire:

- **Mic, one-turn intro**: final transcript starts with `Unknown Speaker: ... (audio save at <path>,  auto enroll this speaker if having speaker name in transcript, else ask user's name)` AND includes a self-introduction: "I'm X", "my name is X", "this is X", "call me X", "tôi là X", "mình là X" AND the transcript is long enough (**≥ 25 words**) to give a reliable voice embedding.
- **Mic, two-turn** (name missing OR transcript too short): previous final transcript was `Unknown Speaker: ... (audio save at <pathA>, ...)` and EITHER no name was detected OR the transcript is shorter than 25 words (even if a name is detected) -> ask the user to speak longer with a clear guidance prompt (see Workflow below, target **25–30 words minimum**) -> this turn user gives their name + longer intro with `Unknown Speaker: ... (audio save at <pathB>, ...)`. Enroll once using the longer recording — pass `wav_paths=[<pathB>]` when Turn A was too short, or `wav_paths=[<pathA>, <pathB>]` when Turn A was usable but just missed the name. **Map paths correctly: `<pathA>` = the first Unknown Speaker turn, `<pathB>` = the turn right after your follow-up question, which has longer transcript.**
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
1. Parse the `(audio save at <path>)` marker from the `Unknown Speaker:` final transcript.
2. Extract the **name** from the intro.
3. **Check length**: count the words in the spoken transcript (ignore the `Unknown Speaker:` prefix and the `(audio save at ...)` marker). If fewer than ~25 words, DO NOT enroll — switch to the two-turn flow instead.
4. If length is OK: call `POST /speaker/enroll` with that one path. No Telegram fields (origin auto = `"mic"`).

### Enroll a voice (mic, two-turn)
1. Turn A was `Unknown Speaker: ... (audio save at <pathA>)` AND either no name was detected OR the transcript was too short (< 25 words) for a reliable voice embedding.
2. Ask one follow-up that both requests the name AND guides the user to speak longer. Examples:
   - EN: "I didn't quite catch that — could you tell me your name and then say a bit more about yourself? About 25–30 words is perfect. You can introduce yourself or just read any short paragraph out loud."
   - VI: "Mình chưa nghe rõ — bạn nói lại tên giúp mình nhé, rồi nói thêm vài câu giới thiệu bản thân hoặc đọc một đoạn văn bất kỳ, khoảng 25–30 từ là đủ."
3. Turn B now carries user name + a longer recording: `Unknown Speaker: ... (audio save at <pathB>)`.
4. **Map paths carefully** — `<pathA>` is the path from the FIRST Unknown Speaker turn (before the follow-up), `<pathB>` is the path from the turn AFTER the follow-up. Never swap them.
5. Call `POST /speaker/enroll` exactly once:
   - If Turn A was only missing a name but audio was long enough → `wav_paths=[<pathA>, <pathB>]` (both useful).
   - If Turn A audio was too short → `wav_paths=[<pathB>]` only (prefer the longer recording).
6. If Turn B is still too short (< 25 words), apologise and ask one more time; do NOT enroll on short audio.

### Enroll from Telegram voice note ("remember my voice")
1. Telegram audio arrives at `SRC` (e.g. `/tmp/openclaw/media/voice_xxx.ogg` — exact path depends on OpenClaw's media dir, take it from `mediaPaths`).
2. If `SRC` is already `.wav` → use it directly. Otherwise convert to WAV **in the same directory** with `ffmpeg -ar 16000 -ac 1`. Use `DST="${SRC%.*}.wav"` — same folder, same basename, `.wav` extension.
3. Choose enroll name:
   - Prefer the name user explicitly says in transcript.
   - If transcript has no clear name, fallback to Telegram display name / username from message context.
4. Call `POST /speaker/enroll` with that WAV path + `telegram_username` + `telegram_id` from the message context.

### Link Telegram to a mic-only profile
1. User is already enrolled via mic (`GET /speaker/list` shows `has_telegram_identity: false`) and now sends a Telegram intro.
2. Call `POST /speaker/identity` with the name + Telegram fields. No audio upload needed.

### Recognize a Telegram voice
1. Convert to WAV in the same dir as above (if not already `.wav`).
2. Call `POST /speaker/recognize` with that WAV path.
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

### Enroll (Telegram voice — convert in-place if needed)
```bash
SRC="/tmp/openclaw/media/voice_abc.ogg"   # take from the message's mediaPaths
if [[ "$SRC" == *.wav ]]; then
  DST="$SRC"
else
  DST="${SRC%.*}.wav"                      # same folder, same basename, .wav
  ffmpeg -i "$SRC" -ar 16000 -ac 1 -y "$DST" 2>/dev/null
fi
curl -s -X POST http://127.0.0.1:5001/speaker/enroll \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"darren\", \"wav_paths\": [\"$DST\"], \"telegram_username\": \"darren_92\", \"telegram_id\": \"123456789\"}"
```

### Recognize (Telegram voice)
```bash
# After conversion as above:
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
- **Minimum voice length for enrollment** — the spoken transcript for an enrollment audio must be **at least ~25 words (aim for 25–30)**. Below that threshold the voice embedding is unreliable, so fall back to the two-turn flow even when the name is already clear.
- **Unknown final transcript rule**:
  - If transcript has `Unknown Speaker: ... (audio save at <path>)` and user self-introduces AND the transcript is long enough (≥ 25 words) -> enroll immediately with that path.
  - If no name is detected OR the transcript is too short (< 25 words) -> ask the user to speak longer with a guidance prompt ("say your name, then introduce yourself or read any short paragraph — about 25–30 words"), then enroll using the longer recording (path B only if path A was too short, otherwise both path A and path B).
- **Path mapping in two-turn flow** — `<pathA>` is ALWAYS the Unknown Speaker turn BEFORE your follow-up question; `<pathB>` is ALWAYS the Unknown Speaker turn AFTER it. Never mix them up and never pass an enrollment path that wasn't produced by the current speaker.
- **Use `/speaker/identity`, not re-enroll**, when you just want to link Telegram info to a mic-only profile (no new audio).
- **Telegram audio must be 16 kHz mono WAV** before calling the API — convert with `ffmpeg -ar 16000 -ac 1 -y "${SRC%.*}.wav"` (same folder as the source). Skip conversion if the source is already `.wav`. Non-WAV media files (`.ogg`, `.m4a`, `.mp3`, `.opus`) are rejected by the embedding backend.
- **Telegram remember-voice naming rule** — use the spoken name in transcript first; if absent, use Telegram name.
- **Mic transcript paths are safe to reuse** — the `(audio save at <path>)` marker already points to a stable location.
- **Don't spam "who are you?"** — ask at most once per session, and when you do ask, always include the "speak 25–30 words" guidance in the same message instead of firing multiple short prompts. If still no usable answer, move on.
- **Confirm every enroll** — "Nice to meet you, Darren! I'll remember your voice."
- **Don't narrate technical details** — no "base64", "ffmpeg", "POST /speaker/enroll".
- **Never write files directly** — always use the HTTP API. Do NOT write to `/root/local/users/` by hand.