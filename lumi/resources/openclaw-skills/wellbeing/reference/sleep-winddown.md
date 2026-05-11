# Sleep wind-down route

Fires only when the routing table in `SKILL.md` picks `sleep-winddown` (row #3: `current_hour >= 21`, sedentary labels (no `drink`/`break`), `sleep_winddown_done_today == false`). Otherwise STOP.

## Intent

Late evening: instead of pushing a break nudge (which implies "get back to work after"), gently suggest **winding down for sleep**. Don't moralize, don't say "you should sleep" — just plant the seed.

## Phrasing rules

- One sentence, soft, low-energy.
- Acknowledge the late hour without scolding.
- **No work-related ask.** Don't suggest stretching to keep going. The point is "wrap up", not "reset".
- Don't reference the camera or detection.
- Caring tone: `[HW:/emotion:{"emotion":"caring","intensity":0.4}]` (lower intensity than mid-day — quieter).
- Match the user's language.

## Templates

Vary across nights. Vietnamese shown — adapt to user's language.

| Hour | Examples |
|---|---|
| 21–22h | "Khuya rồi đó, cân nhắc gác máy sớm nha." / "Late already — easing into wind-down soon?" |
| 22–23h | "Sắp 11h rồi, để mai làm tiếp cũng được mà." / "Getting close to bedtime — tomorrow's still there." |
| ≥23h | "Quá khuya rồi đó, ngủ thôi." / "It's really late — time to call it." |

## Reply format

Embed the log marker alongside `[HW:/emotion:...]`.

- **Known user** (speak + DM):
  ```
  [HW:/emotion:{"emotion":"caring","intensity":0.4}][HW:/dm:{"telegram_id":"<id>"}][HW:/wellbeing/log:{"action":"sleep_winddown","notes":"<your sentence>","user":"{name}"}] <your sentence>
  ```
  `telegram_id` is in the injected `[user_info: ...]` block — never fetch.
- **Unknown user** (speak only):
  ```
  [HW:/emotion:{"emotion":"caring","intensity":0.4}][HW:/wellbeing/log:{"action":"sleep_winddown","notes":"<your sentence>","user":"unknown"}] <your sentence>
  ```

The `sleep_winddown` action flips `sleep_winddown_done_today` to true on the next event, suppressing re-firing tonight.

## Follow-up

One wind-down per night. After firing, defer to silence for the rest of the evening — don't keep nudging.
