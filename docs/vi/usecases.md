# AI Lamp OpenClaw — Các Trường Hợp Sử Dụng

## 1. Bối Cảnh Thị Trường

### Đèn AI khác gì Đèn Thông Minh?

| | Đèn Thông Minh | Đèn AI |
|---|---|---|
| Điều khiển | Phản hồi lệnh cụ thể ("bật đèn", "chỉnh 50%") | Hiểu ý định và ngữ cảnh ("tôi chuẩn bị đọc sách") |
| Học hỏi | Lịch trình cố định, routine thủ công | Học thói quen người dùng, tự thích nghi |
| Tương tác | Nút bấm app, từ khóa giọng nói đơn giản | Hội thoại tự nhiên, gợi ý chủ động |
| Trí tuệ | Chỉ phản ứng | Chủ động + phản ứng |
| Vai trò | Một cái đèn điều khiển từ xa | Trợ lý AI hiện diện vật lý, kiêm điều khiển đèn |

### Đối Thủ Cạnh Tranh

| Sản phẩm | Loại | Điểm khác biệt |
|---|---|---|
| Philips Hue | Hệ sinh thái đèn thông minh | Hệ sinh thái lớn nhất, Zigbee, app phong phú |
| LIFX | Bóng đèn Wi-Fi | Không cần hub, màu sắc sống động |
| Nanoleaf | Panel trang trí | Sense+ thích ứng, đồng bộ nhạc |
| Govee | LED thông minh giá rẻ | AI tạo scene từ mô tả text |
| Dyson Lightcycle | Đèn bàn cao cấp | Theo dõi nhịp sinh học, thích ứng theo tuổi |
| Xiaomi Mi Lamp | Đèn bàn thông minh | Chế độ Pomodoro, giá phải chăng |
| **AI Lamp (dự án này)** | **Đèn AI-native** | **LLM trên thiết bị, hội thoại, OpenClaw** |

### Điểm Khác Biệt Của Chúng Ta

- **LLM trên thiết bị** qua OpenClaw trên Raspberry Pi 4 — bảo mật, độ trễ thấp
- **Điều khiển hội thoại** — không chỉ từ khóa, mà ngôn ngữ tự nhiên đầy đủ
- **Mã nguồn mở** — tùy chỉnh, mở rộng, cộng đồng đóng góp
- **Trợ lý AI** — đèn là hiện thân vật lý của trợ lý AI
- **Xoay hướng cơ học** — servo motor cho phép đèn tự xoay/nghiêng, theo dõi người dùng
- **Thị giác máy tính** — camera cho phép điều khiển cử chỉ, phát hiện hiện diện, theo dõi khuôn mặt

---

## 2. Thông Số Phần Cứng

| Linh kiện | Vai trò | Khả năng |
|---|---|---|
| **Raspberry Pi 4** | Board xử lý chính | Chạy OpenClaw, lamp server, xử lý AI |
| **Microphone** | Đầu vào giọng nói | Phát hiện từ khóa đánh thức, lệnh giọng nói, hội thoại |
| **Speaker** | Đầu ra âm thanh | Phản hồi giọng nói AI, thông báo, cảnh báo |
| **Camera** | Đầu vào hình ảnh | Nhận diện cử chỉ, phát hiện hiện diện, theo dõi khuôn mặt, video call |
| **Servo Motor** | Chuyển động cơ học | Xoay/nghiêng đầu đèn, hướng ánh sáng, theo dõi người dùng |
| **LED (TBD)** | Đầu ra ánh sáng | Độ sáng, màu sắc, nhiệt độ màu |

---

## 3. Đối Tượng Người Dùng

| Phân khúc | Nhu cầu chính | Ưu tiên |
|---|---|---|
| Người đam mê công nghệ / maker | Tùy chỉnh, mã nguồn mở, sáng tạo | Cao |
| Làm việc từ xa / home office | Bảo vệ mắt, tập trung, năng suất | Cao |
| Sinh viên | Đèn bàn, công cụ tập trung, giá rẻ | Trung bình |
| Người quan tâm sức khỏe | Nhịp sinh học, chất lượng giấc ngủ | Trung bình |
| Phụ huynh (phòng trẻ em) | Routine ngủ, kể chuyện | Thấp (tương lai) |
| Người cao tuổi / hỗ trợ tiếp cận | Đơn giản, an toàn, cảnh báo bằng ánh sáng | Thấp (tương lai) |

