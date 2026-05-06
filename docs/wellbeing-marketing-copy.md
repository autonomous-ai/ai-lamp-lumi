# Wellbeing Skill — brief cho Marketing chỉnh copy nhắc nhở

> File này tóm tắt skill **wellbeing** (nhắc uống nước / nghỉ ngơi) và phần **habit-aware** (nhắc theo thói quen riêng) để marketing chỉnh lại lời nói của Lumi.
>
> File gốc cần chỉnh:
> - `lumi/resources/openclaw-skills/wellbeing/SKILL.md` — bảng copy chính (Step 4)
> - `lumi/resources/openclaw-skills/habit/SKILL.md` — copy habit-aware (Output Examples)

---

## 1. Mục đích

Lumi quan sát qua camera/sensor và **nhắc người dùng uống nước hoặc nghỉ ngơi** khi ngồi/làm việc lâu một chỗ. Mỗi lượt chỉ nói **1 câu ngắn**, hoặc im lặng (`NO_REPLY`) nếu chưa đến lúc.

## 2. Khi nào Lumi nhắc

Mỗi lần camera phát hiện hoạt động (`motion.activity`), Lumi tính thời gian từ lần "reset" gần nhất:

| Loại nhắc | Ngưỡng production | Reset khi |
|---|---|---|
| **Hydration** (uống nước) | 45 phút | user uống nước, mới vào phòng (`enter`), hoặc Lumi vừa nhắc xong |
| **Break** (nghỉ ngơi) | 30 phút | user đứng dậy nghỉ, mới vào phòng (`enter`), hoặc Lumi vừa nhắc xong |

- Mỗi lượt chỉ nhắc **1 thứ** — hydration ưu tiên trước break.
- Sau khi đã nhắc, đồng hồ reset → lần sau phải đợi đủ ngưỡng nữa.
- Chưa đủ ngưỡng → **im lặng**, không nói gì.

## 3. Tone & ràng buộc câu nói

- **1 câu duy nhất**, không tách 2–3 câu, không xuống dòng.
- Ấm áp, kiểu **bạn bè quan sát** — không phải robot báo động, không "thưa anh/chị".
- **Phải có dấu hỏi hoặc lời rủ hành động** ("...?", "...for a sec?") — mục tiêu là rủ user uống/nghỉ chứ không phải thông báo.
- **Bám vào hành động đang thấy** (đang dùng máy tính, đang viết, đang đọc...) cho cảm giác Lumi để ý người dùng thật.
- **Không lặp lại** — mỗi lần phải đổi cách nói, nên cần nhiều biến thể.
- Không emoji, không hashtag.

---

## 4. Bảng copy hiện tại — Wellbeing (file `wellbeing/SKILL.md` Step 4)

Lumi chọn câu dựa trên **hoạt động đang quan sát** (raw label từ camera):

| Hoạt động đang thấy | Câu nhắc nước | Câu nhắc nghỉ |
|---|---|---|
| `using computer` | *"Been at the screen — grab a glass of water?"* | *"Eyes off the screen for a sec?"* |
| `writing` | *"Pen down for some water?"* | *"Wrist break — time to stretch."* |
| `texting` | *"Phone down, water break?"* | *"Phone down — stand up for a sec?"* |
| `reading book` | *"Bookmark it and grab some water?"* | *"Been reading a while — give your eyes a rest?"* |
| `reading newspaper` | *"Page down, time for water?"* | *"Eyes need a break from the page?"* |
| `drawing` | *"Brush down, sip of water?"* | *"Hands cramping? Quick stretch."* |
| `playing controller` | *"Pause and grab some water?"* | *"Been gaming a while — stand up?"* |
| (không rõ / chung chung) | *"Been a while since you drank — grab some water?"* | *"Quick stand-up? Your back will thank you."* |

**Lưu ý:**
- Bảng này là **gợi ý**, Lumi có thể biến tấu.
- Nhiều hoạt động cùng lúc → có thể gộp, vd: *"Eyes and wrists both deserve a break."*
- Hiện copy đang **full English**. Muốn dùng tiếng Việt cần thêm cột `vi` cho từng raw label.

---

## 5. Bảng copy hiện tại — Habit-aware (file `habit/SKILL.md` Output Examples)

