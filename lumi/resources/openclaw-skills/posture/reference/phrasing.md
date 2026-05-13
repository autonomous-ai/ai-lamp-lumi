# Posture phrasing

Tables show **tone**, not scripts. Paraphrase every turn — a canned-feeling loop
is the exact failure mode this file exists to prevent.

Examples are written for Vietnamese audience since that is the default user;
match whatever language the user spoke this session.

## What you actually know per event

From the message: final `score`, `risk` (`medium` or `high` only — others
filtered upstream), per-side scores, per-region sub-scores + 4 angles, optional
`[skipped: ...]` joints.

From `[posture_context]`: `asymmetric` / `dominant_side` / `trend`,
`is_repeated` / `praise_eligible` / `voice_budget_left`, `today.goal`,
`patterns_now`, `last_offender_named`.

Decode the message into region labels via `reading-message.md` BEFORE
phrasing. The per-region tables below assume those labels are in hand.

Phrasing leans on:

1. **Region label** (`neck_flexed`, `wrist_deviated`, …) — what to name
2. **Asymmetry** (`dominant_side`) — adds side prefix on arm regions
3. **Trend** (`worsening` / `stable` / `improving`) — sets tone
4. **Session context** (`is_repeated`, `praise_eligible`) — sets warmth/firmness

Body-region facts come from decoding the message via `reading-message.md`. The
tables below use the **semantic labels** that decoder produces (e.g.
`neck_flexed`, `wrist_deviated`) — match them to phrasing.

## Per-region tone (paraphrase — never copy verbatim)

The decoder in `reading-message.md` reduces each event to 1-2 region labels. Look
them up here for an L4 one-liner or L5 short coaching. The L5 structure
(observation + action [+ why] [+ warmth]) lives further down — these are just
the *body* of the line.

### Neck

| Label | L4 one-liner | L5 body |
|---|---|---|
| `neck_flexed` (cúi rõ, score 3+) | *"Cổ kìa."* | *"Cổ đang cúi một lúc rồi. Ngẩng lên, mắt nhìn ngang màn hình — đầu mình nặng hơn mình tưởng."* |
| `neck_extended` (ngửa, angle âm) | *"Cổ ngửa quá."* | *"Đang ngửa cổ ra sau lâu nhỉ. Hạ màn hình xuống một chút hoặc dịch ghế gần lại — đỡ căng cơ cổ sau."* |
| `neck_twisted` (score 4+, angle thấp) | *"Cổ vặn rồi."* | *"Cổ đang vẹo sang một bên khá lâu. Xoay nguyên ghế cho thẳng với màn hình — vặn cổ mãi không tốt cho đốt sống cổ."* |
| `neck_flexed_mild` (score 2-3, không phải dominant) | (skip) | (skip) |

### Trunk

| Label | L4 one-liner | L5 body |
|---|---|---|
| `trunk_flexed` (gập 20-60°) | *"Lưng kìa."* | *"Đang chúi cả người về phía trước. Đẩy ghế sát bàn hơn, dựa lưng vào — lưng cứ thế lâu là chiều đau thắt lưng."* |
| `trunk_bent_low` (gập >60°) | *"Gập sâu lắm."* | *"Đang gập hẳn xuống rồi. Đứng dậy duỗi 10 giây — gập sâu vầy lâu là cột sống chịu không nổi."* |
| `trunk_twisted` (score 3+, angle thấp) | *"Vặn người kìa."* | *"Người đang xoắn — nhìn hai màn hình hả? Xoay nguyên ghế thay vì xoắn eo, đỡ vặn cột sống."* |
| `trunk_flexed_mild` (score 2-3, không dominant) | (skip) | (skip) |

### Upper arm

| Label | L4 one-liner | L5 body |
|---|---|---|
| `upper_arm_flexed` (45-90°) | *"Khuỷu cao kìa."* | *"Khuỷu đang mở rộng ra xa người. Kéo bàn phím gần lại hoặc hạ khuỷu xuống sát hông — vai mới đỡ phải gồng."* |
| `upper_arm_raised` (>90°) | *"Tay giơ cao."* | *"Tay đang giơ lên quá cao rồi. Thở ra, thả vai xuống — vai cứ thế lâu là mai đau gáy đó."* |
| `upper_arm_extended` (ngửa sau >20°) | *"Tay ra sau xa."* | *"Cánh tay đang ngửa ra sau lâu. Đặt tay gần người hơn nha."* |
| `upper_arm_flexed_mild` (20-45°) | (skip) | (skip) |

### Lower arm

