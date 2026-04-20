# Motion Activity Whitelist

Only these Kinect action classes are forwarded to OpenClaw as `motion.activity` events. All others are filtered at LeLamp level to save tokens.

Chỉ những action classes dưới đây được forward lên OpenClaw dạng `motion.activity`. Còn lại bị filter ở LeLamp để tiết kiệm token.

LeLamp categorises raw action labels before sending to Lumi:
- Physical groups (`drink`, `break`, `sedentary`) — collapsed to the group name on the `Activity detected:` line. The raw label is not exposed.
- Emotional bucket (`laughing`, `crying`, `yawning`, `singing`) — sent as raw labels on a separate `Emotional cue:` line so the agent can map each to the correct emotion + mood log entry.

LeLamp phân loại raw action trước khi gửi Lumi:
- Nhóm vật lý (`drink`, `break`, `sedentary`) — gộp về tên nhóm ở dòng `Activity detected:`. Raw label không được expose.
- Nhóm cảm xúc (`laughing`, `crying`, `yawning`, `singing`) — gửi raw label ở dòng riêng `Emotional cue:` để agent map đúng emotion + log mood từng cái.

## drink — reset hydration timer / Reset timer nhắc uống nước

- drinking — uống nước
- drinking beer — uống bia
- drinking shots — uống shot
- tasting beer — nếm bia
- opening bottle — mở chai
- making tea — pha trà

## break — reset break timer / Reset timer nhắc nghỉ (ăn, vận động, tương tác)

- tasting food — nếm đồ ăn
- stretching arm — vươn tay
- stretching leg — vươn chân
- dining — ăn cơm
- eating burger, eating cake, eating carrots, eating chips, eating doughnuts, eating hotdog, eating ice cream, eating spaghetti, eating watermelon
- applauding — vỗ tay (khen)
- clapping — vỗ tay
- celebrating — ăn mừng
- sneezing — hắt xì
- sniffing — hít mũi
- hugging — ôm
- kissing — hôn
- headbanging — lắc đầu theo nhạc
- sticking tongue out — lè lưỡi

## sedentary — create wellbeing crons + trigger Music suggestion / Ngồi yên, tạo wellbeing crons + kích hoạt Music suggestion

- using computer — dùng máy tính
- writing — viết
- texting — nhắn tin
- reading book — đọc sách
- reading newspaper — đọc báo
- drawing — vẽ
- playing controller — chơi game

## emotional — always speak, log mood / Cảm xúc, luôn nói, ghi mood

- laughing — cười
- crying — khóc
- yawning — ngáp
- singing — hát
