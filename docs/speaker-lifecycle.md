# Speaker Lifecycle — TTS & Music Output Control

Speaker (audio output) control — mute output khi không muốn Lumi phát âm thanh, hoặc trong meeting/call.

## Current State

- TTS plays through speaker via `tts_service.speak()` — auto-spoken on every agent reply
- Music plays through speaker via `music_service` (ffmpeg → ALSA)
- GPIO17 button stops TTS + music (immediate)
- Volume control via `POST /audio/volume` (amixer)
- No speaker mute/unmute concept — chỉ stop individual playback
- Backchannel ("Uhm", "Ok") plays qua TTS during STT sessions

## Khác biệt với Mic Lifecycle

| | Mic | Speaker |
|---|---|---|
| Mute meaning | Stop listening (STT off) | Stop all audio output (TTS + music + backchannel) |
| Privacy concern | High — người ngoài nghe thấy nội dung | Low — chỉ phiền, không privacy issue |
| Wake up mechanism | Button (vì deaf) | Voice command vẫn hoạt động (mic vẫn on) |
| Auto-trigger | Scene focus/meeting | Scene focus/meeting, hoặc khi mic mute |

## Bài toán

User đang meeting/call, Lumi không nên:
- Nói TTS (agent reply, greeting, reconnect announce)
- Chơi nhạc (proactive suggestion, cron)
- Backchannel sounds ("Uhm", "Ok")
- System sounds (beep, tone)

Nhưng Lumi vẫn nên:
- Nhận lệnh qua Telegram (silent — chỉ text reply, không TTS)
- Process sensing events (camera, presence — nhưng không nói ra)
- LED/servo vẫn hoạt động

## Design: Speaker Mute

### Cách 1: Volume 0
- Set `amixer` volume 0 → tất cả audio silent
- Simple, hardware-level
- Nhưng: restore volume về bao nhiêu? User set custom volume trước mute → phải remember

### Cách 2: Software flag `_speaker_muted`
- TTS service check flag trước khi play → skip
- Music service check flag → skip hoặc pause
- Backchannel check flag → skip
- Không đụng hardware volume
- Pro: clean, no volume state to remember
- Con: mỗi output component phải check flag

### Cách 3: Kết hợp mic mute
- Khi mic mute → speaker cũng nên mute (meeting mode)
- Khi mic unmute → speaker unmute
- Tách riêng speaker mute cho case: muốn nghe nhạc nhưng không muốn TTS

### Recommendation: Cách 2 + tùy chọn kết hợp mic

`_speaker_muted` flag, independent từ mic. Nhưng khi user nói "đang họp" → mute cả mic + speaker cùng lúc (meeting mode).

## Triggers

### Mute speaker

1. **Voice command**: "Lumi, im đi" / "be quiet" / "silent mode" / "đang họp"
   - "đang họp" = mute cả mic + speaker (meeting mode)
   - "im đi" = mute speaker only, mic vẫn nghe
2. **Telegram command**: "mute speaker" / "silent"
3. **Web monitor toggle**
4. **Scene**: focus, movie → auto-mute speaker (user tập trung)
5. **Khi mic mute**: option auto-mute speaker theo

### Unmute speaker

1. **Voice command**: "Lumi, nói đi" / "unmute" / "you can talk"
   - Mic vẫn on nên voice command hoạt động
2. **GPIO17 button**: nếu speaker muted → unmute speaker
3. **Telegram/web toggle**
4. **Scene change**: energize, relax → auto-unmute

## What Happens When Speaker Muted

| Component | State | Behavior |
|-----------|-------|----------|
| TTS | **Suppressed** | `speak()` returns immediately, text not played |
| Music | **Paused/blocked** | `play()` skipped hoặc paused |
| Backchannel | **Suppressed** | No "Uhm"/"Ok" sounds |
| System TTS ("Brain reconnected") | **Suppressed** | Silent |
| Agent reply | **Text only** | Reply vẫn gửi qua Telegram/web, chỉ không TTS |
| LED/servo | **Unaffected** | Emotion animations vẫn chạy |
| Volume | **Unchanged** | Hardware volume giữ nguyên |

## Meeting Mode (mic + speaker mute)

Khi user nói "đang họp" / "I'm in a meeting":
1. Agent gọi `[HW:/voice/mute:{}]` (mic off)
2. Agent gọi `[HW:/speaker/mute:{}]` (speaker off)
3. TTS confirm trước khi mute: "OK, meeting mode. Press button when done."
4. Lumi hoàn toàn silent — không nghe, không nói
5. LED có thể dim hoặc show meeting indicator
6. Unmute: GPIO17 button → unmute cả mic + speaker

## GPIO17 Button

No change needed. Button handles mic unmute + stop TTS/music. Speaker unmute is done via voice command (mic still on) or web/Telegram. Button stays simple.

## API Design

```
POST /speaker/mute      → suppress all audio output
POST /speaker/unmute    → resume audio output
GET  /audio/status      → include speaker_muted field
```

Hoặc gộp vào `/audio/*`:
```
POST /audio/mute        → suppress all audio output
POST /audio/unmute      → resume audio output
```

## Implementation Plan

### LeLamp (Python)

1. **`server.py`**: Add `_speaker_muted` flag + `/speaker/mute` + `/speaker/unmute` endpoints
2. **`tts_service.py`**: Check `_speaker_muted` before playing → return early
3. **`music_service.py`**: Check flag before play → skip
4. **`backchannel.py`**: Check flag before playing cue → skip
5. **GPIO17 handler**: Update priority logic
6. **`GET /audio/status`**: Include `speaker_muted` field

### OpenClaw Skills

7. **Voice skill**: Add speaker mute/unmute markers + meeting mode
8. **Trigger phrases**: "im đi", "be quiet", "silent", "đang họp" (meeting = both)

### Web Monitor

9. **Overview**: Speaker mute toggle next to volume control

## Interaction Matrix

| Mic | Speaker | Mode | Use case |
|-----|---------|------|----------|
| ON | ON | Normal | Default |
| ON | OFF | Silent | Working, don't want Lumi talking but still listening |
| OFF | ON | Listen-only | Unlikely — muted mic but speaker on? Maybe music-only mode |
| OFF | OFF | Meeting | In a call, completely silent |

## Open Questions

- Should "im đi" (be quiet) mute speaker permanently or just stop current TTS? Currently "shut up" stops TTS via intent. Mute is different — persistent until unmute.
- "đang họp" → meeting mode (mic + speaker). Should this be 1 HW marker `[HW:/meeting/start:{}]` or 2 separate markers?
- Music pause vs skip when muted: pause allows resume on unmute, skip means lost. Pause better UX.
- Should Lumi show LED indicator when speaker muted? Subtle — maybe dim amber pulse.
