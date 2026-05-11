# Morning greeting route

Fires only when the routing table in `SKILL.md` picks `morning-greeting` (row #2: `first_activity_today == true`, `current_hour ∈ [5, 11)`, `morning_greeting_done_today == false`). Otherwise STOP.

## Intent

This is the user's first detected activity of the day — they're starting work. Greet warmly and ask one open question about their day plan. Sets a relational tone without lecturing.

## Phrasing rules

- One sentence, warm and casual.
- **One open-ended question** about today's plan / intent / mood. Avoid yes/no.
- Don't reference the camera ("I see you're back…"). Speak as if you simply noticed.
- Don't comment on lateness or how long they were gone — that's not the spirit.
- Match the user's language; mirror recent chat history.
- Caring or happy tone: `[HW:/emotion:{"emotion":"happy","intensity":0.5}]` (or `caring` if quieter morning).

## Templates

Vary across days. Vietnamese shown — adapt to user's language.

| Sub-mood | Examples |
|---|---|
| neutral / fresh | "Chào buổi sáng — hôm nay plan gì nè?" / "Sáng rồi, hôm nay định làm gì?" / "Good morning — what's the day looking like?" |
| weekend feel (Sat/Sun) | "Cuối tuần rồi, hôm nay tính thư giãn hay làm gì?" / "Weekend morning — anything fun planned?" |
| late morning (≥9h) | "Sáng nay khởi động hơi muộn ha — hôm nay focus cái gì?" / "Slow start today — what's the focus?" |

## Reply format

Embed the log marker alongside `[HW:/emotion:...]` (and `[HW:/dm:...]` for known users).

- **Known user** (speak + DM):
  ```
  [HW:/emotion:{"emotion":"happy","intensity":0.5}][HW:/dm:{"telegram_id":"<id>"}][HW:/wellbeing/log:{"action":"morning_greeting","notes":"<your sentence>","user":"{name}"}] <your sentence>
  ```
  `telegram_id` is in the injected `[user_info: ...]` block — never fetch.
- **Unknown user** (speak only):
  ```
  [HW:/emotion:{"emotion":"happy","intensity":0.5}][HW:/wellbeing/log:{"action":"morning_greeting","notes":"<your sentence>","user":"unknown"}] <your sentence>
  ```

The `morning_greeting` action flips `morning_greeting_done_today` to true on the next event, suppressing re-firing today.

## Follow-up

One greeting per day. If the user answers, that's a regular conversation — not gated by this skill. If they don't reply, stay silent until tomorrow.
