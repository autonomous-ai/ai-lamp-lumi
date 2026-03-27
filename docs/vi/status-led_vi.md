# Status LED — Đặc Tả

Status LED giúp user nhìn đèn là biết Lumi đang làm gì bên trong.
Không có tín hiệu này, user không phân biệt được Lumi đang suy nghĩ, đang update, hay bị lỗi.

## Nguyên Tắc

1. **Nhìn là hiểu** — mỗi trạng thái có màu + effect riêng, không cần đoán.
2. **Không xung đột** — status LED nhường quyền cho scene/emotion do user chọn. Khi trạng thái kết thúc, ambient tự resume.
3. **Ưu tiên** — khi nhiều trạng thái active cùng lúc, trạng thái cao nhất thắng.

## Các Trạng Thái

| Trạng thái | Màu | Effect | Speed | Ưu tiên | Khi nào |
|-----------|-----|--------|-------|---------|---------|
| **Processing** | Xanh dương `(80, 140, 255)` | `pulse` | 1.0 | 1 (thấp) | Agent lifecycle `start` → `end` |
| **OTA** | Cam `(255, 140, 0)` | `breathing` | 0.4 | 2 | Bootstrap phát hiện bản update |
| **Error** | Đỏ `(255, 30, 30)` | `pulse` | 1.5 | 3 (cao) | OTA lỗi, lỗi nghiêm trọng |

### OTA chi tiết

| Giai đoạn | LED |
|----------|-----|
| Đang tải + cài | Cam breathing |
| Thành công | Flash xanh lá `(0, 255, 80)` qua `notification_flash`, rồi dừng |
| Thất bại | Đỏ pulse `(255, 30, 30)` |

## Kiến Trúc

### Lumi (lamp-server)

`internal/statusled/Service` quản lý các state active với priority map.

```
SSE handler (lifecycle start) → statusled.Set(Processing)
        ↓ agent suy nghĩ...
SSE handler (lifecycle end)   → statusled.Clear(Processing)
        ↓
ambient service resume breathing LED sau 60s im lặng
```

Service gọi LeLamp `/led/effect` qua `lib/lelamp` (shared HTTP client).

### Bootstrap (bootstrap-server)

Bootstrap là binary riêng. Gọi `lib/lelamp` trực tiếp trong hàm `reconcile`:

```
reconcile phát hiện update → lelamp.SetEffect("breathing", cam)
        ↓ cài update...
thành công → lelamp.SetEffect("notification_flash", xanh lá)
thất bại   → lelamp.SetEffect("pulse", đỏ)
```

## Tích Hợp Với Ambient

Ambient service (`internal/ambient`) tự pause khi có interaction events. Trong lúc agent processing, ambient đã pause sẵn vì voice/chat trigger pause. Khi statusled clear trạng thái processing, nó gọi `lelamp.StopEffect()`. Sau 60s im lặng, ambient resume breathing LED.

## Shared LeLamp Client

`lib/lelamp/client.go` — HTTP wrapper dùng chung cho tất cả Go code điều khiển LED:

| Function | Endpoint | Mô tả |
|----------|----------|-------|
| `SetEffect(effect, r, g, b, speed)` | `POST /led/effect` | Bật effect |
| `StopEffect()` | `POST /led/effect/stop` | Dừng effect |
| `SetSolid(r, g, b)` | `POST /led/solid` | Set màu đơn |
| `Off()` | `POST /led/off` | Tắt LED |

Tất cả gọi fire-and-forget, timeout 5s. Nếu hardware không có thì bỏ qua.

## Trải Nghiệm User

| User thấy | Lumi đang làm gì |
|-----------|------------------|
| Đèn xanh dương nhấp nháy | Lumi nghe rồi, đang suy nghĩ |
| Đèn cam thở | Lumi đang tự update (OTA) |
| Flash xanh lá | Update xong |
| Đèn đỏ nhấp nháy | Có lỗi xảy ra |
| Thở nhẹ ấm (bình thường) | Lumi idle, đang vibe |
