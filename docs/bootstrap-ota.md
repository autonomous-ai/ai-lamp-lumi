# Bootstrap & OTA System — AI Lamp

## 1. Overview

The AI Lamp device runs **5 software components** on a Raspberry Pi 4. All components are installed via an initial setup script and kept up-to-date by a background OTA worker.

| Component | Type | Install Method | Service Name | Install Path |
|---|---|---|---|---|
| **Lumi Server** | Go binary (ARM64) | Download zip from OTA | `lumi.service` | `/usr/local/bin/lumi-server` |
| **Bootstrap Server** | Go binary (ARM64) | Download zip from OTA | `bootstrap.service` | `/usr/local/bin/bootstrap-server` |
| **Web (Setup SPA)** | React/Vite bundle | Download zip from OTA | nginx serves static | `/usr/share/nginx/html/setup/` |
| **OpenClaw** | Node.js package | `npm install -g` | `openclaw.service` | Global npm |
| **LeLamp Runtime** | Python package | Download zip from OTA | `lelamp.service` | `/opt/lelamp/` |

### Architecture Diagram

```
                    ┌──────────────────────────────┐
                    │   OTA Metadata (GCS JSON)     │
                    │                                │
                    │  lumi:      {version, url}     │
                    │  bootstrap: {version, url}     │
                    │  web:       {version, url}     │
                    │  openclaw:  {version}          │
                    │  lelamp:    {version, url}     │
                    └───────────────┬────────────────┘
                                    │ poll every 5m
                                    ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Bootstrap Server (Go, port 8080)               │
│                                                                   │
│  checkLoop() → for each component:                                │
│    1. Detect current installed version                            │
│    2. Compare to OTA metadata target version                      │
│    3. If mismatch → applyUpdate()                                 │
│       → download zip / npm install                                │
│       → extract to install path                                   │
│       → systemctl restart {service}                               │
│    4. Persist state to /root/bootstrap/state.json                 │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

---

## 2. OTA Metadata Format

Single JSON file hosted on GCS. All components reference this file.

**URL**: `https://storage.googleapis.com/{BUCKET}/lumi/ota/metadata.json`

```json
{
  "lumi": {
    "version": "1.2.3",
    "url": "https://storage.googleapis.com/{BUCKET}/lumi/ota/lumi/1.2.3/lumi-1.2.3.zip"
  },
  "bootstrap": {
    "version": "1.0.5",
    "url": "https://storage.googleapis.com/{BUCKET}/lumi/ota/bootstrap/1.0.5/bootstrap-1.0.5.zip"
  },
  "web": {
    "version": "0.9.0",
    "url": "https://storage.googleapis.com/{BUCKET}/lumi/ota/web/0.9.0/setup-0.9.0.zip"
  },
  "openclaw": {
    "version": "2026.3.8"
  },
  "lelamp": {
    "version": "1.0.0",
    "url": "https://storage.googleapis.com/{BUCKET}/lumi/ota/lelamp/1.0.0/lelamp-1.0.0.zip"
  }
}
```

**Domain types** — `domain/ota.go`:

```go
const (
    OTAKeyLumi      = "lumi"
    OTAKeyBootstrap = "bootstrap"
    OTAKeyWeb       = "web"
    OTAKeyOpenClaw  = "openclaw"
    OTAKeyLeLamp    = "lelamp"    // NEW for AI Lamp
)

type OTAMetadata map[string]OTAComponent

type OTAComponent struct {
    Version string `json:"version"`
    URL     string `json:"url,omitempty"`
}
```

---

## 3. Initial Setup (`scripts/setup.sh`)

One-time provisioning script run on a fresh Raspberry Pi. Executes stages sequentially.

### Stage Overview

| Stage | Name | Description |
|---|---|---|
| -1 | Locale fix | Ensure `C.UTF-8` encoding |
| 0 | Prerequisites | System packages, Node.js 22 |
| 0a | WiFi stability | Disable IPv6, WiFi power saving (RPi5) |
| 0b | Enable SPI | For WS2812 LED driver |
| 1 | Fetch OTA metadata | Download metadata.json, extract versions and URLs |
| 1b | Install binaries | Download + install lumi-server, bootstrap-server, create systemd services |
| 2 | Install OpenClaw | `npm install -g openclaw`, create config, create systemd service |
| **2b** | **Install LeLamp** | **Download + install LeLamp Python runtime, create systemd service** (NEW) |
| 3 | Setup nginx | Download web bundle, configure reverse proxy + captive portal |
| 4 | Setup WiFi AP | Configure hostapd, dnsmasq, start AP mode for provisioning |

