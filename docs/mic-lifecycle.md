# Mic Lifecycle — Mute/Unmute

Mic mute for privacy — meetings, calls, or just don't want Lumi listening.

## Current State

- Voice pipeline (`VoiceService`) runs always-on: mic → VAD → wake word → STT → OpenClaw
- Sound perception (`SoundPerception`) in sensing loop: mic → RMS → sound events
- Wake word detection runs inside VoiceService
- No mute/unmute API currently
- `POST /voice/stop` tears down entire pipeline (too aggressive)
- GPIO17 button currently stops TTS + music only

## Design: Fully Deaf When Muted

When muted, mic is **completely off** — no STT, no wake word, no sound perception. Fully deaf. Saves CPU, guarantees privacy.

### Mute: Voice command (one-way in)

User says "đừng nghe" / "stop listening" / "I'm in a meeting" → STT processes this last command → agent calls `[HW:/voice/mute:{}]` → TTS says "OK, I'll stop listening. Press the button when you need me." → mic off.

This is the **last thing Lumi says** until button press.

### Unmute: Physical button (one-way out)

GPIO17 button press → mic back on. Simple, reliable, no ambiguity.

Button behavior changes based on state:
- **Mic ON + TTS speaking** → click = stop TTS (current behavior)
- **Mic ON + TTS not speaking** → click = stop music if playing
- **Mic OFF (muted)** → click = unmute mic

```
User: "đừng nghe" ──→ [HW:/voice/mute:{}] ──→ mic OFF (deaf)
                                                    │
                                          GPIO17 click ──→ mic ON
```

### Additional unmute triggers

- **Web monitor toggle** — manual enable from UI
- **Telegram command** — remote "unmute" / "start listening"
- **Timer** — "mute for 1 hour" → auto unmute (optional, agent can set cron)

## What Happens When Muted

| Component | State | Why |
|-----------|-------|-----|
| STT | **OFF** | Privacy — no transcription |
| Wake word | **OFF** | Fully deaf — button is the only way back |
| Sound perception | **OFF** | No sound events |
| TTS | **ON** | Lumi can still speak (Telegram, cron triggers) |
| Camera/sensing | **Unaffected** | Separate from mic |
| Music | **ON** | Can still play/stop via Telegram or web |

## Interaction with Camera Lifecycle

| Camera | Mic | Use Case |
|--------|-----|----------|
| ON | ON | Normal — full sensing |
| ON | OFF | Meeting mode — sees but doesn't listen |
| OFF | ON | Visual privacy — hears but doesn't see |
| OFF | OFF | Full privacy — only GPIO17 button wakes |

## Auto-Mute Triggers (optional, same pattern as camera)

- **Scene focus/movie** → auto-mute (user focused, don't interrupt)
- **Scene night/sleepy** → auto-mute (sleeping)
- **Scene energize/relax** → auto-unmute

Manual override respected — if user explicitly muted via voice command, auto triggers skip (same as camera `_manual_override`).

## Implementation Plan

### LeLamp (Python)

1. **`server.py`**: Add endpoints:
   - `POST /voice/mute` — stop VoiceService, stop sound perception, set `_mic_muted = True`
   - `POST /voice/unmute` — restart VoiceService, restart sound perception, clear flag
   - `GET /voice/status` — include `muted` field

2. **GPIO17 button handler** (`_on_stop_button`): Add mic mute check:
   ```python
   if _mic_muted:
       unmute_mic()  # restart voice pipeline
       tts_service.speak("I'm listening!")  # confirm to user
   elif tts_service and tts_service.speaking:
       stop_tts()
   else:
       audio_stop()
   ```
   TTS confirmation is essential — user needs audible feedback that mic is back on. Without it, user doesn't know if button press worked.

3. **Scene/emotion integration**: `_auto_mic_mute()` / `_auto_mic_unmute()` with `_mic_manual_override` flag (same pattern as camera).

### OpenClaw Skills

4. **Voice skill or camera skill**: Add mute/unmute HW markers:
   - "đừng nghe" / "stop listening" / "mute mic" → `[HW:/voice/mute:{}]`
   - Unmute handled by button, not voice (Lumi is deaf)

### Web Monitor

5. **Voice status section**: Mute/Unmute toggle button + muted state indicator.

### Lumi (Go)

6. **HW marker dispatch**: `[HW:/voice/mute:{}]` and `[HW:/voice/unmute:{}]` — already handled by generic parser.

## Edge Cases

- **Muted + Telegram message**: Works — Telegram doesn't use mic. Agent responds normally.
- **Muted + TTS triggered**: TTS plays — speaker is output, independent of mic.
- **Muted + presence.enter** (camera on): Camera fires presence event, agent responds via TTS. User hears Lumi but Lumi can't hear back. Acceptable — user can click button if they want to talk.
- **Muted + timer unmute**: Agent sets cron "unmute in 1h" before muting → cron fires → `POST /voice/unmute` → mic back on.
- **Double mute**: `POST /voice/mute` when already muted → no-op, return `already_muted`.
- **Button press during TTS + muted**: Unlikely (how did TTS start if muted? → Telegram trigger). If happens: unmute takes priority over stop-TTS.
