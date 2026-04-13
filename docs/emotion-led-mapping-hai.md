# Emotion → LED + Animation Mapping

Source: `lelamp/presets.py` — `EMOTION_PRESETS`

| Emotion | Color (RGB) | Hex | Effect | Speed | Servo Animation |
|---|---|---|---|---|---|
| `curious` | 255, 200, 80 | `#FFBF00` vàng ấm | breathing | 1.0 | curious |
| `happy` | 230, 51, 230 | `#FFDC00` vàng | candle | 1.0 | happy_wiggle |
| `sad` | 80, 80, 200 | `#5050C8` xanh tím | breathing | 0.8 | sad |
| `thinking` | 180, 100, 255 | `#B464FF` tím | pulse | 0.5 | thinking_deep |
| `idle` | 86, 86, 193 | `#B7EBEA` xanh nhẹ | breathing | 0.8 | idle |
| `excited` | 230, 51, 230 | `#E633E6` hồng tím | blink | 2.5 | excited |
| `shy` | 255, 150, 180 | `#FF96B4` hồng | blink | 0.5 | shy |
| `shock` | 255, 255, 255 | `#FFFFFF` trắng | notification_flash | 2.0 | shock |
| `listening` | 51, 121, 230 | `#3379E6` xanh dương | pulse | 0.6 | listening |
| `laugh` | 230, 191, 51 | `#E6BF33` vàng sáng | blink | 1.2 | laugh |
| `confused` | 224, 71, 25 | `#E04719` cam đậm | candle | 0.6 | confused |
| `sleepy` | 60, 40, 120 | `#3C2878` tím đậm | breathing | 0.5 | sleepy |
| `greeting` | 255, 180, 100 | `#FFB464` vàng nhạt | blink | 0.8 | greeting | wake_up | goodbye |
| `acknowledge` | 51, 230, 141 | `#33E68D` xanh lá | blink | 1.0 | acknowledge |
| `stretching` | 245, 240, 230 | `#F5F0E6` xanh lá nhạt | breathing | 0.6 | stretching |
| `music_strong` | 155, 221, 155 | `#9BDD9B` xanh lá nhạt | rainbow | 1.5 | music_rock |
| `music_chill` | 252, 136, 3 | `#FC8803` cam | breathing | 0.5 | music_rock | music_groove | music_jazz | music_waltz |
| `scan` | 155, 221, 155 | `#24B8E0` xanh nhạt | pulse | 1.0 | scanning |
| `nod` | 51, 230, 141 | `#33E68D` xanh lá | blink | 1.0 | nod |
| `headshake` | 230, 51, 51 | `#E63333` đỏ | blink | 1.0 | headshake |

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
