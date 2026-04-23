# Vision Tracking — Theo dõi vật thể bằng servo

Lumi có thể theo dõi và hướng theo bất kỳ vật thể nào mà người dùng mô tả bằng ngôn ngữ tự nhiên. Hệ thống sử dụng cách tiếp cận hybrid: LLM vision để phát hiện ban đầu, OpenCV tracker để bám theo real-time.

## Kiến trúc

```
User: "Lumi, nhìn theo tay mình đi"
         |
    OpenClaw Agent (hiểu ý định)
         |
    1. Chụp snapshot → LLM vision → bounding box [x, y, w, h]
         |
    2. POST /servo/track {bbox, target}
         |
    3. TrackerService (vòng lặp nền @ 10 FPS)
         |  lấy frame → OpenCV CSRT update → pixel offset → nudge servo
         |
    4. Vật di chuyển → servo bám theo
         |
    5. Mất target → tự động re-detect hoặc dừng
```

### Tại sao hybrid?

| Cách tiếp cận | Tốc độ | Linh hoạt | Vấn đề |
|----------------|--------|-----------|--------|
| Chỉ LLM vision | ~1-2s/frame | Bất kỳ vật nào | Quá chậm để tracking |
| Chỉ YOLO/ML | ~30ms/frame | Chỉ các class cố định | Không track được "cái ly xanh bên trái" |
| **Hybrid** | **~100ms/frame** | **Bất kỳ vật nào** | — |

LLM xử lý phần "cái gì" (ngôn ngữ tự nhiên → bounding box). OpenCV xử lý phần "ở đâu" (vị trí real-time).

## Thành phần

### TrackerService (`lelamp/service/tracking/tracker_service.py`)

Engine tracking chính. Quản lý một phiên tracking duy nhất.

**Vòng đời:**
1. `start(bbox, target_label, camera, servo)` — khởi tạo OpenCV tracker trên bbox
2. Thread nền chạy ở `TRACK_FPS` (mặc định 10)
3. Mỗi frame: update tracker → tính offset từ tâm frame → nudge servo
4. `stop()` — kết thúc phiên, tiếp tục animation idle

**Điều khiển servo khi tracking:**
- Bật `_hold_mode = True` để chặn các animation idle/ambient
- Nudge `base_yaw` và `base_pitch` trực tiếp qua `move_to()` (bỏ qua HTTP để nhanh hơn)
- Tắt hold mode khi dừng

**Tự động dừng:** Tracker mất target trong `MAX_LOST_FRAMES` (15 frame = ~1.5s) → tự động dừng.

### Chuyển đổi Pixel sang Độ (Degree)

```
Tâm frame: (320, 240) cho 640x480
Tâm vật thể: (cx, cy) từ tracker bbox
Offset: dx = cx - 320, dy = cy - 240

yaw_degrees  = -dx * DEG_PER_PX_YAW   (mặc định 0.08 deg/px)
pitch_degrees = -dy * DEG_PER_PX_PITCH  (mặc định 0.08 deg/px)
```

**Các hằng số cần chỉnh** (đầu file `tracker_service.py`):

| Hằng số | Mặc định | Mô tả |
|---------|----------|-------|
| `DEG_PER_PX_YAW` | 0.08 | Độ mỗi pixel ngang. ~60 độ FOV / 640px |
| `DEG_PER_PX_PITCH` | 0.08 | Độ mỗi pixel dọc |
| `DEAD_ZONE_PX` | 20 | Bỏ qua offset nhỏ hơn giá trị này (chống rung) |
| `MAX_NUDGE_DEG` | 10.0 | Độ tối đa mỗi bước nudge (chống giật mạnh) |
| `TRACK_FPS` | 10 | Tần suất vòng lặp tracking |
| `MAX_LOST_FRAMES` | 15 | Số frame mất trước khi tự động dừng (~1.5s ở 10 FPS) |
| `NUDGE_DURATION` | 0.15 | Thời gian di chuyển servo mỗi bước (giây) |

Các giá trị này cần calibrate trên Pi + camera thực tế.

## API Endpoints

Tất cả dưới `/servo/track`.

### POST /servo/track — Bắt đầu tracking

```json
// Request
{
  "bbox": [200, 150, 80, 100],  // [x, y, w, h] bằng pixel trên frame 640x480
  "target": "ly nước"           // nhãn mô tả (tùy chọn)
}

// Response
{
  "status": "ok",
  "tracking": true,
  "target": "ly nước",
  "bbox": [200, 150, 80, 100]
}
```

### DELETE /servo/track — Dừng tracking

