# Bootstrap & OTA — AI Lamp

## 1. Tổng Quan

AI Lamp chạy **5 thành phần phần mềm** trên Raspberry Pi 4. Tất cả được cài đặt qua script setup ban đầu và cập nhật tự động qua OTA worker chạy nền.

| Thành phần | Loại | Cách cài | Service | Đường dẫn |
|---|---|---|---|---|
| **Intern Server** | Go binary (ARM64) | Tải zip từ OTA | `intern.service` | `/usr/local/bin/intern-server` |
| **Bootstrap Server** | Go binary (ARM64) | Tải zip từ OTA | `bootstrap.service` | `/usr/local/bin/bootstrap-server` |
| **Web (Setup SPA)** | React/Vite | Tải zip từ OTA | nginx serve static | `/usr/share/nginx/html/setup/` |
| **OpenClaw** | Node.js package | `npm install -g` | `openclaw.service` | Global npm |
| **LeLamp Runtime** | Python package | Tải zip từ OTA | `lelamp.service` | `/opt/lelamp/` |

### Sơ đồ hệ thống

```
                    ┌──────────────────────────────┐
                    │   OTA Metadata (GCS JSON)     │
                    │                                │
                    │  intern:    {version, url}     │
                    │  bootstrap: {version, url}     │
                    │  web:       {version, url}     │
                    │  openclaw:  {version}          │
                    │  lelamp:    {version, url}     │
                    └───────────────┬────────────────┘
                                    │ poll mỗi 5 phút
                                    ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Bootstrap Server (Go, port 8080)               │
│                                                                   │
│  checkLoop() → với mỗi thành phần:                               │
│    1. Phát hiện version hiện tại đang cài                        │
│    2. So sánh với version mục tiêu trong OTA metadata            │
│    3. Nếu khác → applyUpdate()                                   │
│       → tải zip / npm install                                     │
│       → giải nén vào đường dẫn cài đặt                           │
│       → systemctl restart {service}                               │
│    4. Lưu trạng thái vào /root/bootstrap/state.json              │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

---

## 2. OTA Metadata

File JSON duy nhất trên GCS. Tất cả thành phần tham chiếu file này.

**URL**: `https://storage.googleapis.com/{BUCKET}/intern/ota/metadata.json`

```json
{
  "intern": {
    "version": "1.2.3",
    "url": "https://storage.googleapis.com/{BUCKET}/intern/ota/intern/1.2.3/intern-1.2.3.zip"
  },
  "bootstrap": {
    "version": "1.0.5",
    "url": "https://storage.googleapis.com/{BUCKET}/intern/ota/bootstrap/1.0.5/bootstrap-1.0.5.zip"
  },
  "web": {
    "version": "0.9.0",
    "url": "https://storage.googleapis.com/{BUCKET}/intern/ota/web/0.9.0/setup-0.9.0.zip"
  },
  "openclaw": {
    "version": "2026.3.8"
  },
  "lelamp": {
    "version": "1.0.0",
    "url": "https://storage.googleapis.com/{BUCKET}/intern/ota/lelamp/1.0.0/lelamp-1.0.0.zip"
  }
}
```

**Domain types** — `domain/ota.go`:

```go
const (
    OTAKeyIntern    = "intern"
    OTAKeyBootstrap = "bootstrap"
    OTAKeyWeb       = "web"
    OTAKeyOpenClaw  = "openclaw"
    OTAKeyLeLamp    = "lelamp"    // MỚI cho AI Lamp
)

type OTAMetadata map[string]OTAComponent

type OTAComponent struct {
    Version string `json:"version"`
    URL     string `json:"url,omitempty"`
}
```

---

## 3. Setup Ban Đầu (`scripts/setup.sh`)

Script chạy **1 lần duy nhất** trên Pi mới. Thực thi tuần tự theo stages.

### Tổng quan stages

