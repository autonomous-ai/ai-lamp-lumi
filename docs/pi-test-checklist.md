# Pi Hardware Test Checklist

Track which features have been manually tested on the Raspberry Pi 4.

**Legend:** ✅ Tested & working | ❌ Tested, broken | ⏳ Not tested yet | ⚠️ Partial

---

## Infrastructure — Test trước, mọi thứ đều phụ thuộc vào đây

| # | Component | How to test | Status | Notes |
|---|---|---|---|---|
| INF-01 | LeLamp startup | SSH vào Pi, chạy `sudo systemctl status lelamp` hoặc `python server.py` trực tiếp. Expect: không có exception, log "Application startup complete" | ✅ | |
| INF-02 | Lumi startup | `sudo systemctl status lumi` hoặc chạy binary trực tiếp. Expect: log "connected to OpenClaw WebSocket" | ✅ | |
| INF-03 | LED driver | `curl -X POST http://pi:5001/led/solid -d '{"r":255,"g":100,"b":0,"brightness":80}'` → LED sáng màu cam | ✅ | |
| INF-04 | Servo driver | `curl -X POST http://pi:5001/servo/move -d '{"positions":{"tilt":90}}'` → servo tilt di chuyển | ✅ | |
| INF-05 | Audio playback | `curl -X POST http://pi:5001/voice/speak -d '{"text":"hello","language":"en"}'` → nghe thấy giọng nói qua speaker | ✅ | |
| INF-06 | Mic capture | `curl -X POST http://pi:5001/voice/start` → nói thử → `curl http://pi:5001/voice/status` xem có transcript không | ✅ | |
| INF-07 | Camera | `curl http://pi:5001/camera` → `{"available":true}`. Rồi `curl http://pi:5001/camera/snapshot -o test.jpg` → mở file xem ảnh có rõ không | ✅ | |
| INF-08 | Sensing loop | Đứng trước camera → xem log Lumi có nhận `POST /api/sensing/event` với `type:"presence.enter"` không | ⚠️ | Code có (`facerecognizer.py` → `handler.go`), chưa test thực tế trên Pi |
| INF-09 | OpenClaw WS | Xem log Lumi khi start. Expect: `[openclaw] websocket connected`. Gửi thử 1 message từ Telegram/Web UI → có response không | ✅ | |

---

## P0 — MVP Core

| # | Use Case | How to test | Status | Notes |
|---|---|---|---|---|
| UC-01 | Voice control | Nói: **"bật đèn"** → LED bật. Nói: **"tắt đèn"** → LED tắt. Nói: **"sáng hơn"** → LED tăng brightness | ✅ | |
| UC-02 | LED color via voice | Nói: **"đèn màu xanh"** → LED xanh. Nói: **"đèn vàng ấm"** → LED vàng. Nói: **"màu hoàng hôn"** → LED gradient cam-hồng | ✅ | |
| UC-14 | Voice reply (TTS + body language) | Hỏi: **"hôm nay thời tiết thế nào?"** → Lumi trả lời bằng giọng + servo cử động + LED đổi theo cảm xúc khi nói | ✅ | |

---

## P1 — Launch-critical

| # | Use Case | How to test | Status | Notes |
|---|---|---|---|---|
| UC-03 | Scene presets | Nói: **"chế độ làm việc"** → LED trắng sáng. Nói: **"thư giãn"** → LED vàng ấm tối. Nói: **"xem phim"** → LED dim amber. Nói: **"đi ngủ"** → LED tắt dần | ✅ | |
| UC-04 | Scheduling | Nói: **"30 giây nữa tắt đèn"** → đợi 30s → LED tắt. Nói: **"hủy timer"** → timer bị cancel | ✅ | |
| UC-06 | AI assistant | Nói: **"dịch hello sang tiếng Việt"** → trả lời đúng. Nói: **"thời tiết Hà Nội hôm nay"** → có thông tin thời tiết | ✅ | |
| UC-08 | Servo via voice | Nói: **"nghiêng sang trái"** → servo tilt trái. Nói: **"hướng xuống bàn"** → servo cúi xuống. Nói: **"thẳng lên"** → servo về thẳng | ⚠️ | AIM_PRESETS có 8 hướng (`presets.py`), skill-based parsing — chưa test thực tế |
| UC-11 | Presence detection | **Enter:** Rời xa rồi bước vào khung hình camera → Lumi tự chào (không cần nói gì). **Leave:** Rời khỏi tầm nhìn camera > 15 phút → đèn tự dim/tắt. **Noise check:** Ngồi yên gõ phím bình thường → Lumi không bị trigger bởi micro-movement (motion threshold tuning) | ⚠️ | `presence_service.py` + SOUL.md greet rule có đủ, chưa test thực tế trên Pi |
| UC-13 | System status LED | **Boot:** Tắt/bật Pi → quan sát LED sequence (booting → connecting → ready). **Listening:** Nói wake word → LED đổi màu báo hiệu đang nghe | ⚠️ | `statusled/service.go` có 5 states + `FlashReady()`, chưa test thực tế |

---

## Extra — Guard Mode & Stranger Tracking

| # | Use Case | How to test | Status | Notes |
|---|---|---|---|---|
| EX-01 | Guard mode enable/disable | `curl -X POST http://pi:5000/api/guard/enable` → `{"status":1}`. `curl http://pi:5000/api/guard` → `{"guard_mode":true}`. `curl -X POST http://pi:5000/api/guard/disable` → `{"guard_mode":false}` | ⏳ | |
| EX-02 | Guard mode broadcast | Bật guard mode → bước vào khung hình camera → kiểm tra tất cả Telegram DM/group nhận được cảnh báo presence.enter kèm ảnh | ⏳ | |
| EX-03 | Guard mode motion broadcast | Bật guard mode → tạo chuyển động lớn trước camera → kiểm tra Telegram nhận cảnh báo motion | ⏳ | |
| EX-04 | Guard manual alert | `curl -X POST http://pi:5000/api/guard/alert -d '{"message":"Test alert"}'` → tất cả chat session nhận message | ⏳ | |
| EX-05 | Guard mode via voice | Nói: **"bật chế độ canh gác"** hoặc **"enable guard mode"** → guard mode bật. Nói: **"tắt canh gác"** → guard mode tắt | ⏳ | Qua OpenClaw `guard` skill |
| EX-06 | Stranger stats tracking | Để stranger xuất hiện trước camera nhiều lần → `curl http://pi:5001/face/stranger-stats` → thấy count tăng, first_seen/last_seen đúng | ⏳ | LeLamp port 5001 |
| EX-07 | Stranger enrollment suggestion | Để stranger xuất hiện 3+ lần → agent gợi ý đăng ký khuôn mặt | ⏳ | Sensing skill logic |
| EX-08 | Stranger stats persistence | Restart LeLamp → `curl http://pi:5001/face/stranger-stats` → stats vẫn còn (lưu trong LeLamp data dir) | ⏳ | |

---

## Known gaps (not testing — P2+)

- UC-09: Face tracking / servo follow face — chưa implement
- UC-10: Gesture control — chưa implement
- UC-12: Video call lighting — chưa implement
- UC-15: Remote control via Telegram/Slack — chưa test end-to-end
- Face enrollment API — chưa implement (ai cũng bị classify là stranger)
