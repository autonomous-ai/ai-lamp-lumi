# Motion Activity Whitelist

Only these Kinect action classes are forwarded to OpenClaw as `motion.activity` events. All others are filtered at LeLamp level to save tokens.

Chỉ những action classes dưới đây được forward lên OpenClaw dạng `motion.activity`. Còn lại bị filter ở LeLamp để tiết kiệm token.

LeLamp sends raw Kinetics action labels directly on the `Activity detected:` line — the agent maps them to buckets (`drink`, `break`, `sedentary`) using the Wellbeing SKILL's "Raw label → bucket" table. The group names below are documentation-only; they describe how the agent should collapse each label, not what appears on the wire.

Emotional actions (`laughing`, `crying`, `yawning`, `singing`) are filtered out on LeLamp and never appear on `motion.activity`. A dedicated `motion.emotional` event will carry them in a future version.

LeLamp gửi raw Kinetics labels trực tiếp ở dòng `Activity detected:` — agent tự map sang bucket (`drink`, `break`, `sedentary`) theo bảng "Raw label → bucket" trong Wellbeing SKILL. Tên nhóm bên dưới chỉ là doc, mô tả cách agent gom label, không phải format trên wire.

Action cảm xúc (`laughing`, `crying`, `yawning`, `singing`) bị filter ở LeLamp, không bao giờ lên `motion.activity`. Sẽ có event `motion.emotional` riêng cho nhóm này trong tương lai.

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