| Stage | Tên | Mô tả |
|---|---|---|
| -1 | Locale fix | Đảm bảo encoding `C.UTF-8` |
| 0 | Prerequisites | Packages hệ thống, Node.js 22 |
| 0a | WiFi stability | Tắt IPv6, WiFi power saving (RPi5) |
| 0b | Enable SPI | Cho WS2812 LED driver + GC9A01 display |
| 1 | Fetch OTA metadata | Tải metadata.json, trích xuất versions và URLs |
| 1b | Install binaries | Tải + cài intern-server, bootstrap-server, tạo systemd services |
| 2 | Install OpenClaw | `npm install -g openclaw`, tạo config, systemd service |
| **2b** | **Install LeLamp** | **Tải + cài LeLamp Python runtime, tạo systemd service** (MỚI) |
| 3 | Setup nginx | Tải web bundle, cấu hình reverse proxy + captive portal |
| 4 | Setup WiFi AP | Cấu hình hostapd, dnsmasq, bật AP mode cho provisioning |

### Stage 2b: Cài LeLamp Runtime (MỚI)

```bash
stage_install_lelamp() {
    echo "=== Stage 2b: Install LeLamp Runtime ==="

    # 1. Cài Python dependencies hệ thống
    apt-get install -y python3 python3-pip python3-venv

    # 2. Tạo thư mục cài đặt
    mkdir -p /opt/lelamp

    # 3. Tải từ OTA metadata
    LELAMP_URL=$(echo "$OTA_JSON" | jq -r '.lelamp.url')
    LELAMP_VERSION=$(echo "$OTA_JSON" | jq -r '.lelamp.version')

    curl -fsSL "$LELAMP_URL" -o /tmp/lelamp.zip
    unzip -o /tmp/lelamp.zip -d /opt/lelamp/
    rm /tmp/lelamp.zip

    # 4. Cài Python dependencies trong venv
    python3 -m venv /opt/lelamp/venv
    /opt/lelamp/venv/bin/pip install -r /opt/lelamp/requirements.txt

    # 5. Tạo systemd service
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

### Systemd Services trên thiết bị

| Service | Lệnh chạy | Port | Ghi chú |
|---|---|---|---|
| `intern.service` | `/usr/local/bin/intern-server` | 5000 | HTTP API chính, luôn chạy |
| `bootstrap.service` | `/usr/local/bin/bootstrap-server` | 8080 | OTA worker, poll cập nhật |
| `openclaw.service` | `xvfb-run ... openclaw gateway run` | — | AI brain, memory limit 1500M |
| `lelamp.service` | `/opt/lelamp/venv/bin/python -m lelamp.server` | TBD | Hardware drivers (servo, LED, audio, display) |
| nginx | `nginx` | 80 | Setup SPA + reverse proxy |

### Thứ tự khởi động

```
boot
  → intern.service      (tầng hệ thống, LED boot animation)
  → bootstrap.service   (bắt đầu poll cập nhật)
  → lelamp.service      (hardware drivers sẵn sàng)
  → openclaw.service    (AI brain, kết nối intern qua HTTP)
  → nginx               (web UI cho setup)
```

---

## 4. Bootstrap OTA Worker

### Config (`config/bootstrap.json`)

```json
{
  "httpPort": 8080,
  "metadata_url": "https://storage.googleapis.com/{BUCKET}/intern/ota/metadata.json",
  "poll_interval": "5m",
  "state_file": "/root/bootstrap/state.json"
}
```

Nếu file không tồn tại → dùng giá trị mặc định.

### State (`/root/bootstrap/state.json`)

Lưu version đã cài của mỗi thành phần:

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

### Luồng xử lý chính (`bootstrap/bootstrap.go`)

```
checkLoop():
  1. checkOnce() ngay khi khởi động
  2. Sleep poll_interval (mặc định 5 phút)
  3. Lặp lại

checkOnce():
  1. Tải OTA metadata JSON
  2. Với mỗi key [intern, bootstrap, web, openclaw, lelamp]:
     → reconcile(key, metadata[key])
  3. Lưu state

reconcile(key, target):
  1. Phát hiện version hiện tại đã cài
  2. So sánh với version mục tiêu
  3. Nếu giống → cập nhật state, return
  4. Nếu khác → applyUpdate(key, target)
