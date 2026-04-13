# Motion Activity Whitelist

Only these Kinect action classes are forwarded to OpenClaw as `motion.activity` events. All others are filtered at LeLamp level to save tokens.

Chỉ những action classes dưới đây được forward lên OpenClaw dạng `motion.activity`. Còn lại bị filter ở LeLamp để tiết kiệm token.

## Hydration — reset hydration cron / Reset cron nhắc uống nước

- drinking — uống nước
- drinking beer — uống bia
- drinking shots — uống shot
- tasting beer — nếm bia
- tasting food — nếm đồ ăn
- opening bottle — mở chai
- making tea — pha trà

## Break — reset break cron / Reset cron nhắc nghỉ

- stretching arm — vươn tay
- stretching leg — vươn chân
- yoga
- tai chi
- exercising arm — tập tay
- push up — hít đất
- situp — gập bụng
- squat
- jogging — chạy bộ
- running on treadmill — chạy máy

## Meal — skip hydration reminder / Bữa ăn, bỏ qua nhắc nước

- dining — ăn cơm
- eating burger
- eating cake
- eating carrots
- eating chips
- eating doughnuts
- eating hotdog
- eating ice cream
- eating spaghetti
- eating watermelon

## Sedentary — context only, expect NO_REPLY / Ngồi yên, chỉ để context

- using computer — dùng máy tính
- writing — viết
- texting — nhắn tin
- reading book — đọc sách
- drawing — vẽ

## Emotional / Cảm xúc

- laughing — cười
- crying — khóc
- yawning — ngáp
- singing — hát

## Music / Nhạc cụ

- playing piano
- playing guitar
- playing drums
- playing keyboard
- playing violin
