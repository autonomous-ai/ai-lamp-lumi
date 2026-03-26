# Web UI — Lumi Monitor Dashboard

## Ngày cập nhật: 2026-03-26

---

## 1. Tổng Quan

Web UI của Lumi là một React SPA (Single Page Application) được build bằng **React 19 + TypeScript + Vite + Tailwind CSS 4**, phục vụ hai mục đích:

1. **Setup flow** — Onboarding WiFi, LLM provider, messaging channel (các trang `/setup/*`)
2. **Monitor Dashboard** — Theo dõi trạng thái thiết bị real-time (`/monitor`)

File build output (`dist/`) được nginx serve tại root `/` trên thiết bị.

---

## 2. Cấu Trúc Thư Mục

```
lumi/web/
├── src/
│   ├── pages/
│   │   ├── Monitor.tsx        # Dashboard monitor (file chính)
│   │   └── ...                # Các trang setup
│   ├── components/
│   │   └── ui/                # shadcn/ui components
│   ├── index.css              # Global styles + theme variables
│   └── main.tsx
├── vite.config.ts
└── package.json
```

---

## 3. Monitor Dashboard (`/monitor`)

### 3.1 Thiết Kế Tổng Thể

Monitor dùng dark theme riêng với class `.lm-root` (định nghĩa trong `index.css`), **không dùng Tailwind** — toàn bộ styling dùng inline styles với CSS variables `--lm-*`.

Layout: **Sidebar 192px cố định + Main area co giãn**, chiều cao 100vh.

### 3.2 Sidebar Navigation

4 section có thể chuyển đổi bằng local state (`section: Section`):

| Icon | Section | Nội dung |
|------|---------|---------|
| ◈ | Overview | Tổng quan toàn bộ hệ thống |
| ⬡ | System | CPU/RAM/Temp chi tiết + lịch sử |
| ◎ | Workflow | OpenClaw event feed real-time |
| ⬟ | Camera | MJPEG stream + Display LCD |

Góc dưới sidebar hiển thị trạng thái OpenClaw (online/offline) và thời điểm cập nhật gần nhất.

### 3.3 Dark Theme Variables

Định nghĩa tại `.lm-root` trong `index.css`:

```css
--lm-bg:          #0C0B09   /* Background chính */
--lm-sidebar:     #111009   /* Sidebar */
--lm-card:        #17160F   /* Card background */
--lm-surface:     #1E1D14   /* Surface bên trong card */
--lm-border:      #2A2820   /* Border */
--lm-border-hi:   #3A3828   /* Border highlight */
--lm-amber:       #F59E0B   /* Màu chủ đạo (warm lamp) */
--lm-amber-dim:   rgba(245,158,11,0.12)
--lm-amber-glow:  rgba(245,158,11,0.35)
--lm-teal:        #2DD4BF
--lm-green:       #34D399
--lm-red:         #F87171
--lm-blue:        #60A5FA
--lm-purple:      #A78BFA
--lm-text:        #F0EEE8
--lm-text-dim:    #9A9080
--lm-text-muted:  #504A3C
```

---

## 4. Polling & Data Sources

Monitor poll tất cả API mỗi **3 giây** qua `setInterval`. Các endpoint được gọi:

### 4.1 Lumi Server (Go, port 5000, prefix `/api`)

| Endpoint | Dữ liệu |
|----------|---------|
| `GET /api/system/info` | CPU load, RAM (KB), nhiệt độ, uptime, goroutines, version, deviceId |
| `GET /api/system/network` | SSID, IP, signal (dBm), internet (bool) |
| `GET /api/openclaw/status` | name, connected (bool), sessionKey (bool) |
| `GET /api/openclaw/recent` | 100 MonitorEvent gần nhất (seed lần đầu) |
| `GET /api/openclaw/events` | SSE stream — MonitorEvent real-time |

> **Lưu ý format**: Lumi API trả `{ status: 1, data: <payload>, message: null }` khi thành công.

### 4.2 LeLamp (Python/FastAPI, port 5001, prefix `/hw`)