```

### Phát hiện version hiện tại

| Thành phần | Cách phát hiện |
|---|---|
| `intern` | Chạy `intern-server --version`, parse output |
| `bootstrap` | Hằng số compile-time `config.BootstrapVersion` (ldflags) |
| `web` | Đọc file `/usr/share/nginx/html/setup/VERSION` |
| `openclaw` | Chạy `openclaw --version`, trích xuất semver bằng regex |
| `lelamp` | Chạy `/opt/lelamp/venv/bin/python -m lelamp --version` HOẶC đọc `/opt/lelamp/VERSION` |

### Cách cập nhật từng thành phần

| Thành phần | Các bước |
|---|---|
| `intern` | Chạy `software-update intern` (block tối đa 10 phút) |
| `bootstrap` | Spawn detached `software-update bootstrap` (tự cập nhật, sống sót sau restart) |
| `web` | Chạy `software-update web` |
| `openclaw` | Chạy `npm install -g openclaw@{version}` → `systemctl restart openclaw` |
| `lelamp` | Chạy `software-update lelamp` |

---

## 5. Script Cập Nhật (`/usr/local/bin/software-update`)

Bash script được cài bởi setup.sh. Bootstrap worker gọi script này để thực hiện cập nhật.

### Xử lý LeLamp (MỚI)

```bash
"lelamp")
    echo "Updating LeLamp to $VERSION..."

    # Tải
    curl -fsSL "$URL" -o /tmp/lelamp-update.zip

    # Dừng service trước khi cập nhật
    systemctl stop lelamp.service

    # Backup
    cp -r /opt/lelamp /opt/lelamp.bak 2>/dev/null || true

    # Giải nén (giữ venv nếu chỉ thay đổi code, hoặc rebuild)
    unzip -o /tmp/lelamp-update.zip -d /opt/lelamp/

    # Cài lại dependencies nếu requirements.txt thay đổi
    /opt/lelamp/venv/bin/pip install -r /opt/lelamp/requirements.txt --quiet

    # Khởi động lại
    systemctl start lelamp.service

    # Dọn dẹp
    rm -f /tmp/lelamp-update.zip
    rm -rf /opt/lelamp.bak

    echo "LeLamp updated to $VERSION"
    ;;
```

---

## 6. Cấu Trúc Package LeLamp

Zip phân phối qua OTA:

```
lelamp-{version}.zip
├── lelamp/
│   ├── __init__.py           # Package init, expose __version__
│   ├── server.py             # HTTP server expose hardware control API
│   ├── services/
│   │   ├── motors.py         # MotorsService — 5x Feetech servo
│   │   ├── rgb.py            # RGBService — 64x WS2812 LED (rpi_ws281x)
│   │   ├── audio.py          # Audio — amixer, playback, TTS
│   │   ├── display.py        # DisplayService — GC9A01 LCD (eyes + info)
│   │   └── service_base.py   # Event-driven ServiceBase, priority dispatch
│   └── config.py             # Runtime config
├── requirements.txt          # Python dependencies
└── VERSION                   # Version string (ví dụ: "1.0.0")
```

### LeLamp HTTP API (để Intern Server bridge đến)

LeLamp Python runtime expose HTTP API riêng trên port local (ví dụ `127.0.0.1:5001`). Intern Server (Go, port 5000) proxy/bridge request từ OpenClaw skills đến API này.

```
OpenClaw LLM
  → curl 127.0.0.1:5000/api/servo
    → Intern Server (Go)
      → http://127.0.0.1:5001/servo
        → LeLamp Python
          → Phần cứng (servo/LED/audio/display)
```

Đây là **Go-to-Python bridge** — HTTP proxy đơn giản. LeLamp chạy HTTP server nhẹ (Flask/FastAPI) trực tiếp điều khiển phần cứng.

---

## 7. Scripts Upload / Publish

### `scripts/upload-lelamp.sh` (MỚI)

```bash
#!/usr/bin/env bash
# Upload LeLamp runtime lên OTA

set -euo pipefail

VERSION_FILE="VERSION_LELAMP"
BUCKET="s3-autonomous-upgrade-3"
OTA_PATH="intern/ota/lelamp"
METADATA_PATH="intern/ota/metadata.json"

# Tự tăng patch version
CURRENT=$(cat "$VERSION_FILE" 2>/dev/null || echo "0.0.0")
MAJOR=$(echo "$CURRENT" | cut -d. -f1)
MINOR=$(echo "$CURRENT" | cut -d. -f2)
PATCH=$(echo "$CURRENT" | cut -d. -f3)
NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))"
echo "$NEW_VERSION" > "$VERSION_FILE"