| Label | L4 one-liner | L5 body |
|---|---|---|
| `lower_arm_strained` (góc <60° hoặc >100°) | *"Cẳng tay căng."* | *"Cẳng tay đang duỗi/gập quá mức. Hạ bàn phím hoặc kéo ghế lại — góc khuỷu tầm 90° là êm nhất."* |

### Wrist

| Label | L4 one-liner | L5 body |
|---|---|---|
| `wrist_deviated` (score 3) | *"Cổ tay lệch."* | *"Cổ tay đang lệch sang một bên. Đặt chuột ngay trước vai, đừng để xa hông — lệch trục lâu mỏi gân lắm."* |
| `wrist_strained` (score 4+) | *"Cổ tay căng."* | *"Cổ tay đang gập hoặc ngửa quá. Nâng kê tay lên hoặc hạ ghế thấp xuống một bậc — gập cổ tay lâu là đường tắt đến hội chứng ống cổ tay."* |

### Multi-region (>1 label fires)

Pick top region by sub-score (decoder rule). If tied and both are equally
fresh in conversation, blend in **one** sentence — don't list them as bullets:

- `neck_flexed` + `wrist_deviated`: *"Cổ với cổ tay đang căng cùng lúc. Ngồi thẳng, đặt chuột thẳng tay lại — hai cái này hay đi chung."*
- `trunk_flexed` + `upper_arm_raised`: *"Đang chúi người với tay nâng cao — chắc đang với cái gì xa quá. Kéo lại gần, ngồi thẳng nha."*

### Side prefix (when `asymmetric == true`)

Prepend the dominant side to arm/wrist labels only (neck/trunk are bilateral):

| `dominant_side` | Prefix template | Example |
|---|---|---|
| `right` | *"Tay phải..."* / *"Bên phải..."* | *"Tay phải đang lệch kìa."* |
| `left` | *"Bên trái..."* / *"Tay trái..."* | *"Bên trái chống cằm hả? Hạ tay xuống."* |
| `both` | (no prefix — symmetric) | *"Cổ tay lệch kìa."* |

## L5 — coaching sentence (2-4 sentences)

Trigger: `current.risk == "high"` (score ≥ 7).

Structure to build the line:

1. **Observation** (soft) — opener that names the region from per-region table.
2. **Concrete action** (doable in 5 sec) — the second clause from per-region L5 body.
3. *(Optional)* **Why** — the consequence from per-region L5 body.
4. *(Optional)* **Warmth** — *"Một chút thôi, không cần dừng việc."* / *"Lát quay lại tiếp."*

Skip steps 3 and/or 4 if you used them in either of the last 2 nudges. Variety > completeness.

When `asymmetric == true`, prepend the side prefix per the table above. When
multiple regions trigger, use the multi-region row instead of stacking two
sentences.

## L4 — one short line

Trigger: `current.risk == "medium"` AND `is_repeated == true`.

Use the L4 one-liner from the per-region table for the dominant offender. With
asymmetry, prepend side: *"Tay phải lệch kìa."* / *"Bên trái nghiêng rồi."*

Never repeat the same opener twice in one session. Track `last_offender_named`
from context to diverge.

## L3 — servo only

No words. Servo plays `posture_correct` gesture. The log row carries `nudge_level=3`.

## L2 — chime only

No words. Soft chime via audio. Log row carries `nudge_level=2`.

## L1 — LED only

Owned by lelamp side. No event reaches the agent — nothing to phrase.

## Praise (rare, earned)

Trigger: `praise_eligible == true` in context — last nudge was 1-30 min ago AND
risk has dropped (e.g. `high` → `medium`). If user recovered fully, no event
fires and praise is silent by design.

Short, warm, never over-celebrating. 1 sentence max.

- *"Đó. Giữ vậy nha."*
- *"Ngon — vai thả xuống nhìn dễ chịu liền."*
- *"Thấy bạn chỉnh rồi đó. Đỡ ghê."*
- *"Tay đỡ căng rồi. Tốt."*

**Anti-patterns — never:**

- Praise without a prior nudge (drive-by compliment is creepy).
- Quantify (*"score giảm từ 6 xuống 3"* — sounds like a tracker).
- Praise twice within 30 min — feels patronizing.

## Asymmetry phrasing rules

When `asymmetric == true`, you have the most-specific signal available — use it.

| Dominant side | Likely cause (educated guess, do not state) | Phrasing angle |
|---|---|---|
| `"right"` | Mouse arm overworked / leaning on right elbow | *"tay phải đang gánh nặng"*, *"tay phải cứng dần đó"* |
| `"left"` | Chin rested on left hand / left-handed mouse | *"bên trái đang lệch hơn"*, *"chống cằm bên trái lâu lắm rồi"* |
| `"both"` (equal) | Whole-body posture issue (neck/trunk) | Speak about posture as a whole, not arms |

