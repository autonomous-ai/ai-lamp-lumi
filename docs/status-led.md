# Status LED — Specification

Status LEDs give users visual feedback about what Lumi is doing internally.
Without them, users cannot tell whether Lumi is thinking, updating, or broken.

## Design Principles

1. **Glanceable** — each state has a unique color + effect so the user never has to guess.
2. **Non-intrusive** — status LEDs yield to user-initiated scenes/emotions. When the status clears, ambient behavior resumes automatically.
3. **Priority-based** — when multiple states are active simultaneously, the highest-priority state wins.

## States

| State | Color | Effect | Speed | Priority | Triggered by |
|-------|-------|--------|-------|----------|-------------|
| **Processing** | Blue `(80, 140, 255)` | `pulse` | 1.0 | 1 (lowest) | Agent lifecycle `start` → `end` |
| **OTA** | Orange `(255, 140, 0)` | `breathing` | 0.4 | 2 | Bootstrap `reconcile` detects update |
| **Error** | Red `(255, 30, 30)` | `pulse` | 1.5 | 3 (highest) | OTA failure, critical errors |

### OTA sub-states

| Phase | LED behavior |
|-------|-------------|
| Downloading + installing | Orange breathing |
| Success | Green flash `(0, 255, 80)` via `notification_flash`, then stop |
| Failure | Red pulse `(255, 30, 30)` |

## Architecture

### Lumi (lamp-server)

`internal/statusled/Service` manages active states with a priority map.

```
SSE handler (lifecycle start) → statusled.Set(Processing)
        ↓ agent thinks...
SSE handler (lifecycle end)   → statusled.Clear(Processing)
        ↓
ambient service resumes breathing LED after 60s silence
```

The service calls LeLamp's `/led/effect` endpoint via `lib/lelamp` (shared HTTP client).

### Bootstrap (bootstrap-server)

Bootstrap is a separate binary. It calls `lib/lelamp` directly in the `reconcile` function:

```
reconcile detects update → lelamp.SetEffect("breathing", orange)
        ↓ applies update...
success → lelamp.SetEffect("notification_flash", green)
failure → lelamp.SetEffect("pulse", red)
```

## Integration with Ambient

The ambient service (`internal/ambient`) pauses on interaction events (`chat_send`, `chat_response`, etc.). During agent processing, ambient is already paused because the voice/chat interaction triggers a pause. When statusled clears the processing state, it calls `lelamp.StopEffect()`. After 60s of silence, ambient resumes its breathing LED.

## Shared LeLamp Client

`lib/lelamp/client.go` provides a thin HTTP wrapper used by all Go code that controls LEDs:

| Function | Endpoint | Purpose |
|----------|----------|---------|
| `SetEffect(effect, r, g, b, speed)` | `POST /led/effect` | Start a named effect |
| `StopEffect()` | `POST /led/effect/stop` | Stop running effect |
| `SetSolid(r, g, b)` | `POST /led/solid` | Set solid color |
| `Off()` | `POST /led/off` | Turn off LEDs |

All calls are fire-and-forget with a 5s timeout. Hardware unavailability is silently ignored.

## User Experience

| User sees | What's happening |
|-----------|-----------------|
| Blue pulsing light | Lumi heard you and is thinking |
| Orange breathing light | Lumi is updating itself (OTA) |
| Green flash | Update completed successfully |
| Red pulsing light | Something went wrong |
| Warm breathing (normal) | Lumi is idle, just vibing |