| Endpoint | Dữ liệu |
|----------|---------|
| `GET /hw/health` | Trạng thái 8 hardware: servo, led, camera, audio, sensing, voice, tts, display |
| `GET /hw/presence` | state, enabled, seconds_since_motion |
| `GET /hw/voice/status` | voice_available, voice_listening, tts_available, tts_speaking |
| `GET /hw/servo` | available_recordings, current |
| `GET /hw/display` | mode, hardware, available_expressions |
| `GET /hw/audio/volume` | control, volume (0–100) |
| `GET /hw/led/color` | led_count, color [R,G,B], hex (#rrggbb) |

---

## 5. Các Section Chi Tiết

### 5.1 Overview Section

Gồm các card:

**OpenClaw AI**
- Trạng thái connected/disconnected
- Tên agent
- Session key: Acquired / Pending

**Network**
- SSID + Signal bars (4 mức dựa trên dBm)
- IP address
- Internet status

**Presence**
- State (active/idle)
- Sensing enabled/disabled
- Thời gian kể từ lần detect chuyển động cuối

**Voice & TTS**
- Mic available + đang listening (badge LIVE)
- TTS available + đang speaking (badge SPEAKING)
- Volume hiện tại

**Hardware** (card ngang)
- 8 badge: Servo / LED / Camera / Audio / Sensing / Voice / TTS / Display
- **LED color swatch**: ô màu vuông bo góc hiển thị màu hiện tại của dải LED, kèm hex code. Lấy từ `GET /hw/led/color`.

**Servo Pose**
- Pose đang chạy (current)
- Danh sách poses available (tối đa 8)

**Display Eyes**
- Expression đang hiển thị (mode)
- Danh sách expressions available

**System quick stats**
- CPU, RAM, Temp, Uptime dạng pill

### 5.2 System Section

**Performance** — 3 GaugeRing SVG:
- CPU: màu amber, hiện `%`
- Memory: màu blue, detail `used/total MB` (chuyển đổi từ KB: `value / 1024`)
- Temp: màu teal (< 70°C) hoặc red (≥ 70°C), scale 0–85°C

**CPU History / RAM History** — Sparkline chart (area + line):
- Lưu 60 điểm lịch sử (`HISTORY_LEN = 60`)
- Cập nhật mỗi 3 giây

**Process**: goroutines, uptime, version, deviceId
**Network Detail**: SSID, IP, signal, internet

### 5.3 Workflow Section

SSE event feed từ `/api/openclaw/events`:

| Type | Màu | Ý nghĩa |
|------|-----|---------|
| `lifecycle` | amber | Agent bắt đầu / kết thúc run |
| `tool_call` | teal | AI gọi một tool |
| `thinking` | purple | AI đang suy nghĩ (streaming) |
| `assistant_delta` | blue | AI đang trả lời (streaming delta) |
| `chat_response` | green | Chat response final |

Mỗi event hiển thị: type badge, phase (nếu có), runId (8 ký tự đầu), timestamp, summary text, error (nếu có).

Feed tự động scroll xuống event mới nhất. Được seed từ `/api/openclaw/recent` khi load trang.

### 5.4 Camera Section

- **Camera Stream**: MJPEG live stream từ `GET /hw/camera/stream`
- **Display Eyes (GC9A01)**: Snapshot màn hình tròn 1.28" từ `GET /hw/display/snapshot`, hiển thị dạng hình tròn với amber glow. Có nút Refresh.
- **Camera Snapshot**: Ảnh tĩnh từ `GET /hw/camera/snapshot`, có nút Capture để chụp mới.

---

## 6. LED Color API

### Vấn đề
`GET /hw/led` gốc chỉ trả `{ led_count: 64 }` — không có thông tin màu hiện tại.

### Giải pháp
Thêm `GET /hw/led/color` vào `lelamp/server.py`:

```python
@app.get("/led/color", response_model=LEDColorResponse, tags=["LED"])
def get_led_color():
    """Get the current LED color (last color set on the strip)."""
```

**Ưu tiên lấy màu:**
1. `sensing_service.presence._last_color` — màu base được track khi AI set
2. Fallback: `rgb_service.strip.getPixelColor(0)` — đọc trực tiếp từ hardware

**Tracking đã được bổ sung cho:**
- `POST /led/solid` ✅ (đã có từ trước)
- `POST /scene` ✅ (đã có từ trước)
- `POST /emotion` ✅ (bổ sung thêm — đây là path AI dùng nhiều nhất)

> **Lưu ý**: `GET /hw/led/color` là **read-only**, monitor chỉ đọc, không set màu.

---

## 7. Reusable Components (nội bộ Monitor.tsx)

| Component | Mô tả |
|-----------|-------|
| `GaugeRing` | SVG ring chart với drop-shadow glow, transition 0.7s |
| `Sparkline` | SVG area + line chart, nhận mảng số |
| `HWBadge` | Badge xanh/đỏ cho hardware status |
| `StatusDot` | Chấm tròn xanh/đỏ với glow |
| `SignalBars` | 4 bar WiFi signal (ngưỡng: -50/-65/-75/-85 dBm) |
| `StatPill` | Row label + value trong card |

---

## 8. Build & Deploy

```bash
# Build production
make web-build        # tsc + vite build → lumi/web/dist/

# Deploy lên Pi
make web-deploy       # web-build + rsync dist/ → /usr/share/nginx/html/setup/

# Deploy LeLamp (khi thay đổi server.py)
make lelamp-deploy    # rsync + pip install + systemctl restart lumi-lelamp.service
```

> Deploy dùng `PI_HOST=lumi.local` (mDNS). Nếu không resolve được, dùng IP trực tiếp:
> `PI_USER=root PI_HOST=<DEVICE_IP> make web-deploy`