---

## 3. Các Trường Hợp Sử Dụng

### UC-01: Điều Khiển Đèn Bằng Giọng Nói (Core)

**Người dùng**: User
**Mô tả**: Điều khiển đèn bằng ngôn ngữ tự nhiên qua OpenClaw
**Ví dụ**:
- "Bật đèn"
- "Giảm xuống 30%"
- "Sáng hơn đi"
- "Tắt đèn"

**Tiêu chí chấp nhận**:
- Phản hồi lệnh bật/tắt, điều chỉnh độ sáng (0-100%)
- Thời gian phản hồi < 1 giây từ giọng nói đến thay đổi ánh sáng
- Hỗ trợ cả tiếng Anh và tiếng Việt

---

### UC-02: Điều Khiển Màu Sắc & Nhiệt Độ Màu

**Người dùng**: User
**Mô tả**: Thay đổi màu đèn (RGB) hoặc nhiệt độ màu (trắng ấm/lạnh)
**Ví dụ**:
- "Ánh sáng ấm"
- "Chuyển sang màu xanh"
- "Nhiệt độ màu 4000K"
- "Màu cam hoàng hôn"

**Tiêu chí chấp nhận**:
- Hỗ trợ dải màu RGB (nếu phần cứng hỗ trợ)
- Hỗ trợ nhiệt độ màu (2700K - 6500K)
- Chấp nhận tên màu, mã hex, và mô tả

---

### UC-03: Chế Độ / Scene Định Sẵn

**Người dùng**: User
**Mô tả**: Kích hoạt các scene ánh sáng định sẵn hoặc do AI tạo
**Ví dụ**:
- "Chế độ đọc sách"
- "Chế độ xem phim"
- "Chế độ tập trung"
- "Chế độ thư giãn"
- "Cho tôi cảm giác buổi chiều mưa" (AI tạo)

**Các Scene Định Sẵn**:

| Scene | Độ sáng | Nhiệt độ màu | Màu |
|---|---|---|---|
| Đọc sách | 80% | 4000K (trung tính) | Trắng |
| Tập trung | 100% | 5000K (lạnh) | Trắng |
| Thư giãn | 40% | 2700K (ấm) | Trắng ấm |
| Xem phim | 15% | 2700K (ấm) | Hổ phách |
| Đêm | 5% | 2200K (rất ấm) | Ấm mờ |
| Tràn năng lượng | 100% | 6500K (ánh sáng ban ngày) | Trắng |

**Tiêu chí chấp nhận**:
- Ít nhất 6 scene định sẵn
- AI có thể tạo scene tùy chỉnh từ mô tả ngôn ngữ tự nhiên
- Chuyển đổi mượt giữa các scene (fade, không chuyển đột ngột)

---

### UC-04: Hẹn Giờ & Lịch Trình

**Người dùng**: User
**Mô tả**: Đặt hẹn giờ hoặc lịch trình cho đèn
**Ví dụ**:
- "Tắt đèn sau 30 phút"
- "Đánh thức tôi lúc 6:30 sáng với ánh sáng bình minh"
- "Giảm dần trong 20 phút"
- "Bật đèn mỗi ngày lúc 7 giờ tối"

**Tiêu chí chấp nhận**:
- Hẹn giờ một lần (tắt sau X phút)
- Lịch trình lặp lại (hàng ngày, ngày thường, cuối tuần)
- Mô phỏng bình minh (tăng dần ánh sáng ấm trong 15-30 phút)
- Mô phỏng hoàng hôn (giảm dần cho giấc ngủ)

---

### UC-05: Ánh Sáng Thích Ứng / Nhịp Sinh Học

**Người dùng**: Hệ thống (tự động)
**Mô tả**: Tự động điều chỉnh nhiệt độ màu theo thời gian trong ngày để hỗ trợ nhịp sinh học
**Hành vi**:
- Sáng (6-9h): Tăng dần lên trắng lạnh (5000-6500K) — tràn năng lượng
- Ban ngày (9-17h): Trung tính đến lạnh (4000-5000K) — tập trung
- Chiều tối (17-21h): Chuyển sang trắng ấm (3000-3500K) — thư giãn
- Đêm (21h+): Ấm mờ (2200-2700K) — chuẩn bị ngủ