Do NOT state the cause as fact — phrase as a question or possibility:

- ✅ *"Tay phải chắc đang dùng chuột nhiều à?"*
- ❌ *"Bạn đang dùng chuột quá nhiều, tay phải bị lệch trục."*

## Trend phrasing

| Trend | Tone | Example angle |
|---|---|---|
| `worsening` | Light urgency, not panic | *"Đang xấu dần rồi — chỉnh sớm trước khi mỏi luôn nhé."* |
| `stable` | Matter-of-fact, observation | *"Vẫn dáng đó từ nãy giờ. Đổi tư thế thử."* |
| `improving` | Praise (see Praise section) | *"Đỡ rồi đó."* |
| `new` (first alert of episode) | Gentle entry | *"Tư thế bắt đầu lệch nha — sớm thôi mà."* |

## Pre-emptive (pattern-aware)

When `patterns[*].peak_hour` is within ±30 min of `today.current_hour` AND
`current.risk == "medium"` AND `is_repeated == false` (a fresh episode), you can nudge BEFORE it gets worse:

- *"Sắp 15h — giờ này mọi hôm bạn xuống dáng. Ngồi thẳng từ đầu xem có đỡ không."*
- *"Buổi chiều tay phải bạn hay cứng. Duỗi nhẹ một xíu nha."*

Use sparingly — at most one pre-emptive nudge per pattern per day. Frame as
"mọi hôm" or "thường" — never quote the exact time from data.

## Today-goal awareness

If `today.goal` is non-empty AND set by morning ritual, you can reference it
once per day at the right moment:

- After an improvement that crosses the goal threshold:
  *"Đó — đúng mục tiêu sáng đặt rồi đó. Giữ vậy hết chiều thử."*
- When risk rises despite a goal:
  *"Hôm nay đặt mục tiêu ≤4 chiều mà giờ đang 6 nè. Không trách đâu — chỉnh một xíu vẫn kịp."*

Never frame as pass/fail. Goals are aspirations, not contracts.

## Cross-skill phrasing (combine with wellbeing signals)

If the same turn has BOTH:

- A `[posture_context]` showing risk, AND
- A `[wellbeing_context]` showing the user has been sedentary > 60 min OR hasn't drunk in > 45 min

Then merge into **one** spoken line, not two separate nudges. Examples:

- *"Đứng lên duỗi xíu — vừa thẳng lưng vừa lấy cốc nước, một công đôi việc."*
- *"Tư thế cứng rồi đây. Có break thì đứng dậy đi vài bước, máu chạy đỡ tê tay."*

Cross-skill phrasing wins over single-skill: fewer interruptions, more value.
Wellbeing owns food/drink phrasing; posture owns body-mechanics phrasing.

## Health framing (medical-safety reminder)

Even though the event itself does not name a disease, the agent may be tempted
to mention conditions to motivate the user. Rules:

- ✅ *"giữ vầy lâu mai mỏi vai gáy"* — symptom + timing, no diagnosis
- ✅ *"cổ tay đỡ một lực mãi không tốt"* — body region + general consequence
- ❌ *"bạn bị tech neck rồi"* — never name a condition as a fact
- ❌ *"có nguy cơ hội chứng ống cổ tay"* — even framed as risk, this names a specific medical condition

The hedge tail lelamp appends — *"camera-based posture assessment; treat as a
gentle nudge, not a diagnosis"* — is the contract. Stay within it.

## Anti-patterns — never

- **Inventing body parts.** Without offender data, do NOT say *"cổ cúi"* unless `asymmetric == false` AND the score implies a whole-body issue — and even then prefer general phrasing.
- **Quoting raw numbers** — *"score 6"*, *"RULA 5/6"*, *"left 4 right 6"* — round, paraphrase, or omit. The user does not care about the number.
- **Cop voice** — *"Tôi đang quan sát…"*, *"Hệ thống phát hiện…"*. Coach voice is friendly, not clinical.
- **Naming the framework** — never say "RULA", "ergo score", "pose estimation". User doesn't care.
- **Stacking warnings** — pick max 3 signals from {asymmetry, trend, today.goal, pattern}.
- **Repeating the last opener** — even if the same risk level is detected back-to-back.
- **Praising without a fix** — only after a confirmed improvement.
- **Lecturing on ergonomics** — give one fact max, never a paragraph.