### Stage 2b: Install LeLamp Runtime (NEW)

This stage installs the LeLamp Python runtime that provides hardware drivers for servos, LEDs, and audio.

```bash
stage_install_lelamp() {
    echo "=== Stage 2b: Install LeLamp Runtime ==="

    # 1. Install Python dependencies
    apt-get install -y python3 python3-pip python3-venv

    # 2. Create install directory
    mkdir -p /opt/lelamp

    # 3. Download from OTA metadata
    LELAMP_URL=$(echo "$OTA_JSON" | jq -r '.lelamp.url')
    LELAMP_VERSION=$(echo "$OTA_JSON" | jq -r '.lelamp.version')

    curl -fsSL "$LELAMP_URL" -o /tmp/lelamp.zip
    unzip -o /tmp/lelamp.zip -d /opt/lelamp/
    rm /tmp/lelamp.zip

    # 4. Install Python dependencies in venv
    python3 -m venv /opt/lelamp/venv
    /opt/lelamp/venv/bin/pip install -r /opt/lelamp/requirements.txt

    # 5. Create systemd service
    cat > /etc/systemd/system/lelamp.service << 'UNIT'
[Unit]
Description=LeLamp Python Runtime — Hardware Drivers
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lelamp
ExecStart=/opt/lelamp/venv/bin/python -m lelamp.server
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

    systemctl daemon-reload
    systemctl enable lelamp.service
    systemctl start lelamp.service

    echo "LeLamp $LELAMP_VERSION installed at /opt/lelamp/"
}
```

### Systemd Services Created by Setup

| Service | ExecStart | Port | Notes |
|---|---|---|---|
| `lumi.service` | `/usr/local/bin/lumi-server` | 5000 | Main HTTP API, always running |
| `bootstrap.service` | `/usr/local/bin/bootstrap-server` | 8080 | OTA worker, polls for updates |
| `openclaw.service` | `xvfb-run ... openclaw gateway run` | — | AI brain, memory limit 1500M |
| `lelamp.service` | `/opt/lelamp/venv/bin/python -m lelamp.server` | TBD | Hardware drivers (servo, LED, audio) |
| nginx | `nginx` | 80 | Setup SPA + reverse proxy to Lumi |

### Service Dependency Order

```
boot
  → intern.service      (system layer, LED boot animation)
  → bootstrap.service   (starts polling for updates)
  → lelamp.service      (hardware drivers ready)
  → openclaw.service    (AI brain, connects to intern via HTTP)
  → nginx               (web UI for setup)
```

---

## 4. Bootstrap OTA Worker

### Config (`config/bootstrap.json`)

```json
{
  "httpPort": 8080,
  "metadata_url": "https://storage.googleapis.com/{BUCKET}/lumi/ota/metadata.json",
  "poll_interval": "5m",
  "state_file": "/root/bootstrap/state.json"
}
```

Falls back to defaults if file missing.

### State (`/root/bootstrap/state.json`)

Tracks last known installed version per component:

```json
{
  "components": {
    "intern": "1.2.3",
    "bootstrap": "1.0.5",
    "web": "0.9.0",
    "openclaw": "2026.3.8",
    "lelamp": "1.0.0"
  }
}
```

### Core Loop (`bootstrap/bootstrap.go`)

```
checkLoop():
  1. checkOnce() immediately on startup
  2. Sleep poll_interval (default 5m)
  3. Repeat

checkOnce():
  1. Fetch OTA metadata JSON
  2. For each key [intern, bootstrap, web, openclaw, lelamp]:
     → reconcile(key, metadata[key])
  3. Save state

reconcile(key, target):
  1. Detect current installed version
  2. Compare to target version
  3. If same → update state, return
  4. If different → applyUpdate(key, target)
```

### Version Detection Per Component

