# Vision Tracking — Theo dõi vật thể bằng servo

Lumi có thể theo dõi và hướng theo bất kỳ vật thể nào mà người dùng mô tả bằng ngôn ngữ tự nhiên. Hệ thống sử dụng cách tiếp cận hybrid: LLM vision để phát hiện ban đầu, TrackerVit (ViT-based ONNX) để bám theo real-time.

## Kiến trúc

```
User: "Lumi, nhìn theo cái ly đi"
         |
    OpenClaw Agent (hiểu ý định)
         |
    1. Chụp snapshot → LLM: "Tìm cái ly, trả về bbox [x,y,w,h]"
         |
    2. POST /servo/track {bbox, target}
         |
    3. TrackerService (vòng lặp nền @ 12 FPS)
         |  lấy frame → TrackerVit update → kiểm tra confidence → pixel offset → nudge servo
         |
    4. Vật di chuyển → servo bám theo (yaw + 3 pitch joints)
         |
    5. Confidence < 0.3 trong 5 frame → tự động dừng + resume idle
```

### Tại sao hybrid?

| Cách tiếp cận | Tốc độ | Linh hoạt | Vấn đề |
|----------------|--------|-----------|--------|
| Chỉ LLM vision | ~1-2s/frame | Bất kỳ vật nào | Quá chậm để tracking |
| Chỉ YOLO/ML | ~30ms/frame | Chỉ các class cố định | Không track được "cái ly xanh bên trái" |
| **Hybrid** | **~15ms/frame** | **Bất kỳ vật nào** | — |

LLM xử lý phần "cái gì" (ngôn ngữ tự nhiên → bounding box). TrackerVit xử lý phần "ở đâu" (vị trí real-time với confidence scoring).

## Tracker: TrackerVit

**Model:** `lelamp/service/tracking/vittrack.onnx` (714KB, nằm trong repo)

| Tính năng | Giá trị |
|-----------|---------|
| Tốc độ | ~10-20ms/frame trên Pi 5 |
| Confidence score | 0.0-1.0 mỗi frame |
| Xử lý scale | Tự điều chỉnh kích thước bbox |
| Phát hiện mất | Trả `ok=False` + score thấp khi vật biến mất |

**Fallback chain:** TrackerVit → CSRT (cần opencv-contrib) → KCF → MIL

## Điều khiển Servo

Tracking sử dụng 4 trong 5 servo:
- **base_yaw** (ID 1) — quay trái/phải
- **base_pitch** (ID 2) — nghiêng lên/xuống (1/3 pitch)
- **elbow_pitch** (ID 3) — nghiêng lên/xuống (1/3 pitch)
- **wrist_pitch** (ID 5) — nghiêng lên/xuống (1/3 pitch)

Pitch được chia đều cho 3 joint để có toàn bộ range chuyển động theo chiều dọc.

**Khi đang tracking:**
- `_hold_mode = True` — chặn idle animations
- `send_action()` — ghi servo trực tiếp, không blocking (servo P-gain tự smooth)
- Theo dõi vị trí nội bộ — đọc bus 1 lần lúc bắt đầu, track delta nội bộ

**Khi dừng:** resume idle animation qua `dispatch(SERVO_CMD_PLAY, idle_recording)`.

### Chuyển đổi Pixel sang Độ

```
Tâm frame: (320, 240) cho 640x480
Tâm vật thể: (cx, cy) từ tracker bbox

dx = cx - 320   (dương = bên phải)
dy = cy - 240   (dương = bên dưới)

yaw_deg   = dx * 0.02   (cùng dấu: phải → phải)
pitch_deg = dy * 0.02   (cùng dấu: xuống → xuống)
```

### Hằng số Tuning

| Hằng số | Giá trị | Mô tả |
|---------|---------|-------|
| `DEG_PER_PX_YAW` | 0.02 | Độ mỗi pixel ngang |
| `DEG_PER_PX_PITCH` | 0.02 | Độ mỗi pixel dọc |
| `DEAD_ZONE_PX` | 15 | Bỏ qua offset nhỏ hơn giá trị này (chống rung) |
| `MAX_NUDGE_DEG` | 1.5 | Độ tối đa mỗi bước |
| `TRACK_FPS` | 12 | Tần suất vòng lặp tracking |
| `CONFIDENCE_THRESHOLD` | 0.3 | Dưới ngưỡng này = "mất" |
| `MAX_LOW_CONFIDENCE_FRAMES` | 5 | Số frame confidence thấp liên tiếp trước khi dừng |
| `BBOX_JUMP_PX` | 100 | Bỏ qua nudge nếu bbox nhảy hơn mức này |

