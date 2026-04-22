# Habit Tracking

Habit tracking adds **predictive behavior** to Lumi's wellbeing and music systems. Instead of only reacting to events (threshold nudges, mood-based music), Lumi learns personal patterns over time and acts proactively.

## How It Works

```
Data sources (input)                  Habit skill                    Consumers (output)
─────────────────────                ─────────────                  ──────────────────
Wellbeing logs (sensing)  ──┐                                      Wellbeing Step 3b
  drink, break, enter,      ├──→  Flow A: build patterns  ──→      (predictive nudge)
  leave, sedentary           │       ↓
                             │    patterns.json               ──→  Music-suggestion
SOUL (conversation)     ──┘       per user                        (preferred genre)
  meal, coffee, sleep,
  exercise
```

## Data Sources

Two independent inputs feed into the same wellbeing JSONL logs:

### 1. Sensing data (via Wellbeing skill)
Camera detects physical actions → LeLamp logs to wellbeing JSONL automatically.

| Action | Source |
|--------|--------|
| `drink` | Camera activity detection |
| `break` | Camera activity detection |
| `using computer`, `writing`, `reading book`, `texting`, `drawing` | Camera sedentary detection |
| `enter` / `leave` | Presence detection (backend) |

### 2. Conversation intent (via SOUL)
User mentions daily activity in conversation → Lumi silently logs to wellbeing JSONL.

| User says | Action logged |
|-----------|---------------|
| "going to lunch", "dinner" | `meal` |
| "coffee break", "grab a coffee" | `coffee` |
| "good night", "going to sleep" | `sleep` |
| "gym", "workout", "going for a run" | `exercise` |

**Rule:** Only logs when user states intent NOW — not past tense or general discussion. Logging is silent; Lumi responds naturally without mentioning it.

## Pattern Building (Flow A)

The habit skill reads 7–14 days of wellbeing JSONL and computes patterns:

1. **Group** events by `(action, hour)` across all days
2. **Count** frequency: `days_appeared / days_observed`
3. **Compute** typical minute (median of minute values at that hour)
4. **Assign** strength: weak (<0.5), moderate (0.5–0.75), strong (>0.75)
5. **Write** results to `patterns.json`

### Minimum data requirements

| Purpose | Min days | Min occurrences |
|---------|----------|-----------------|
| Habit detection | 3 | 2 |
| Proactive nudging | 5 | 3 |
| Music personalization | 3 | 2 accepted |

## Storage

Per-user file:
```
/root/local/users/{name}/habit/patterns.json
```

Rebuilt when:
- File does not exist
- File is older than 6 hours
- User explicitly asks about their habits

### Example patterns.json

```json
{
  "updated_at": "2026-04-22T10:01:00",
  "days_observed": 3,
  "wellbeing_patterns": [
    {
      "action": "meal",
      "typical_hour": 9,
      "typical_minute": 30,
      "window_minutes": 45,
      "frequency": 0.67,
      "days_observed": 3,
      "strength": "moderate"
    },
    {
      "action": "enter",
      "typical_hour": 8,
      "typical_minute": 30,
      "window_minutes": 45,
      "frequency": 0.67,
      "days_observed": 3,
      "strength": "moderate"
    }
  ],
  "music_patterns": [
    {
      "preferred_genre": "lofi hip hop",
      "peak_hour": 14,
      "acceptance_rate": 0.8,
      "days_observed": 5
    }
  ]
}
```

## Consumers

### Wellbeing — predictive nudging (Step 3b)

After the normal threshold check (drink > 45 min? break > 30 min?), wellbeing reads `patterns.json`:

1. Is the current time within a habit's `typical_hour:typical_minute ± window_minutes`?
2. Has the action already occurred today? → skip
3. Has a nudge already been logged today? → skip
4. If not → proactive nudge

**Example:** Leo usually drinks water at 9am. At 9:15 with no `drink` entry today, Lumi nudges — even if the hydration threshold hasn't been crossed yet.

Rules:
- Only nudge moderate+ habits (frequency ≥ 0.5)
- No double-nudge if threshold already fired
- Skip first 30 min of user's day

### Music-suggestion — personal genre preference (Flow C)

Before picking a genre from the default mood table, music-suggestion reads `patterns.json → music_patterns`:

- If current hour matches `peak_hour ± 1` → use `preferred_genre`
- Otherwise → fall back to default genre table

**Example:** Leo usually accepts lo-fi between 14:00–16:00 → at 14:00, suggest lo-fi instead of generic mood-based pick.

## Window Sizes

| Action | Window |
|--------|--------|
| `drink` | ±30 min |
| `break` | ±30 min |
| `meal` | ±45 min |
| `coffee` | ±30 min |
| `sleep` | ±30 min |
| `exercise` | ±60 min |
| `enter` (arrival) | ±45 min |
| Sedentary labels | ±60 min |

## Web Monitor

The Users tab shows a **habit** badge per user when `patterns.json` exists. The file is viewable in the folder tree under `habit/patterns.json`.

## Files

| File | Purpose |
|------|---------|
| `lumi/resources/openclaw-skills/habit/SKILL.md` | Skill definition — Flows A–D, algorithm, storage |
| `lumi/internal/openclaw/resources/SOUL.md` | "Observing Habits" section — conversation intent logging |
| `lumi/resources/openclaw-skills/wellbeing/SKILL.md` | Step 3b — reads patterns.json for predictive nudge |
| `lumi/internal/openclaw/onboarding.go` | Registers habit in skills list |
| `lelamp/models.py` | `habit_patterns` field in FacePersonDetail |
| `lelamp/routes/sensing.py` | Checks habit/patterns.json in face/owners API |
| `lumi/web/src/pages/monitor/FaceOwnersSection.tsx` | Habit badge + folder in Users tab |