| Component | How to Detect Current Version |
|---|---|
| `intern` | Run `intern-server --version`, parse output |
| `bootstrap` | Compiled-in constant `config.BootstrapVersion` (ldflags) |
| `web` | Read file `/usr/share/nginx/html/setup/VERSION` |
| `openclaw` | Run `openclaw --version`, extract semver with regex |
| `lelamp` | Run `/opt/lelamp/venv/bin/python -m lelamp --version` OR read `/opt/lelamp/VERSION` file |

### Update Application Per Component

| Component | Update Steps |
|---|---|
| `intern` | Run `software-update intern` (blocks up to 10 min) |
| `bootstrap` | Spawn detached `software-update bootstrap` (self-update, survives restart) |
| `web` | Run `software-update web` |
| `openclaw` | Run `npm install -g openclaw@{version}` → `systemctl restart openclaw` |
| `lelamp` | Run `software-update lelamp` |

---

## 5. Software Update Script (`/usr/local/bin/software-update`)

Bash script installed by setup.sh. Called by bootstrap worker to apply updates.

### LeLamp Case (NEW)

```bash
"lelamp")
    echo "Updating LeLamp to $VERSION..."

    # Download
    curl -fsSL "$URL" -o /tmp/lelamp-update.zip

    # Stop service before updating
    systemctl stop lelamp.service

    # Backup current
    cp -r /opt/lelamp /opt/lelamp.bak 2>/dev/null || true

    # Extract (preserve venv if only code changed, or rebuild)
    unzip -o /tmp/lelamp-update.zip -d /opt/lelamp/

    # Reinstall dependencies if requirements.txt changed
    /opt/lelamp/venv/bin/pip install -r /opt/lelamp/requirements.txt --quiet

    # Restart
    systemctl start lelamp.service

    # Cleanup
    rm -f /tmp/lelamp-update.zip
    rm -rf /opt/lelamp.bak

    echo "LeLamp updated to $VERSION"
    ;;
```

---

## 6. LeLamp Runtime Package Structure

The LeLamp zip distributed via OTA should contain:

```
lelamp-{version}.zip
├── lelamp/
│   ├── __init__.py           # Package init, exposes __version__
│   ├── server.py             # HTTP server exposing hardware control API
│   ├── services/
│   │   ├── motors.py         # MotorsService — 5x Feetech servo control
│   │   ├── rgb.py            # RGBService — 64x WS2812 LED (rpi_ws281x)
│   │   ├── audio.py          # Audio — amixer, playback, TTS
│   │   ├── display.py        # DisplayService — GC9A01 LCD (eyes + info)
│   │   └── service_base.py   # Event-driven ServiceBase with priority dispatch
│   └── config.py             # Runtime config
├── requirements.txt          # Python dependencies
└── VERSION                   # Plain text version string (e.g., "1.0.0")
```

### LeLamp HTTP API (for Intern Server to bridge to)

The LeLamp Python runtime exposes its own HTTP API on a local port (e.g., `127.0.0.1:5001`). The Intern Server (Go, port 5000) proxies/bridges OpenClaw skill requests to this API.

```
OpenClaw LLM → curl 127.0.0.1:5000/api/servo → Intern Server → http://127.0.0.1:5001/servo → LeLamp Python → Hardware
```

This is the **Go-to-Python bridge** — a simple HTTP proxy. LeLamp runtime runs its own lightweight HTTP server (Flask/FastAPI) that directly controls hardware.

---

## 7. Upload / Publish Scripts

### `scripts/upload-lelamp.sh` (NEW)

