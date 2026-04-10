# Emotion → LED + Animation Mapping

Source: `lelamp/presets.py` — `EMOTION_PRESETS`

| Emotion | Color (RGB) | Hex | Effect | Speed | Servo Animation |
|---|---|---|---|---|---|
| `curious` | 255, 200, 80 | `#FFC850` vàng cam | pulse | 1.2 | curious |
| `happy` | 255, 220, 0 | `#FFDC00` vàng | pulse | 1.5 | happy_wiggle |
| `sad` | 80, 80, 200 | `#5050C8` xanh tím | breathing | 0.4 | sad |
| `thinking` | 180, 100, 255 | `#B464FF` tím | pulse | 0.8 | thinking_deep |
| `idle` | 100, 200, 220 | `#64C8DC` xanh lam nhạt | breathing | 0.3 | idle |
| `excited` | 255, 100, 0 | `#FF6400` cam | rainbow | 2.5 | excited |
| `shy` | 255, 150, 180 | `#FF96B4` hồng | breathing | 0.5 | shy |
| `shock` | 255, 255, 255 | `#FFFFFF` trắng | notification_flash | 3.0 | shock |
| `listening` | 100, 180, 255 | `#64B4FF` xanh dương | breathing | 0.6 | listening |
| `laugh` | 255, 200, 50 | `#FFC832` vàng sáng | rainbow | 2.0 | laugh |
| `confused` | 200, 150, 255 | `#C896FF` tím nhạt | pulse | 0.8 | confused |
| `sleepy` | 60, 40, 120 | `#3C2878` tím đậm | breathing | 0.2 | sleepy |
| `greeting` | 255, 180, 100 | `#FFB464` cam nhạt | pulse | 1.5 | greeting |
| `acknowledge` | 100, 255, 150 | `#64FF96` xanh lá | pulse | 1.0 | acknowledge |
| `stretching` | 255, 230, 180 | `#FFE6B4` vàng kem | candle | 0.6 | stretching |

## LED Restore Behavior

- **User đã set color/effect/scene** → sau emotion, restore về màu/scene của user (kèm re-aim nếu là scene)
- **Đèn tắt hoặc chưa set** → emotion LED ở lại sau khi animation xong
- **`shock`** → restore sau 2.0s (notification_flash tự tắt sau ~1.5s)
- **`idle`** → không schedule restore (là ambient resting state)

## Scene → LED + Aim Mapping

Source: `lelamp/presets.py` — `SCENE_PRESETS`

| Scene | Color (RGB) | Brightness | Aim |
|---|---|---|---|
| `reading` | 255, 225, 180 (~4000K) | 80% | desk |
| `focus` | 235, 240, 255 (~5000K) | 100% | desk |
| `relax` | 255, 180, 100 (~2700K) | 40% | wall |
| `movie` | 255, 170, 80 (~2200K) | 15% | wall |
| `night` | 255, 140, 40 (~2200K) | 5% | down |
| `energize` | 220, 235, 255 (~6500K) | 100% | up |
