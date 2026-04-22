# Theo dõi thói quen (Habit Tracking)

Habit tracking thêm **hành vi dự đoán** cho hệ thống wellbeing và music của Lumi. Thay vì chỉ phản ứng khi có sự kiện (nhắc theo threshold, nhạc theo mood), Lumi học thói quen cá nhân theo thời gian và hành động chủ động.

## Cách hoạt động

```
Nguồn dữ liệu (input)               Habit skill                    Consumer (output)
─────────────────────                ─────────────                  ──────────────────
Wellbeing logs (sensing)  ──┐                                      Wellbeing Step 3b
  drink, break, enter,      ├──→  Flow A: build patterns  ──→      (nhắc dự đoán)
  leave, sedentary           │       ↓
                             │    patterns.json               ──→  Music-suggestion
SOUL (conversation)     ──┘       per user                        (genre ưa thích)
  meal, coffee, sleep,
  exercise
```

## Nguồn dữ liệu

Hai nguồn độc lập cùng ghi vào wellbeing JSONL:

### 1. Dữ liệu sensing (qua Wellbeing skill)
Camera phát hiện hành động → LeLamp tự ghi vào wellbeing JSONL.

| Action | Nguồn |
|--------|-------|
| `drink` | Camera phát hiện uống nước |
| `break` | Camera phát hiện nghỉ |
| `using computer`, `writing`, `reading book`, `texting`, `drawing` | Camera phát hiện ngồi yên |
| `enter` / `leave` | Phát hiện hiện diện (backend) |

### 2. Intent từ hội thoại (qua SOUL)
User nhắc đến hoạt động hàng ngày → Lumi âm thầm ghi vào wellbeing JSONL.

| User nói | Action ghi |
|----------|------------|
| "going to lunch", "dinner" | `meal` |
| "coffee break", "grab a coffee" | `coffee` |
| "good night", "going to sleep" | `sleep` |
| "gym", "workout", "going for a run" | `exercise` |

**Quy tắc:** Chỉ ghi khi user nói intent NGAY BÂY GIỜ — không ghi quá khứ hay nói chung chung. Ghi âm thầm, Lumi trả lời tự nhiên.

## Xây dựng Pattern (Flow A)

Habit skill đọc 7–14 ngày wellbeing JSONL và tính patterns:

1. **Group** events theo `(action, hour)` qua tất cả các ngày
2. **Đếm** tần suất: `số_ngày_xuất_hiện / tổng_ngày`
3. **Tính** phút điển hình (median của phút tại giờ đó)
4. **Gán** strength: weak (<0.5), moderate (0.5–0.75), strong (>0.75)
5. **Ghi** kết quả ra `patterns.json`

### Yêu cầu dữ liệu tối thiểu

| Mục đích | Tối thiểu ngày | Tối thiểu lần |
|----------|----------------|----------------|
| Phát hiện thói quen | 3 | 2 |
| Nhắc chủ động | 5 | 3 |
| Cá nhân hóa nhạc | 3 | 2 accepted |

## Lưu trữ

File per user:
```
/root/local/users/{name}/habit/patterns.json
```

Rebuild khi:
- File chưa tồn tại
- File cũ hơn 6 giờ
- User hỏi về thói quen của mình

## Consumer

### Wellbeing — nhắc dự đoán (Step 3b)

Sau khi check threshold bình thường (uống nước > 45 min? nghỉ > 30 min?), wellbeing đọc `patterns.json`:

1. Giờ hiện tại có nằm trong `typical_hour:typical_minute ± window_minutes` không?
2. Action đã xảy ra hôm nay chưa? → bỏ qua
3. Đã nudge hôm nay chưa? → bỏ qua
4. Nếu chưa → nhắc chủ động

**Ví dụ:** Leo thường uống nước lúc 9h. 9h15 chưa thấy entry `drink` → Lumi nhắc, dù threshold chưa vượt.

### Music-suggestion — genre ưa thích (Flow C)

Trước khi chọn genre từ bảng mood mặc định, music-suggestion đọc `patterns.json → music_patterns`:

- Giờ hiện tại khớp `peak_hour ± 1` → dùng `preferred_genre`
- Không khớp → dùng bảng genre mặc định

**Ví dụ:** Leo hay chấp nhận lo-fi lúc 14:00–16:00 → lúc 14:00, suggest lo-fi thay vì chọn theo mood.

## Web Monitor

Tab Users hiện badge **habit** cho mỗi user khi `patterns.json` tồn tại. File xem được trong folder tree `habit/patterns.json`.

## Files

| File | Mục đích |
|------|----------|
| `lumi/resources/openclaw-skills/habit/SKILL.md` | Skill definition — Flow A–D, algorithm, storage |
| `lumi/internal/openclaw/resources/SOUL.md` | Section "Observing Habits" — ghi intent từ hội thoại |
| `lumi/resources/openclaw-skills/wellbeing/SKILL.md` | Step 3b — đọc patterns.json để nhắc dự đoán |
| `lumi/internal/openclaw/onboarding.go` | Đăng ký habit vào danh sách skills |
| `lelamp/models.py` | Field `habit_patterns` trong FacePersonDetail |
| `lelamp/routes/sensing.py` | Check habit/patterns.json trong face/owners API |
| `lumi/web/src/pages/monitor/FaceOwnersSection.tsx` | Habit badge + folder trong tab Users |