**Tiêu chí chấp nhận**:
- Lịch có thể tùy chỉnh theo múi giờ người dùng
- Có thể ghi đè thủ công (ghi đè có hiệu lực đến chu kỳ tiếp theo)
- Người dùng có thể bật/tắt tính năng này

---

### UC-06: Trợ Lý AI Hội Thoại

**Người dùng**: User
**Mô tả**: Ngoài điều khiển đèn, OpenClaw hoạt động như trợ lý AI
**Ví dụ**:
- "Thời tiết hôm nay thế nào?" (và điều chỉnh đèn phù hợp)
- "Kể chuyện cười đi"
- "Mấy giờ rồi?"
- "Nhắc tôi nghỉ giải lao sau 25 phút" (Pomodoro + hiệu ứng đèn)

**Tiêu chí chấp nhận**:
- Hỏi đáp tổng quát qua khả năng LLM của OpenClaw
- Phản hồi nhận biết ngữ cảnh, có thể kích hoạt thay đổi ánh sáng
- Nhớ cuộc hội thoại trong phiên

---

### UC-07: Hiệu Ứng & Animation Ánh Sáng

**Người dùng**: User
**Mô tả**: Kích hoạt các hiệu ứng ánh sáng động
**Ví dụ**:
- "Hiệu ứng thở" (nhịp chậm)
- "Nến lung linh"
- "Cầu vồng xoay"
- "Nhấp nháy thông báo" (nháy nhanh khi có cảnh báo)
- "Pomodoro" (25 phút ánh sáng tập trung, 5 phút đổi màu nghỉ)

**Tiêu chí chấp nhận**:
- Ít nhất 5 hiệu ứng tích hợp
- Tốc độ và cường độ có thể tùy chỉnh
- Kích hoạt bằng giọng nói hoặc sự kiện hệ thống

---

### UC-08: Servo — Điều Khiển Hướng Đèn

**Người dùng**: User
**Mô tả**: Điều khiển hướng chiếu sáng vật lý bằng servo motor (xoay/nghiêng)
**Ví dụ**:
- "Chiếu sang trái"
- "Hướng xuống bàn"
- "Đèn về giữa"
- "Nghiêng lên 30 độ"

**Hành vi**:
- Xoay ngang (pan): Phạm vi 0° - 180°
- Nghiêng dọc (tilt): Phạm vi 0° - 90°
- Chuyển động mượt với tốc độ tùy chỉnh
- Trở về vị trí mặc định khi có lệnh

**Tiêu chí chấp nhận**:
- Lệnh giọng nói điều khiển hướng
- Chuyển động servo mượt, yên tĩnh (không giật)
- Vị trí đặt sẵn (bàn, tường, trần, giữa)
- Thời gian phản hồi < 500ms từ lệnh đến bắt đầu chuyển động

---

### UC-09: Servo — Tự Động Theo Dõi (Theo Người Dùng)

**Người dùng**: Hệ thống (tự động, sử dụng Camera)
**Mô tả**: Camera phát hiện vị trí khuôn mặt/cơ thể, servo motor tự động hướng đèn theo người dùng
**Chế độ**:
- **Chế độ theo dõi**: Đèn theo người dùng khi di chuyển trong tầm nhìn camera
- **Chế độ vắng mặt**: Đèn giảm sáng hoặc tắt khi không phát hiện ai
- **Chế độ spotlight**: Giữ ánh sáng tập trung vào khu vực làm việc

**Tiêu chí chấp nhận**:
- Phát hiện khuôn mặt/cơ thể qua camera với độ chính xác hợp lý
- Theo dõi mượt (không giật)
- Tốc độ và độ nhạy theo dõi có thể tùy chỉnh
- Người dùng có thể bật/tắt theo dõi
- Hoạt động trong nhiều điều kiện ánh sáng khác nhau

---

### UC-10: Camera — Điều Khiển Bằng Cử Chỉ

**Người dùng**: User
**Mô tả**: Điều khiển đèn bằng cử chỉ tay được camera phát hiện
**Cử chỉ**:
- Vẫy tay: Bật/tắt
- Lòng bàn tay lên/xuống: Tăng/giảm độ sáng
- Giơ ngón cái: Kích hoạt scene yêu thích
- Xoay tròn: Chuyển qua các scene
- Vuốt hai ngón: Thay đổi nhiệt độ màu

