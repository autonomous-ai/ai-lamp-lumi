# AI Lamp — Lumi

An AI-powered lamp running on Raspberry Pi, with OpenClaw as the brain and LeLamp driving the hardware (servo, LED, mic, speaker, camera).

## Layout

- **`lumi/`** — Go backend: HTTP API, MQTT, OTA bootstrap, OpenClaw WebSocket gateway, web UI (React + Vite).
- **`lelamp/`** — Python driver layer for hardware (servo, LED, audio, camera, vision).
- **`dlbackend/`** — Supporting backend service.
- **`claude-desktop-buddy/`** — Companion app for Claude Desktop (BLE pairing).
- **`hardware/`** — Schematics, BOM, hardware notes.
- **`imager/`** — Tooling to build Pi images.
- **`docs/`** — Architecture, flows, use cases (bilingual: EN + `docs/vi/`).
- **`scripts/`** — Deploy and test scripts.

## Build

```bash
# Go backend (cross-compiles to linux/arm64)
make build-lamp
make build-bootstrap

# Web UI
cd lumi/web && npm install && npm run dev

# LeLamp (Python, runs on the Pi)
cd lelamp && uv sync
```

## Docs

Start with `docs/overview.md`, or read `CLAUDE.md` for coding conventions and multi-IDE rules.

## Module

`go-lamp.autonomous.ai` — Go 1.24 — target Linux ARM64.
