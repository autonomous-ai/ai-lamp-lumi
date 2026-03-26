# LED Control — Tài Liệu

## Phần Cứng

- **64 WS2812 RGB LEDs** — grid 8x5
- Driver: `rpi_ws281x` (Python, LeLamp owns)
- FastAPI endpoints trên `:5001`

## Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/led` | LED strip info (count, available) |
| GET | `/led/color` | Màu hiện tại `{"r", "g", "b"}` |
| POST | `/led/solid` | Fill toàn bộ strip 1 màu |
| POST | `/led/paint` | Set từng pixel (array tối đa 64 items) |
| POST | `/led/off` | Tắt tất cả LED |
| POST | `/led/effect` | Bật effect |
| POST | `/led/effect/stop` | Dừng effect đang chạy |

## Solid Color

```json
POST /led/solid
{"r": 255, "g": 180, "b": 100}
```

Giá trị RGB 0-255.

## Paint (Per-Pixel)

```json
POST /led/paint
{"pixels": [{"i": 0, "r": 255, "g": 0, "b": 0}, {"i": 1, "r": 0, "g": 255, "b": 0}]}
```

`i` = pixel index (0-63).

## Effects

```json
POST /led/effect
{"effect": "breathing", "r": 255, "g": 100, "b": 50, "speed": 1.0}
```

| Effect | Mô tả | Params |
|--------|-------|--------|
| `breathing` | Sine-wave brightness lên xuống | r, g, b, speed |
| `candle` | Nến lung linh ngẫu nhiên | r, g, b |
| `rainbow` | Xoay hue qua toàn bộ strip | speed |
| `notification_flash` | Flash nhanh 3 lần | r, g, b |
| `pulse` | Pulse đơn từ tâm ra ngoài | r, g, b, speed |

## Lighting Scenes

```json
POST /scene
{"scene": "reading"}
```

| Scene | Brightness | Màu | Mô tả |
|-------|-----------|-----|-------|
| `reading` | 80% | Warm white | Đọc sách |
| `focus` | 100% | Cool white | Tập trung |
| `relax` | 40% | Warm amber | Thư giãn |
| `movie` | 15% | Dim warm | Xem phim |
| `night` | 5% | Soft orange | Đèn ngủ |
| `energize` | 100% | Bright daylight | Tỉnh táo |

## Ambient Idle Behaviors

Khi Lumi idle (không có interaction):
- **Breathing LED** — sine-wave brightness, palette warm
- **Color drift** — xoay palette ấm chậm

Tự pause khi có interaction, resume sau 10s im lặng.

## LED Trong Emotion

Mỗi emotion preset có LED color riêng:

| Emotion | LED Color |
|---------|-----------|
| curious | Vàng ấm |
| happy | Vàng sáng |
| sad | Xanh dương nhạt |
| thinking | Tím nhẹ |
| idle | Warm white mờ |
| excited | Cam sáng |
| shy | Hồng nhạt |
| shock | Trắng flash |