# Đóng gói
echo "Packaging LeLamp $NEW_VERSION..."
cd path/to/lelamp-source
echo "$NEW_VERSION" > VERSION
zip -r "/tmp/lelamp-${NEW_VERSION}.zip" lelamp/ requirements.txt VERSION

# Upload zip
gsutil cp "/tmp/lelamp-${NEW_VERSION}.zip" \
    "gs://${BUCKET}/${OTA_PATH}/${NEW_VERSION}/lelamp-${NEW_VERSION}.zip"

# Cập nhật metadata
DOWNLOAD_URL="https://storage.googleapis.com/${BUCKET}/${OTA_PATH}/${NEW_VERSION}/lelamp-${NEW_VERSION}.zip"
gsutil cp "gs://${BUCKET}/${METADATA_PATH}" /tmp/metadata.json
jq --arg v "$NEW_VERSION" --arg u "$DOWNLOAD_URL" \
    '.lelamp = {"version": $v, "url": $u}' /tmp/metadata.json > /tmp/metadata-updated.json
gsutil cp /tmp/metadata-updated.json "gs://${BUCKET}/${METADATA_PATH}"

echo "LeLamp $NEW_VERSION published."
```

### Tất cả upload scripts

| Script | Thành phần | Pattern |
|---|---|---|
| `scripts/upload-intern.sh` | Intern Server binary | Build → zip → GCS → update metadata |
| `scripts/upload-bootstrap.sh` | Bootstrap Server binary | Build → zip → GCS → update metadata |
| `scripts/upload-web.sh` | Web SPA bundle | Build → zip → GCS → update metadata |
| `scripts/upload-lelamp.sh` | LeLamp Python runtime (MỚI) | Package → zip → GCS → update metadata |

---

## 8. Build & Version

### Go binaries (ldflags)

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

Version của LeLamp là file text `VERSION` trong thư mục gốc package. Bootstrap đọc qua file hoặc `python -m lelamp --version`.

---

## 9. Khác Biệt So Với Lobster

| Khía cạnh | Lobster (gốc) | AI Lamp (project này) |
|---|---|---|
| Số thành phần | 4 (intern, bootstrap, web, openclaw) | **5** (+ lelamp) |
| OTA keys | intern, bootstrap, web, openclaw | + **lelamp** |
| Setup stages | 7 (stage -1 đến 4) | **8** (+ stage 2b: LeLamp) |
| Systemd services | 4 | **5** (+ lelamp.service) |
| Python runtime | Không có | **LeLamp** tại /opt/lelamp/ với venv |
| Hardware bridge | Không có | Intern HTTP → LeLamp HTTP (localhost proxy) |
| SPI usage | Chỉ LED | LED + **Display (GC9A01)** |

---

## 10. Câu Hỏi Mở

- [ ] **LeLamp source**: Code Python nằm ở đâu? Fork từ `humancomputerlab/lelamp_runtime`? Hay code mới trong repo này dưới `lelamp/`?
- [ ] **LeLamp HTTP port**: Port nào cho LeLamp Python server? Đề xuất: `5001` (intern là `5000`).
- [ ] **Bridge protocol**: HTTP proxy đơn giản trong Go? Hay structured hơn (gRPC, Unix socket)?
- [ ] **Python version**: Pin Python 3.11+? Yêu cầu Python hiện tại của LeLamp?
- [ ] **Đóng gói LeLamp**: Include venv sẵn? Hay cài deps trên thiết bị? (Pi resources hạn chế cho `pip install`)
- [ ] **Display driver**: DisplayService (GC9A01) — nằm trong LeLamp Python? Hay module mới?
- [ ] **LeLamp config**: LeLamp cần config file riêng? Hay cấu hình qua Intern Server?

---

> Tài liệu này mô tả toàn bộ hệ thống OTA và bootstrap.
> Xem [architecture-decision.md](architecture-decision.md) cho quyết định kiến trúc.
> Xem [product-vision.md](product-vision.md) cho tầm nhìn sản phẩm.
