# AI Lamp — Lumi

Lumi is an AI-powered desk lamp built on a Raspberry Pi. It listens, sees, moves, and talks. The brain is OpenClaw (LLM + skills + memory); the hands are LeLamp (servo, LED, mic, speaker, camera, display); Lumi Server (Go) glues them together with networking, sensing, OTA, and a web UI.

Target hardware: Raspberry Pi 4/5, Linux ARM64.

## Architecture

Three layers, each independently replaceable:

```
OpenClaw (AI / LLM / skills)
        │  WebSocket
        ▼
Lumi Server (Go, :5000)         ← system, network, MQTT, OTA, sensing routing, local intent
        │  HTTP
        ▼
LeLamp Runtime (Python, :5001)  ← hardware drivers (servo, LED, audio, camera, display)
        │
        ▼
Hardware (plug-and-play; missing parts are skipped)
```

Design principles:

- **Hardware is a plugin.** If a device is missing, that subsystem is skipped — the rest still runs.
- **System layer runs without OpenClaw.** Network, OTA, reset, LED feedback, local intents all work offline.
- **LeLamp has no AI.** Drivers only. AI lives in OpenClaw.
- **SKILL.md native.** OpenClaw reads skill files and calls `curl` against LeLamp/Lumi directly — no MCP layer.
- **Code is the source of truth.** Docs reflect code, never the other way around.

## Repository Layout

| Path | Language | Description |
|------|----------|-------------|
| `lumi/` | Go 1.24 | HTTP API, MQTT, OTA bootstrap, OpenClaw WS gateway, sensing event routing, local intent, ambient behaviors |
| `lumi/web/` | TypeScript / React 19 / Vite / Tailwind 4 | On-device web UI (setup, monitor, configuration) |
| `lelamp/` | Python 3.12 / FastAPI | Hardware drivers — servo, LED, audio (TTS/STT/VAD), camera, vision, GC9A01 display |
| `dlbackend/` | — | Supporting backend service |
| `claude-desktop-buddy/` | Go | Companion BLE pairing app for Claude Desktop |
| `hardware/` | — | Schematics, BOM, mechanical and electrical notes |
| `imager/` | — | Tooling to build flashable Pi images |
| `docs/` | Markdown | Architecture, flows, use cases (bilingual: `docs/` EN + `docs/vi/` VI) |
| `scripts/` | Bash | Deploy, OTA upload, and test scripts |

## Quick Start

### Build the Go backend (cross-compiled for the Pi)

```bash
make lumi-build            # builds lumi/lumi-server (linux/arm64)
make lumi-build-bootstrap  # builds lumi/bootstrap-server (OTA worker)
make lumi-generate         # regenerate Wire DI after provider changes
make lumi-lint             # golangci-lint
make lumi-test             # go test ./...
```

Version is injected at build time via `ldflags` (`VERSION` from `git describe`).

### Run the web UI in dev mode

```bash
make web-install
make web-dev               # Vite dev server
make web-build             # production bundle to lumi/web/dist
```

### LeLamp (runs on the Pi)

```bash
cd lelamp && uv sync       # install Python deps
make lelamp-dev            # uvicorn reload on :5001
make lelamp-run            # production-style run
make lelamp-test           # pytest
```

### Claude Desktop Buddy

```bash
make buddy-build           # builds claude-desktop-buddy/buddy-plugin (linux/arm64)
```

### OTA upload (artifact → GCS)

```bash
make upload-lumi           # push lumi-server
make upload-bootstrap      # push bootstrap-server
make upload-lelamp         # push Python runtime
make upload-web            # push web/dist
make upload-skills         # push resources/openclaw-skills/
make upload-all            # everything except OpenClaw
make upload-openclaw 2026.5.2  # explicit version bump (not in upload-all)
```

## API Response Convention

All Lumi HTTP endpoints return:

```jsonc
// success
{"status": 1, "data": <payload>, "message": null}
// failure
{"status": 0, "data": null, "message": "error"}
```

## Voice Pipeline (brief)

```
Mic (always on) → Local VAD (RMS, free)
    → Speech → Deepgram STT
        → "hey lumi, …"  → voice_command → local intent → execute (~50ms)
        → other speech   → voice         → OpenClaw
    → 3s silence → disconnect Deepgram
```

## Sensing Pipeline (brief)

LeLamp ticks every 2s and runs pluggable detectors on one frame: motion (frame diff), face recognition (InsightFace), ambient light, sound RMS. Events with images (motion, face enter) are JPEG-encoded; face-enter frames are annotated with bounding boxes (green = friend, red = stranger). Events are POSTed to Lumi, which either matches a local intent or forwards to OpenClaw with vision. Cooldowns protect LLM cost: motion/sound 60s, presence 10s, light 30s.

## Documentation

- `docs/overview.md` — architecture deep dive
- `docs/lamp-server.md` — Lumi Server HTTP API and startup
- `docs/led-control.md` — LED states, effects, animations
- `docs/setup-flow.md` — first-boot provisioning
- `docs/flow-monitor.md` — turn pipeline, JSONL logs, SSE
- `docs/mqtt.md` — MQTT dispatch
- `docs/bootstrap-ota.md` — OTA worker
- `docs/sensing-behavior.md`, `docs/sensing-tuning.md` — sensing
- `docs/habit-tracking.md` — pattern-based predictive nudging
- `docs/vision-tracking.md` — object follow, servo tracking
- `docs/web-ui.md` — web UI
- `docs/DEV-MULTI-IDE.md` — Cursor + Claude Code conventions
- `CLAUDE.md` — coding standards and AI assistant rules

Every English doc has a Vietnamese mirror under `docs/vi/`.

## Module

Go module: `go-lamp.autonomous.ai` — Go 1.24 — target Linux ARM64.
