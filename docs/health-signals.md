# Health Signals — LED Status Guide

Lumi uses LED breathing patterns to communicate device status. Each state has a distinct color so users can identify issues at a glance.

## LED Signal Table

| LED Color | Effect | Meaning | When | Auto-clears |
|-----------|--------|---------|------|-------------|
| Cyan `(0,200,200)` | Breathing fast | **Agent Down** — AI brain disconnected | OpenClaw WebSocket drops | Yes — when agent reconnects |
| Purple `(180,0,255)` | Breathing fast | **LeLamp Down** — Hardware server unreachable | LED goes dark when down; purple flash 3s on recovery | Yes — clears after 3s |
| Orange `(255,80,0)` | Breathing fast | **No Internet** — Wi-Fi connected but no internet | 5 consecutive ping failures (~25s) | Yes — when internet restores |
| Blue `(0,80,255)` | Breathing fast | **Booting** — Lumi is starting up | Power on, system restart | Yes — when boot completes |
| Green `(0,255,0)` | Breathing fast | **Updating** — OTA firmware update in progress | Bootstrap detects new firmware | Yes — when update completes (reboots) |
| Red `(255,0,0)` | Breathing fast | **Error** — System error | Critical failure | Yes — when error resolves |

## Priority

When multiple states are active simultaneously, the highest-priority state is shown:

```
Error (highest) > OTA > Booting > Connectivity > LeLamp Down > Agent Down (lowest)
```

Example: if Lumi has no internet AND agent is down, **No Internet** (orange) is shown because it has higher priority.

## Behavior Details

### Agent Down (Cyan)
- Activates when the OpenClaw WebSocket connection drops
- Clears when the WebSocket reconnects successfully
- Voice commands and AI features are unavailable; local LED scenes and servo still work
- TTS announces "Brain reconnected!" on recovery

### LeLamp Down (Purple — or dark/black)
- When LeLamp crashes, LED goes **dark** because the LED driver itself is down
- Health watcher polls every 5 seconds and tracks the outage
- On recovery: purple breathing flashes briefly as the state clears, then normal LED resumes
- TTS announces "Hardware recovered!" on recovery
- LED control, servo, camera, mic, and speaker are unavailable while LeLamp is down

### No Internet (Orange)
- Network service pings every 5 seconds
- After 5 consecutive failures (~25 seconds), LED turns orange
- Clears immediately when a ping succeeds
- Lumi continues to function locally but cloud features are unavailable

### Booting (Blue)
- Activates at startup before the agent is ready
- Clears when the OpenClaw agent connects and is ready to accept commands
- A brief white flash indicates boot is complete

### OTA Update (Green)
- Activates when the bootstrap service detects a new firmware version
- Stays active during download and installation
- Device reboots after update — LED transitions to Booting (blue)

### Error (Red)
- Activates on critical system errors
- Clears when the error condition is resolved

## Normal Operation

When no status state is active, the LED is controlled by:
1. **Emotion presets** — colors driven by the AI agent's emotional state
2. **Scene presets** — user-selected lighting scenes (reading, focus, relax, etc.)
3. **Ambient breathing** — gentle warm breathing when idle

The status LED **overrides** all of the above when active. Once the status clears, normal LED behavior resumes automatically.
