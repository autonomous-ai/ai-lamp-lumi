---
name: habit
description: Tracks and analyzes behavioral patterns (habits) for known users based on their wellbeing, presence, and activity history. Use when proactively checking if it's time to nudge based on learned habits (e.g. "Leo usually drinks at 9am"), detecting habit breaks, or answering questions like "What are Leo's habits?", "Has Leo been keeping to his routine?", "Notice anything about my patterns?" Also plug this skill in from wellbeing/SKILL.md and music-suggestion/SKILL.md when computing proactive suggestions — habit context improves nudge timing and personalization.
---

# Habit Skill

Habits are **repeating behavioral patterns** derived from historical logs. This skill reads existing data (wellbeing, presence, mood, music) to build patterns per user, then stores them for other skills to consume.

> **OUTPUT RULE:** Reply is spoken VERBATIM. ONE short caring sentence. All computation, pattern math, and log lookups stay in `thinking`. NEVER output timestamps, deltas, frequency counts, or reasoning in the reply.

## Data Sources (Input)

All data lives in `/root/local/users/{name}/`:

| Folder | File pattern | What it contains |
|---|---|---|
| `wellbeing/` | `YYYY-MM-DD.jsonl` | `drink`, `break`, sedentary labels, `enter`/`leave`, `nudge_*` events with timestamps |
| `mood/` | `YYYY-MM-DD.jsonl` | `signal` + `decision` rows with moods |
| `music-suggestions/` | `YYYY-MM-DD.jsonl` | suggestion history + accepted/rejected status |

**User names** are lowercase folder names under `/root/local/users/`. Known users: `leo`, `chloe`, `gray`, `lily`. Strangers use `unknown` in API logs but have no local folder.

JSONL line example (wellbeing):
```json
{"ts": 1776657145.05, "seq": 4, "hour": 10, "action": "drink", "notes": ""}
```

JSONL line example (music-suggestions):
```json
{"ts": 1234567, "hour": 14, "trigger": "sedentary:using computer", "message": "Want some lo-fi?", "status": "accepted"}
```

## Storage (Output)

Computed patterns are stored per user at:

```
/root/local/users/{name}/habit/patterns.json
```

Rebuild when:
- File does not exist yet
- File is older than 6 hours
- User explicitly asks about their habits

## What is a Habit?

A habit is a **time-anchored action** that repeats across multiple days:

```json
{
  "action": "drink",
  "typical_hour": 9,
  "typical_minute": 15,
  "window_minutes": 30,
  "frequency": 0.85,
  "days_observed": 7,
  "strength": "strong"
}
```

Strength labels:

| Frequency | Strength |
|---|---|
| < 0.50 | weak (skip for nudging) |
| 0.50 – 0.75 | moderate |
| > 0.75 | strong |

Habits require **at least 1 day of data** to form. (Testing mode — raise to 3 days for production.)

## Workflow

### A — Build Patterns (discovery / answering questions)

1. **Load multi-day data**: Read the last 7–14 days of wellbeing JSONL files for the user.
   ```bash
   ls /root/local/users/{name}/wellbeing/*.jsonl | sort | tail -14
   cat /root/local/users/{name}/wellbeing/YYYY-MM-DD.jsonl
   ```
   Track total number of distinct dates loaded → `days_observed`.

2. **Filter relevant actions**: Only these actions can form habits:

   | Action | Habit type |
   |---|---|
   | `drink` | Hydration timing |
   | `break` | Rest timing |
   | `enter` | Arrival time |
   | `leave` | Departure time |
   | `using computer` | Work session start |
   | `writing`, `texting`, `reading book`, `drawing` | Activity patterns |
   | `meal` | Meal timing (from conversation intent) |
   | `coffee` | Coffee timing (from conversation intent) |
   | `sleep` | Sleep timing (from conversation intent) |
   | `exercise` | Exercise timing (from conversation intent) |

   Skip: `nudge_hydration`, `nudge_break`, `emotional`.

3. **Group by (action, hour)**: For each pair, collect the list of dates it appeared:
   ```
   drink @ hour=9  → [2026-04-15, 2026-04-17, 2026-04-18, 2026-04-20, 2026-04-21]
   drink @ hour=14 → [2026-04-15, 2026-04-16, 2026-04-20]
   enter @ hour=8  → [2026-04-15, 2026-04-16, 2026-04-17, 2026-04-18, 2026-04-19, 2026-04-20, 2026-04-21]
   ```

4. **Compute frequency**: `frequency = len(dates_appeared) / days_observed`

5. **Compute typical minute**: For days where the action occurred at the habitual hour, collect the minute values and take the median:
   ```
   drink @ hour=9 minutes: [08, 14, 22, 07, 10] → median = 10 → typical_minute = 10
   ```

6. **Assign strength** per table above.