Khi Lumi đã học được **thói quen riêng** của user (cần ≥3 ngày dữ liệu), nó có thể chèn ngữ cảnh "thường ngày này..." vào câu nhắc, thay vì câu chung chung.

### Điều kiện kích hoạt habit-aware
- User có ≥3 ngày lịch sử wellbeing.
- Pattern đủ mạnh: `strength` = moderate (xuất hiện 50–75% số ngày) hoặc strong (>75%).
- Thời điểm hiện tại trùng khung giờ thường làm hành động đó (vd: thường uống nước lúc 9h sáng, giờ là 9:15).

Nếu không đủ điều kiện → dùng câu chung ở bảng mục 4.

### Câu nhắc enrich theo habit (khi pattern khớp)

| Tình huống | Ví dụ câu nói |
|---|---|
| **Nhắc nước theo thói quen** | *"You usually have water around now — everything okay?"* |
| **Xác nhận thói quen** (user vừa quay lại bàn đúng giờ thường lệ) | *"Back at your desk right on schedule."* (chỉ dùng nếu thấy tự nhiên) |
| **Gợi ý nhạc theo thói quen** (nếu được music skill gọi) | *"It's your usual coding time — want some lo-fi?"* |
| **Không có dữ liệu thói quen** | Im lặng — **không bịa**, không đoán mò |

### Câu trả lời khi user hỏi về thói quen mình (Flow E — open question)

Phần này dài hơn 1 câu, vì user chủ động hỏi:

| Mode | Khi dùng | Ví dụ |
|---|---|---|
| **Pattern mode** | Có ≥5 ngày data, pattern rõ | *"Leo usually arrives around 8:30 with breakfast, settles at the computer through the morning, and wraps up close to 5. Lo-fi tends to land between 2 and 4. Pretty steady the last week."* |
| **Narrative mode** | 2–4 ngày data, chưa đủ thành habit | *"I've only got two real days on Chloe so far — April 28 was an evening at the computer with a lot of water breaks, and April 29 ran late, working past midnight. Not enough days yet to call it a habit, but that's what I've seen."* |
| **Honest-gap mode** | Data cũ, lâu không gặp user | *"Honestly, I haven't seen Leo much lately — just one short session yesterday. The patterns I have are from two weeks ago, so I'd rather not pretend they're still true."* |

**Tone của Flow E:** trung thực, không phán xét, dám nói "tôi chưa biết đủ để nói chắc". Đây là khác biệt quan trọng so với câu nhắc 1-câu — ở đây Lumi kể lại quan sát.

---

## 6. Checklist khi marketing chỉnh copy

Trước khi merge bản copy mới, kiểm tra:

- [ ] Mỗi ô trong bảng vẫn là **1 câu** (không 2 câu, không xuống dòng).
- [ ] Có dấu hỏi hoặc gợi ý hành động (không phải thông báo trống "Đã đến giờ uống nước.").
- [ ] Ngôi xưng **nhất quán** với các skill khác Lumi đang dùng (hiện: bạn bè, không "anh/chị/quý khách").
- [ ] Câu **bám vào hành động** trong cột bên trái (vd cột `writing` không nên copy giống cột `using computer`).
- [ ] Có **ít nhất 2–3 biến thể** cho mỗi ô để Lumi không lặp.
- [ ] Câu habit-aware (mục 5) có yếu tố "you usually..." hoặc tương đương — đó là điểm khác biệt với câu chung.
- [ ] Nếu làm bản tiếng Việt: thêm cột `vi` ở cả 2 file, **không xoá** cột English (nhiều skill khác đang dùng English làm fallback).

---

## 7. File để chỉnh

| Nội dung | File | Vị trí trong file |
|---|---|---|
| Bảng copy chính (8 hành động × 2 loại nhắc) | `lumi/resources/openclaw-skills/wellbeing/SKILL.md` | mục **Step 4 — Speak**, dòng ~119–126 |
| Câu habit-aware enrich nudge | `lumi/resources/openclaw-skills/habit/SKILL.md` | mục **Output Examples → Nudge enrichment** |
| Câu trả lời khi user hỏi habit (3 mode) | `lumi/resources/openclaw-skills/habit/SKILL.md` | mục **Output Examples → Open habit question** |

Sau khi chỉnh, deploy lại Lumi để Pi load skill mới (hỏi dev để deploy — không tự SSH).
