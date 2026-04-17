# Motion Activity Whitelist

Only these Kinect action classes are forwarded to OpenClaw as `motion.activity` events. All others are filtered at LeLamp level to save tokens.

Chỉ những action classes dưới đây được forward lên OpenClaw dạng `motion.activity`. Còn lại bị filter ở LeLamp để tiết kiệm token.

LeLamp groups raw action labels into 4 categories before sending to Lumi. Lumi/agent only sees the group name (`drink`, `break`, `sedentary`, `emotional`), not the raw label.

LeLamp gom raw action thành 4 nhóm trước khi gửi Lumi. Lumi/agent chỉ thấy tên nhóm, không thấy tên action gốc.

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

## sedentary — create wellbeing/music crons / Ngồi yên, tạo crons nếu chưa có

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
