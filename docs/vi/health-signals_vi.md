# Health Signals — Hướng dẫn đèn trạng thái

Lumi sử dụng đèn LED breathing để thông báo trạng thái thiết bị. Mỗi trạng thái có màu riêng để người dùng nhận biết nhanh.

## Bảng tín hiệu LED

| Màu LED | Hiệu ứng | Ý nghĩa | Khi nào | Tự tắt |
|---------|----------|---------|---------|--------|
| Cyan `(0,200,200)` | Breathing nhanh | **Agent Down** — AI brain mất kết nối | OpenClaw WebSocket ngắt | Có — khi agent kết nối lại |
| Tím `(180,0,255)` | Breathing nhanh | **LeLamp Down** — Server phần cứng không phản hồi | LeLamp process crash hoặc đang restart | Có — khi LeLamp phản hồi lại |
| Cam `(255,80,0)` | Breathing nhanh | **Mất internet** — Wi-Fi kết nối nhưng không có internet | 5 lần ping thất bại liên tiếp (~25s) | Có — khi có internet lại |
| Xanh dương `(0,80,255)` | Breathing nhanh | **Đang khởi động** — Lumi đang bật | Bật nguồn, khởi động lại | Có — khi khởi động xong |
| Xanh lá `(0,255,0)` | Breathing nhanh | **Đang cập nhật** — OTA firmware đang cập nhật | Bootstrap phát hiện firmware mới | Có — khi cập nhật xong (khởi động lại) |
| Đỏ `(255,0,0)` | Breathing nhanh | **Lỗi** — Lỗi hệ thống | Lỗi nghiêm trọng | Có — khi lỗi được khắc phục |

## Ưu tiên

Khi nhiều trạng thái cùng hoạt động, trạng thái ưu tiên cao nhất được hiển thị:

```
Error (cao nhất) > OTA > Booting > Connectivity > LeLamp Down > Agent Down (thấp nhất)
```

Ví dụ: nếu mất internet VÀ agent down, **Mất internet** (cam) được hiển thị vì ưu tiên cao hơn.

## Chi tiết hành vi

### Agent Down (Cyan)
- Kích hoạt khi OpenClaw WebSocket mất kết nối
- Tắt khi WebSocket kết nối lại thành công
- Voice command và AI features không khả dụng; LED scene và servo vẫn hoạt động
- TTS thông báo "Brain reconnected!" khi phục hồi

### LeLamp Down (Tím)
- Kích hoạt khi LeLamp server (port 5001) không phản hồi
- Health watcher poll mỗi 5 giây; LED bật ngay lần thất bại đầu tiên
- Tắt ngay khi LeLamp phản hồi /health
- TTS thông báo "Hardware recovered!" khi phục hồi
- LED, servo, camera, mic, speaker không khả dụng khi LeLamp down

### Mất internet (Cam)
- Network service ping mỗi 5 giây
- Sau 5 lần thất bại liên tiếp (~25 giây), LED chuyển cam
- Tắt ngay khi ping thành công
- Lumi vẫn hoạt động local nhưng cloud features không khả dụng

### Đang khởi động (Xanh dương)
- Kích hoạt khi bật nguồn, trước khi agent sẵn sàng
- Tắt khi OpenClaw agent kết nối và sẵn sàng nhận lệnh
- Một flash trắng ngắn báo hiệu khởi động xong

### Đang cập nhật OTA (Xanh lá)
- Kích hoạt khi bootstrap phát hiện phiên bản firmware mới
- Giữ trong suốt quá trình download và cài đặt
- Thiết bị khởi động lại sau cập nhật — LED chuyển sang Booting (xanh dương)

### Lỗi (Đỏ)
- Kích hoạt khi có lỗi hệ thống nghiêm trọng
- Tắt khi lỗi được khắc phục

## Hoạt động bình thường

Khi không có trạng thái nào, LED được điều khiển bởi:
1. **Emotion preset** — màu theo cảm xúc của AI agent
2. **Scene preset** — scene chiếu sáng do người dùng chọn (reading, focus, relax, v.v.)
3. **Ambient breathing** — breathing nhẹ màu ấm khi rảnh

Đèn trạng thái **ghi đè** tất cả các LED trên khi hoạt động. Khi trạng thái tắt, LED tự động quay về hành vi bình thường.