**Tiêu chí chấp nhận**:
- Ít nhất 5 cử chỉ được nhận diện
- Độ chính xác nhận diện > 85%
- Thời gian phản hồi < 500ms từ cử chỉ đến hành động
- Hoạt động trong khoảng cách 0.5m - 2m từ camera
- Người dùng có thể tùy chỉnh mapping cử chỉ-hành động

---

### UC-11: Camera — Phát Hiện Hiện Diện & Tự Động Hóa

**Người dùng**: Hệ thống (tự động)
**Mô tả**: Camera phát hiện có người trong phòng hay không và điều chỉnh đèn tương ứng
**Hành vi**:
- Có người vào phòng → tự bật đèn (với cài đặt gần nhất)
- Người rời phòng → giảm sáng sau 5 phút, tắt sau 15 phút (tùy chỉnh)
- Người ngủ (không chuyển động lâu) → giảm dần sang chế độ đêm
- Phát hiện nhiều người → điều chỉnh độ sáng cho nhóm

**Tiêu chí chấp nhận**:
- Phát hiện có/không có người đáng tin cậy
- Bộ đếm thời gian bật/tắt tùy chỉnh
- Chế độ riêng tư: người dùng có thể tắt camera
- Sử dụng CPU thấp (không xử lý ảnh độ phân giải cao liên tục)

---

### UC-12: Camera — Đèn Cho Video Call

**Người dùng**: User
**Mô tả**: Tối ưu ánh sáng cho cuộc gọi video bằng phản hồi từ camera
**Ví dụ**:
- "Chế độ video call"
- "Tối ưu ánh sáng cho camera"

**Hành vi**:
- Phân tích ánh sáng trên mặt người dùng qua camera
- Tự động điều chỉnh độ sáng và nhiệt độ màu cho chiếu sáng đều, đẹp
- Servo hướng đèn để giảm bóng trên mặt
- Duy trì ánh sáng ổn định trong suốt cuộc gọi

**Tiêu chí chấp nhận**:
- Phát hiện khuôn mặt và phân tích chất lượng ánh sáng
- Tự động điều chỉnh trong vòng 3 giây
- Servo định vị đèn cho chiếu sáng mặt tối ưu
- Có thể kích hoạt bằng giọng nói hoặc thủ công

---

### UC-13: Hiển Thị Trạng Thái

**Người dùng**: Hệ thống
**Mô tả**: Dùng chính ánh sáng đèn để thể hiện trạng thái hệ thống
**Các chỉ báo**:
- Đang khởi động: Nhịp xanh dương chậm
- Sẵn sàng / Đang lắng nghe: Nhấp nháy trắng ngắn
- Đang xử lý AI: Hiệu ứng thở nhẹ
- Lỗi / Mất kết nối: Nháy đỏ
- Kết nối yếu: Nhịp vàng
- Hẹn giờ đang chạy: Nhấp nháy mờ nhẹ định kỳ

**Tiêu chí chấp nhận**:
- Chỉ báo trạng thái phải tinh tế, không gây phiền
- Người dùng có thể tắt chỉ báo trạng thái
- Không được can thiệp vào ánh sáng bình thường

---

### UC-14: Điều Khiển Qua Mạng / Từ Xa (Tương Lai)

**Người dùng**: User (từ xa)
**Mô tả**: Điều khiển đèn qua mạng nội bộ hoặc internet
**Khả năng**:
- REST API cho điều khiển mạng nội bộ
- Bảng điều khiển web trên Pi
- Ứng dụng di động (cân nhắc trong tương lai)
- Tích hợp MQTT cho hệ thống nhà thông minh

**Tiêu chí chấp nhận**:
- API nội bộ hoạt động không cần internet
- Xác thực bảo mật cho truy cập từ xa
- Tài liệu API cho tích hợp bên thứ ba

---

## 4. Ma Trận Ưu Tiên

