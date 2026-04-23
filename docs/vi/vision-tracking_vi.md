# Vision Tracking — Theo dõi vật thể bằng servo

Lumi có thể theo dõi và hướng theo bất kỳ vật thể nào mà người dùng gọi tên. Hai giai đoạn: YOLOWorld API phát hiện vật thể theo tên, TrackerVit bám theo real-time.

## Kiến trúc

```
User: "Lumi, nhìn theo cái ly đi"
         |
    POST /servo/track {"target": "cup"}
         |
    1. YOLOWorld API: frame + "cup" → bbox [x,y,w,h]  (~1-2s, RunPod GPU)
         |
    2. TrackerVit init trên bbox
         |
    3. Vòng lặp tracking @ 12 FPS
         |  lấy frame → TrackerVit update → kiểm tra confidence → pixel offset → nudge servo
         |
    4. Vật di chuyển → servo bám theo (yaw + 3 pitch joints)
         |
    5. Confidence < 0.3 trong 5 frame → tự động dừng + resume idle
```

### Phát hiện: YOLOWorld API

Phát hiện vật thể open-vocabulary — detect bất kỳ vật nào bằng tên, không giới hạn class cố định.

- **Endpoint:** `{DL_BACKEND_URL}/detect/yoloworld`
- **Auth:** header `x-api-key` từ `DL_API_KEY` config
- **Request:** `{"image_b64": "...", "classes": ["cup"]}`
- **Response:** `[{"class_name": "cup", "xywh": [cx, cy, w, h], "confidence": 0.98}]`
- **Tốc độ:** ~1-2s (RunPod GPU)

Tự động gọi khi `POST /servo/track` không có `bbox`. Có thể truyền bbox thủ công để bỏ qua detection.

### Tracking: TrackerVit

Bám theo vật thể real-time sau khi phát hiện.

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
| `confidence < 0.3` trong 5 frame | Dừng — mất target |
| Bbox > 3x kích thước ban đầu | Dừng — tracker drift/phình |
| Bbox > 50% diện tích frame | Dừng — tracker drift |
| Servo ở limit yaw/pitch + object vẫn lệch > 30% | Dừng — ngoài tầm |
| Tracking > 5 phút | Dừng — timeout tiết kiệm motor/CPU |
| Tâm bbox nhảy > 100px trong 1 frame | Bỏ qua nudge (tracker glitch, không dừng) |
| `tracker.update()` trả `ok=False` | Tính là frame confidence thấp |

## API Endpoints

Tất cả dưới `/servo/track`.

### GET /servo/track/targets — Danh sách target gợi ý

```json
{"targets": ["person", "cup", "bottle", "glass", "phone", "laptop", ...]}
```

YOLOWorld là open-vocabulary — bất kỳ text nào cũng được, danh sách chỉ là gợi ý.

### POST /servo/track — Bắt đầu tracking

```json
// Tự detect (YOLOWorld tìm vật thể)
{"target": "cup"}

// Bbox thủ công (bỏ qua detection)
{"bbox": [190, 50, 170, 300], "target": "cup"}

// Response
{"status": "ok", "tracking": true, "target": "cup", "bbox": [190, 50, 170, 300], "confidence": 1.0}
```

### POST /servo/track/stop — Dừng tracking

```json
{"status": "ok", "tracking": false}
```

### GET /servo/track — Kiểm tra trạng thái

```json
{"status": "ok", "tracking": true, "target": "ly nước", "bbox": [195, 55, 175, 295], "confidence": 0.612}
```

### POST /servo/track/update — Khởi tạo lại bbox

Re-detect thủ công mà không dừng phiên tracking.

```json
{"bbox": [250, 160, 75, 95], "target": "ly nước"}
```

Lưu ý: Re-detect tự động chạy mỗi 5 giây qua YOLOWorld — endpoint này chỉ dùng cho override thủ công.

## Luồng End-to-End

### Trường hợp thành công

```
1. User: "Lumi, nhìn theo cái ly"
2. Agent gọi POST /servo/track {"target": "cup"}
3. LeLamp nội bộ:
   a. Chụp frame hiện tại
   b. Gửi YOLOWorld API → lấy bbox (~1-2s)
   c. Lấy frame mới nhất
   d. TrackerVit init trên bbox → bắt đầu tracking
4. Servo bám theo ly nước real-time (confidence ~0.5-0.7)
5. User: "Thôi đi" → agent gọi POST /servo/track/stop
6. Servo resume idle animation
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
2. Mỗi 5 giây, tracking loop gọi YOLOWorld trong background thread
3. Nếu tìm được → TrackerVit khởi tạo lại với bbox mới
4. Sửa drift mà không gián đoạn tracking
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
- `requests` (đã có trong project)
- **YOLOWorld API** — RunPod DL backend tại `DL_BACKEND_URL/detect/yoloworld`

## Tương tác với các hệ thống khác

| Hệ thống | Khi đang tracking | Sau tracking |
|----------|-------------------|--------------|
| Servo idle animation | Bị chặn (`_hold_mode`) | Tiếp tục |
| `/servo/play` | Bị chặn bởi `_hold_mode` | Tiếp tục |
| Sensing (face, motion) | Tiếp tục — chia sẻ camera | Tiếp tục |
| Camera stream overlay | Vẽ bbox xanh lá | Stream bình thường |
| TTS | Tiếp tục bình thường | Tiếp tục bình thường |

## Bước tiếp theo

- **OpenClaw skill** — `track/SKILL.md` để agent gọi tracking bằng giọng nói
- ~~**Re-detect định kỳ**~~ — done, tự re-detect mỗi 5s trong tracking loop
- **PID control** — servo phản hồi mượt hơn thay vì chỉ proportional
- **Nhiều vật thể** — track nhiều vật, chuyển đổi giữa chúng