```json
// Response
{"status": "ok", "tracking": false}
```

### GET /servo/track — Kiểm tra trạng thái

```json
// Response
{
  "status": "ok",
  "tracking": true,
  "target": "ly nước",
  "bbox": [210, 155, 78, 98]  // bbox cập nhật từ frame cuối
}
```

### PUT /servo/track — Khởi tạo lại bbox

Dùng khi LLM phát hiện lại vật thể sau khi tracker mất.

```json
// Request
{
  "bbox": [250, 160, 75, 95],
  "target": "ly nước"
}
```

## Luồng End-to-End

### Trường hợp thành công

```
1. User: "Lumi, nhìn theo cái ly nước"
2. OpenClaw agent:
   a. Gọi /camera/snapshot → lấy frame
   b. Gửi frame cho LLM: "Tìm cái ly nước, trả về bounding box [x, y, w, h]"
   c. LLM trả về: [200, 150, 80, 100]
   d. Gọi POST /servo/track {"bbox": [200,150,80,100], "target": "ly nước"}
3. TrackerService bám theo ly nước real-time
4. User: "Thôi đi" → agent gọi DELETE /servo/track
```

### Re-detect khi mất target

```
1. TrackerService mất target (MAX_LOST_FRAMES đạt) → tracking dừng
2. Agent có thể:
   a. Thông báo user: "Mình mất cái ly rồi"
   b. Hoặc tự động re-detect: snapshot → LLM → bbox mới → POST /servo/track
```

### Re-detect trong khi đang tracking (PUT)

```
1. Đang tracking nhưng độ chính xác giảm dần
2. Agent chụp snapshot → LLM → bbox mới → PUT /servo/track
3. Tracker khởi tạo lại mà không dừng phiên
```

## Lựa chọn OpenCV Tracker

**Chính: CSRT** (Channel and Spatial Reliability Tracker)
- Độ chính xác tốt, xử lý được bị che 1 phần
- ~20-30ms/frame trên Pi 5
- Cần `opencv-contrib-python`

**Dự phòng: KCF** (Kernelized Correlation Filters)
- Nhanh hơn nhưng kém chính xác
- Có sẵn trong `opencv-python` cơ bản
- Tự động chọn nếu CSRT không có

## Phụ thuộc

- `opencv-python>=4.8.0` (đã có trong `pyproject.toml`)
- Cho CSRT: cần `opencv-contrib-python` (thay thế `opencv-python` trong pyproject.toml)
- Không cần thêm ML model nào

## Tương tác với các hệ thống khác

| Hệ thống | Khi đang tracking | Sau tracking |
|----------|-------------------|--------------|
| Servo idle animation | Bị chặn (`_hold_mode`) | Tiếp tục |
| Sensing (face, motion) | Tiếp tục — chia sẻ camera | Tiếp tục |
| Emotion animations | Bị chặn bởi hold mode | Tiếp tục |
| Camera freeze (snapshot) | Tracker dùng `last_frame`, không ảnh hưởng | N/A |
| TTS | Tiếp tục bình thường | Tiếp tục bình thường |

## Hướng dẫn Calibrate

Sau khi deploy lên Pi:

1. **Test vật cố định**: Đặt vật ở tâm frame. Bật tracking. Vật nên giữ nguyên ở trung tâm — servo không nên di chuyển.

2. **Test offset**: Đặt vật ở rìa frame. Servo nên nudge về phía vật. Nếu quá chậm → tăng `DEG_PER_PX_*`. Nếu vượt quá → giảm.

3. **Test di chuyển**: Từ từ di chuyển vật. Servo nên bám theo mượt. Nếu giật → tăng `NUDGE_DURATION`. Nếu lag → giảm `NUDGE_DURATION` hoặc tăng `TRACK_FPS`.

4. **Test hướng yaw**: Di chuyển vật sang phải trong frame. Servo nên quay phải. Nếu ngược → đổi dấu trong `_nudge_servo`.

5. **Test hướng pitch**: Di chuyển vật xuống dưới. Servo pitch nên nghiêng xuống. Kiểm tra dấu tương tự.

## Cải tiến trong tương lai

- **PID control** thay vì chỉ proportional nudge
- **Tracking dự đoán** — dự đoán hướng di chuyển khi vật rời khỏi rìa frame
- **Nhiều vật thể** — track nhiều vật, chuyển đổi giữa chúng
- **Ngưỡng confidence** — dùng điểm confidence của tracker để re-detect trước khi mất hoàn toàn
- **Thích ứng frame-rate** — giảm TRACK_FPS khi CPU cao, tăng khi load thấp
