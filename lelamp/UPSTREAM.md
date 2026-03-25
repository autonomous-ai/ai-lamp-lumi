# LeLamp Runtime — Upstream Tracking

## Source

- **Repo**: https://github.com/humancomputerlab/lelamp_runtime
- **Commit**: `ee23699` (Update README.md)
- **Date copied**: 2026-03-25

## What we use

- `service/base.py` — ServiceBase (event-driven, priority dispatch)
- `service/motors/motors_service.py` — MotorsService
- `service/motors/animation_service.py` — AnimationService (smooth interpolation)
- `service/rgb/rgb_service.py` — RGBService (64x WS2812)
- `follower/` — LeLampFollower (Feetech servo bus via lerobot)
- `recordings/*.csv` — Pre-recorded animations

## What we ignore (dead code, not imported)

- `leader/` — LeLamp leader arm (not relevant)
- `livekit-agents`, `openai` dependencies — replaced by OpenClaw
- `calibrate.py`, `record.py`, `replay.py` — CLI tools, not imported by server

## How to sync

1. Check upstream for driver-level fixes (servo protocol, LED timing)
2. Cherry-pick relevant changes manually
3. Ignore upstream AI/LiveKit changes
4. Update commit hash above after sync
