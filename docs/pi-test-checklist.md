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
| INF-08 | Sensing loop | Đứng trước camera → xem log Lumi có nhận `POST /api/sensing/event` với `type:"presence.enter"` không | ⏳ | |
| INF-09 | OpenClaw WS | Xem log Lumi khi start. Expect: `[openclaw] websocket connected`. Gửi thử 1 message từ Telegram/Web UI → có response không | ✅ | |

---

## P0 — MVP Core

| # | Use Case | How to test | Status | Notes |
|---|---|---|---|---|
| UC-01 | Voice control | Nói to rõ: **"turn on the light"** → đợi. Expect: LED bật + Lumi trả lời bằng giọng. Test tiếng Việt: **"bật đèn"** | ⏳ | |
| UC-02 | LED color via voice | Nói: **"đèn màu xanh"**, **"đèn vàng ấm"**, **"màu hoàng hôn"** → LED đổi màu khớp với yêu cầu | ⏳ | |
| UC-14 | Voice reply (TTS + body language) | Hỏi bất kỳ câu gì: **"hôm nay thời tiết thế nào?"** → Lumi trả lời bằng giọng nói + servo cử động + LED đổi theo cảm xúc | ⏳ | |

---

## P1 — Launch-critical

| # | Use Case | How to test | Status | Notes |
|---|---|---|---|---|
| UC-03 | Scene presets | Nói: **"chế độ làm việc"**, **"thư giãn"**, **"xem phim"**, **"đi ngủ"**. Hoặc test trực tiếp: `curl -X POST http://pi:5001/scene -d '{"scene":"relax"}'` → LED thay đổi đúng màu/độ sáng | ⏳ | |
| UC-04 | Scheduling | Nói: **"30 giây nữa tắt đèn"** (dùng 30s để test nhanh) → đợi → LED tắt đúng giờ. Test cancel: **"hủy timer"** | ⏳ | |
| UC-06 | AI assistant | Hỏi: **"dịch hello sang tiếng Việt"**, **"thời tiết Hà Nội hôm nay"**, **"2 + 2 bằng mấy"** → OpenClaw trả lời đúng | ⏳ | |
| UC-08 | Servo via voice | Nói: **"nghiêng sang trái"**, **"hướng xuống bàn"**, **"thẳng lên"** → servo di chuyển đúng hướng. Test API: `curl -X POST http://pi:5001/servo/aim -d '{"pan":45,"tilt":30}'` | ⏳ | |
| UC-11 | Presence detection | **Test enter:** Đứng trước camera từ xa rồi bước vào khung hình → Lumi chào. **Test leave:** Rời khỏi khung hình > 15 phút → LED dim/tắt | ⏳ | |
| UC-13 | System status LED | **Boot:** Tắt/bật Pi → quan sát LED sequence (booting → connecting → ready). **Error:** Tắt WiFi → LED có báo lỗi không. **Listening:** Nói wake word → LED đổi màu "đang nghe" | ⏳ | |

---

## Known gaps (not testing — P2+)

- UC-09: Face tracking / servo follow face — chưa implement
- UC-10: Gesture control — chưa implement
- UC-12: Video call lighting — chưa implement
- UC-15: Remote control via Telegram/Slack — chưa test end-to-end
- Face enrollment API — chưa implement (ai cũng bị classify là stranger)