| Use Case | Ưu tiên | MVP? | Phụ thuộc phần cứng |
|---|---|---|---|
| UC-01: Điều khiển giọng nói | P0 - Quan trọng | Có | Microphone, Speaker, LED |
| UC-02: Điều khiển màu sắc | P0 - Quan trọng | Có | RGB LED / LED strip |
| UC-03: Scene định sẵn | P1 - Cao | Có | LED |
| UC-04: Hẹn giờ & lịch trình | P1 - Cao | Có | Không (phần mềm) |
| UC-05: Ánh sáng nhịp sinh học | P2 - Trung bình | Không | LED có nhiệt độ màu |
| UC-06: Trợ lý AI | P1 - Cao | Một phần | Microphone, Loa |
| UC-07: Hiệu ứng ánh sáng | P2 - Trung bình | Không | RGB LED |
| UC-08: Hướng đèn Servo | P1 - Cao | Có | Servo Motor |
| UC-09: Tự động theo dõi | P2 - Trung bình | Không | Servo Motor, Camera |
| UC-10: Điều khiển cử chỉ | P2 - Trung bình | Không | Camera |
| UC-11: Phát hiện hiện diện | P1 - Cao | Có | Camera |
| UC-12: Đèn video call | P2 - Trung bình | Không | Camera, Servo Motor |
| UC-13: Hiển thị trạng thái | P1 - Cao | Có | LED |
| UC-14: Điều khiển từ xa | P2 - Trung bình | Không | Wi-Fi/Mạng |

---

## 5. Kiến Trúc Hệ Thống (Tổng Quan)

```
                    ┌──────────────────────────────────────────┐
                    │          THIẾT BỊ ĐẦU VÀO                │
                    │  ┌─────────┐  ┌────────┐  ┌───────────┐ │
                    │  │   Mic   │  │ Camera │  │   Mạng    │ │
                    │  └────┬────┘  └───┬────┘  └─────┬─────┘ │
                    └───────┼──────────┼────────────┼─────────┘
                            │          │            │
                            ▼          ▼            ▼
                    ┌──────────────────────────────────────────┐
                    │              OpenClaw (AI/LLM)            │
                    │  ┌────────────┐  ┌─────────────────────┐ │
                    │  │ Giọng/NLU  │  │  Xử Lý Hình Ảnh    │ │
                    │  └────────────┘  └─────────────────────┘ │
                    └──────────────────┬───────────────────────┘
                                       │ WebSocket
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │           Lamp Server (Go)                │
                    │                                          │
                    │  ┌───────────┐ ┌──────────┐ ┌─────────┐ │
                    │  │ LED Ctrl  │ │  Servo   │ │  Lịch   │ │
                    │  │(GPIO/PWM) │ │  Ctrl    │ │ trình   │ │
                    │  └─────┬─────┘ └────┬─────┘ └─────────┘ │
                    │  ┌─────┴─────┐ ┌────┴─────┐ ┌─────────┐ │
                    │  │ Hiệu ứng  │ │ Theo dõi │ │Phát hiện│ │
                    │  │  Engine   │ │  Engine  │ │hiện diện│ │
                    │  └───────────┘ └──────────┘ └─────────┘ │
                    └──────┬──────────────┬───────────────────┘
                           │              │
                    ┌──────▼──────┐ ┌─────▼──────┐
                    │  LED / Đèn   │ │Servo Motor │
                    │ (Phần cứng)  │ │(Xoay/Nghiêng)│
                    └─────────────┘ └────────────┘
```

**Thiết bị đầu ra**: Loa (phản hồi giọng nói), LED (ánh sáng), Servo Motor (chuyển động)

**Luồng giao tiếp**:
1. Người dùng nói, ra cử chỉ, hoặc gửi lệnh qua mạng
2. OpenClaw xử lý đầu vào (giọng nói NLU, thị giác, hoặc API)
3. OpenClaw gửi lệnh có cấu trúc qua WebSocket đến Lamp Server
4. Lamp Server thực thi lệnh (LED, servo, lịch trình, hiệu ứng)
5. Lamp Server phản hồi trạng thái cho OpenClaw
6. OpenClaw phản hồi bằng giọng nói qua Loa

---

## 6. Yêu Cầu Phi Chức Năng

| Yêu cầu | Mục tiêu |
|---|---|
| Độ trễ phản hồi (giọng nói đến đèn) | < 1 giây |
| Thời gian khởi động | < 30 giây |
| Tiêu thụ điện (chờ) | < 5W (Pi 5 + LED idle) |
| Hoạt động offline | Điều khiển cơ bản không cần internet |
| Ngôn ngữ hỗ trợ | Tiếng Anh, Tiếng Việt |
| Nhiệt độ hoạt động | 0-45°C |
| Thời gian hoạt động | 24/7 |