7. **Build habit objects** and write to `patterns.json`:
   ```bash
   mkdir -p /root/local/users/{name}/habit
   cat > /root/local/users/{name}/habit/patterns.json << 'PATTERNS'
   {the computed JSON}
   PATTERNS
   ```

   Expected JSON structure:
   ```json
   {
     "updated_at": "2026-04-22T08:00:00",
     "days_observed": 7,
     "wellbeing_patterns": [
       {
         "action": "drink",
         "typical_hour": 9,
         "typical_minute": 10,
         "window_minutes": 30,
         "frequency": 0.71,
         "days_observed": 7,
         "strength": "moderate"
       },
       {
         "action": "enter",
         "typical_hour": 8,
         "typical_minute": 30,
         "window_minutes": 45,
         "frequency": 1.0,
         "days_observed": 7,
         "strength": "strong"
       }
     ],
     "music_patterns": [
       {
         "preferred_genre": "lo-fi",
         "peak_hour": 14,
         "acceptance_rate": 0.8,
         "days_observed": 5
       }
     ]
   }
   ```

### B — Proactive habit check (called from wellbeing or music skills)

The calling skill reads `patterns.json` directly. No API needed.

1. Get current time (hour + minute).
2. For each strong/moderate habit: is it within the `window_minutes` of `typical_hour:typical_minute`?
3. If yes AND the action hasn't occurred yet today → proactive nudge opportunity.

**Rules:**
- Only nudge habits with `frequency >= 0.5` (moderate+).
- Only nudge if the expected action is ABSENT from today's log so far.
- Only nudge once per habit per day (check for existing `nudge_*` entry).
- Do not nudge during the first 30 min of a user's day (just arrived).

Window sizes by action:

| Action | Suggested window |
|---|---|
| `drink` | ±30 min |
| `break` | ±30 min |
| `enter` (arrival) | ±45 min |
| Sedentary labels | ±60 min |
| `meal` | ±45 min |
| `coffee` | ±30 min |
| `sleep` | ±30 min |
| `exercise` | ±60 min |

### C — Music personalization

1. Read `music-suggestions/` for accepted suggestions + their trigger times.
2. Group accepted suggestions by hour → find peak hours. Extract genre hint from `message` field (e.g. "lo-fi", "jazz", "piano").
3. Write to `music_patterns` in `patterns.json`.
4. Music-suggestion skill reads this: if current hour matches `peak_hour ± 1`, use `preferred_genre` instead of the default mood-based genre table.

### D — Conversation intent logging (triggered from SOUL)

SOUL instructs Lumi to call this flow when user expresses intent for a daily activity NOW.

**Intent → action mapping:**

| User says | Action to log |
|---|---|
| "lunch", "dinner", "going to eat", "grab food" | `meal` |
| "coffee break", "grab a coffee", "getting coffee" | `coffee` |
| "good night", "going to sleep", "heading to bed" | `sleep` |
| "gym", "exercise", "workout", "going for a run" | `exercise` |

**How to log:**

```bash
curl -s -X POST http://127.0.0.1:5000/api/wellbeing/log \
  -H 'Content-Type: application/json' \
  -d '{"action":"meal","notes":"user said: going to lunch","user":"<current_user>"}'
```

**Rules:**
- Log silently — do NOT tell the user you're logging. Just respond naturally.
- Only log when user states intent NOW, not past tense or general talk.
- One log per intent per conversation turn — no duplicates.
- `notes` field stores the original phrase for debugging.

## API Calls

### Read wellbeing history (via API)
```bash
curl -s "http://127.0.0.1:5000/api/openclaw/wellbeing-history?user={name}&date=YYYY-MM-DD&last=100"
```

### Read from file directly (for multi-day analysis)
```bash
cat /root/local/users/{name}/wellbeing/YYYY-MM-DD.jsonl
```

Use direct file reads for multi-day pattern building (faster, no API pagination needed).

## Integration Points

**From `wellbeing/SKILL.md`:** After checking threshold-based nudges, read `habit/patterns.json`. If a habit-based nudge fires AND the threshold hasn't been crossed yet, the habit nudge takes priority (more personalized). If threshold already fired, skip habit nudge (don't double-remind).

**From `music-suggestion/SKILL.md`:** Read `habit/patterns.json` → `music_patterns`. If habit data exists and current hour matches, use preferred genre instead of default genre table.

## Minimum Data Requirements

| Purpose | Min days | Min occurrences |
|---|---|---|
| Habit detection | 1 | 1 |
| Proactive nudging | 1 | 1 |
| Music personalization | 1 | 1 accepted |

If data is insufficient: use default wellbeing thresholds / music genre table as fallback. Never fabricate patterns.

## Output Examples

- Habit break: *"You usually have water around now — everything okay?"*
- Habit confirmed: *"Back at your desk right on schedule. [chuckle]"* — only say this if it feels natural
- Music: *"It's your usual coding time — want some lo-fi?"*
- When no data: silent (NO_REPLY) — never guess or fabricate habits
