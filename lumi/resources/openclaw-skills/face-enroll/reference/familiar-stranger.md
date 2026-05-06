# Flow C — Familiar-stranger prompt (lelamp surfaces the hint)

LeLamp tracks how often each `stranger_id` is seen. When the visit count first reaches `_FAMILIAR_VISIT_THRESHOLD` (=2), lelamp:

1. Saves the current raw frame to `<STRANGERS_DIR>/snapshots/<stranger_id>_<ts_ms>.jpg`.
2. Appends a hint to the outgoing `presence.enter` message:

```
(familiar stranger <stranger_id> — seen <N> times, ask user if they want to remember this face; image saved at <path>)
```

This is the ONE exception to the "self-enrollment only" rule — the user may name a face the camera saw, because lelamp explicitly invites them to.

## Trigger
- The current sensing message contains the hint pattern above.
- The user replies to your prompt with a name ("yes, that's Alice", "her name is Alice", just "Alice").
- The user declines ("no", "skip", "ignore") — acknowledge and stop.

## Steps

1. Parse `<stranger_id>` and `<path>` from the hint.
2. **Ask the user** in a single natural message — do NOT enroll yet:
   - EN: "I've seen this person {N} times now — want me to remember them? If yes, what's their name?"
   - VI: "Mình đã thấy người này {N} lần rồi — bạn muốn mình ghi nhớ họ không? Nếu có thì tên họ là gì?"
3. Wait for the user's next reply.
4. **If the user gives a name** (with or without "yes"):
   - Lowercase the name → `label`.
   - Base64-encode the file at `<path>`.
   - Call `POST /face/enroll` with `image_base64`, `label`. **Omit `telegram_username` and `telegram_id`** — the named person is not the sender.
   - Confirm: "Got it, I'll remember {Name} from now on."
5. **If the user declines** ("no" / "skip" / "ignore"): acknowledge once ("Okay, I won't ask about this person again.") and stop. LeLamp will not re-prompt for the same `stranger_id` (the threshold fires only once per id).
6. **If the user is ambiguous** ("maybe later", silence-ish reply): treat as decline.

## One-shot rule
The lelamp hint surfaces exactly once per stranger when the count first reaches the threshold. Don't re-ask in later turns even if you see the same `stranger_id` again — only act on the hint when it appears in the current sensing message. Visit counts above the threshold do not re-fire.

## Example

```
[sensing] Person detected — 1 face(s) visible (stranger (stranger_37)) (familiar stranger stranger_37 — seen 2 times, ask user if they want to remember this face; image saved at /root/local/strangers/snapshots/stranger_37_1735...jpg)

Agent (turn 1):
  Reply: "Mình đã thấy người này 2 lần rồi — bạn có muốn mình nhớ họ không? Nếu có thì tên họ là gì?"

User (turn 2): "Ừ, đó là Alice."

Agent (turn 2):
  → POST /face/enroll {"image_base64": "<base64 of /root/.../stranger_37_1735...jpg>", "label": "alice"}
  → confirm: "Rồi, mình sẽ nhớ Alice từ giờ."
```