### Giới hạn vị trí Servo

| Joint | Min | Max |
|-------|-----|-----|
| base_yaw | -135 | 135 |
| base_pitch | -90 | 30 |
| elbow_pitch | -90 | 90 |
| wrist_pitch | -90 | 90 |

## Phát hiện mất Target

TrackerVit cung cấp confidence scoring, khác với MIL/KCF chỉ drift âm thầm.

| Điều kiện | Hành động |
|-----------|-----------|
| `confidence < 0.3` trong 5 frame | Tự dừng, resume idle |
| Tâm bbox nhảy > 100px trong 1 frame | Bỏ qua nudge (tracker glitch) |
| `tracker.update()` trả `ok=False` | Tính là frame confidence thấp |

## API Endpoints

Tất cả dưới `/servo/track`.

### POST /servo/track — Bắt đầu tracking

```json
// Request
{"bbox": [190, 50, 170, 300], "target": "ly nước"}

// Response
{"status": "ok", "tracking": true, "target": "ly nước", "bbox": [190, 50, 170, 300], "confidence": 1.0}
```

### DELETE /servo/track — Dừng tracking

```json
{"status": "ok", "tracking": false}
```

### GET /servo/track — Kiểm tra trạng thái

```json
{"status": "ok", "tracking": true, "target": "ly nước", "bbox": [195, 55, 175, 295], "confidence": 0.612}
```

### PUT /servo/track — Khởi tạo lại bbox

Re-detect mà không dừng phiên tracking.

```json
{"bbox": [250, 160, 75, 95], "target": "ly nước"}
```

## Luồng End-to-End

### Trường hợp thành công

```
1. User: "Lumi, nhìn theo cái ly"
2. OpenClaw agent:
   a. Gọi /camera/snapshot → lấy frame
   b. Gửi frame cho LLM: "Tìm cái ly, trả về bounding box [x, y, w, h]"
   c. LLM trả về: [190, 50, 170, 300]
   d. Gọi POST /servo/track {"bbox": [190,50,170,300], "target": "ly nước"}
3. TrackerVit bám theo ly nước real-time (confidence ~0.5-0.7)
4. User: "Thôi đi" → agent gọi DELETE /servo/track
5. Servo resume idle animation
```

### Tự dừng khi mất

```
1. Vật rời khỏi frame hoặc bị che
2. TrackerVit confidence giảm dưới 0.3
3. Sau 5 frame confidence thấp liên tiếp → tự dừng
4. Servo resume idle animation
5. Agent có thể thông báo user hoặc tự re-detect
```

### Re-detect định kỳ (PUT)

```
1. Đang tracking nhưng bbox trôi dần (thay đổi scale, bị che 1 phần)
2. Agent chụp snapshot → LLM → bbox mới → PUT /servo/track
3. TrackerVit khởi tạo lại trên bbox mới, phiên tiếp tục
```

## Camera Stream Overlay

Khi tracking, MJPEG stream (`/camera/stream`) vẽ thêm:
- Khung xanh lá bao quanh vật thể
- Tên target phía trên khung

## Web UI

Camera section hiển thị:
- **Vision Tracking card** — input target, input bbox, nút Start/Stop/Status
- **Stream badge** — "LIVE" hoặc "TRACKING: {target}"
- **Confidence** — hiện trong panel thông tin tracking
- **Polling** — trạng thái refresh mỗi 3 giây

## Phụ thuộc

- `opencv-python>=4.8.0` (đã có trong `pyproject.toml`)
- `vittrack.onnx` — nằm trong repo tại `lelamp/service/tracking/vittrack.onnx`
- Không cần thêm package nào

## Tương tác với các hệ thống khác

| Hệ thống | Khi đang tracking | Sau tracking |
|----------|-------------------|--------------|
| Servo idle animation | Bị chặn (`_hold_mode`) | Tiếp tục |
| `/servo/play` | Bị chặn bởi `_hold_mode` | Tiếp tục |
| Sensing (face, motion) | Tiếp tục — chia sẻ camera | Tiếp tục |
| Camera stream overlay | Vẽ bbox xanh lá | Stream bình thường |
| TTS | Tiếp tục bình thường | Tiếp tục bình thường |

## Bước tiếp theo

- **LLM detect integration** — OpenClaw skill để lấy bbox từ mô tả ngôn ngữ tự nhiên
- **Re-detect định kỳ** — tự PUT mỗi N giây để sửa drift
- **PID control** — servo phản hồi mượt hơn thay vì chỉ proportional
- **Nhiều vật thể** — track nhiều vật, chuyển đổi giữa chúng