```bash
#!/usr/bin/env bash
# Upload LeLamp runtime to OTA

set -euo pipefail

VERSION_FILE="VERSION_LELAMP"
BUCKET="s3-autonomous-upgrade-3"
OTA_PATH="intern/ota/lelamp"
METADATA_PATH="intern/ota/metadata.json"

# Auto-increment patch version
CURRENT=$(cat "$VERSION_FILE" 2>/dev/null || echo "0.0.0")
MAJOR=$(echo "$CURRENT" | cut -d. -f1)
MINOR=$(echo "$CURRENT" | cut -d. -f2)
PATCH=$(echo "$CURRENT" | cut -d. -f3)
NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))"
echo "$NEW_VERSION" > "$VERSION_FILE"

# Package
echo "Packaging LeLamp $NEW_VERSION..."
cd path/to/lelamp-source
echo "$NEW_VERSION" > VERSION
zip -r "/tmp/lelamp-${NEW_VERSION}.zip" lelamp/ requirements.txt VERSION

# Upload zip
gsutil cp "/tmp/lelamp-${NEW_VERSION}.zip" \
    "gs://${BUCKET}/${OTA_PATH}/${NEW_VERSION}/lelamp-${NEW_VERSION}.zip"

# Update metadata
DOWNLOAD_URL="https://storage.googleapis.com/${BUCKET}/${OTA_PATH}/${NEW_VERSION}/lelamp-${NEW_VERSION}.zip"
gsutil cp "gs://${BUCKET}/${METADATA_PATH}" /tmp/metadata.json
jq --arg v "$NEW_VERSION" --arg u "$DOWNLOAD_URL" \
    '.lelamp = {"version": $v, "url": $u}' /tmp/metadata.json > /tmp/metadata-updated.json
gsutil cp /tmp/metadata-updated.json "gs://${BUCKET}/${METADATA_PATH}"

echo "LeLamp $NEW_VERSION published."
```

### Existing Upload Scripts (inherited from lobster)

| Script | Component | Pattern |
|---|---|---|
| `scripts/upload-intern.sh` | Intern Server binary | Build → zip → GCS → update metadata |
| `scripts/upload-bootstrap.sh` | Bootstrap Server binary | Build → zip → GCS → update metadata |
| `scripts/upload-web.sh` | Web SPA bundle | Build → zip → GCS → update metadata |
| `scripts/upload-lelamp.sh` | LeLamp Python runtime (NEW) | Package → zip → GCS → update metadata |

---

## 8. Build & Version Injection

### Go Binaries (ldflags)

```makefile
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")

LDFLAGS_BOOTSTRAP := -X go-lamp.autonomous.ai/bootstrap/config.BootstrapVersion=$(VERSION)
LDFLAGS_INTERN    := -X go-lamp.autonomous.ai/server/config.InternVersion=$(VERSION)

build-bootstrap:
	GOOS=linux GOARCH=arm64 go build -ldflags "$(LDFLAGS_BOOTSTRAP)" -o bootstrap-server ./cmd/bootstrap

build-lamp:
	GOOS=linux GOARCH=arm64 go build -ldflags "$(LDFLAGS_INTERN)" -o intern-server ./cmd/lamp
```

### LeLamp (VERSION file)

LeLamp version is a plain text `VERSION` file in the package root. Read by bootstrap via file or `python -m lelamp --version`.

---

## 9. Key Differences from Lobster

| Aspect | Lobster (original) | AI Lamp (this project) |
|---|---|---|
| Components | 4 (intern, bootstrap, web, openclaw) | **5** (+ lelamp) |
| OTA keys | intern, bootstrap, web, openclaw | + **lelamp** |
| Setup stages | 7 (stages -1 to 4) | **8** (+ stage 2b: LeLamp) |
| Systemd services | 4 | **5** (+ lelamp.service) |
| Python runtime | None | **LeLamp** at /opt/lelamp/ with venv |
| Hardware bridge | N/A | Intern HTTP → LeLamp HTTP (localhost proxy) |
| SPI usage | LED only | LED + **Display (GC9A01)** |

---

## 10. Open Questions

- [ ] **LeLamp source**: Where does the LeLamp Python code live? Fork of `humancomputerlab/lelamp_runtime`? Or new code in this repo under `lelamp/`?
- [ ] **LeLamp HTTP port**: What port does the LeLamp Python server listen on? Suggested: `5001` (intern is `5000`).
- [ ] **Bridge protocol**: Simple HTTP proxy in Go? Or more structured (gRPC, Unix socket)?
- [ ] **Python version**: Pin to Python 3.11+? LeLamp's current Python version requirement?
- [ ] **LeLamp packaging**: Include pre-built venv? Or install deps on-device? (Pi has limited resources for `pip install`)
- [ ] **Display driver**: DisplayService (GC9A01) — part of LeLamp Python? Or new module?
- [ ] **LeLamp config**: Does LeLamp need its own config file? Or configured via Intern Server?

---

*This document describes the full OTA and bootstrap system. For architecture decisions, see [architecture-decision.md](architecture-decision.md). For product vision, see [product-vision.md](product-vision.md).*
