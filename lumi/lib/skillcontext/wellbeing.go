// Package skillcontext builds pre-fetched context blocks that the sensing
// handler injects into the chat message before forwarding to the agent.
//
// Saves one read tool turn per reactive event (motion.activity → wellbeing,
// emotion.detected → mood + music-suggestion). The agent reads the data
// from the prompt instead of firing GETs, eliminating the "plan reads"
// LLM-think pass between lifecycle_start and the read batch.
//
// SKILL.md keeps a fallback path: if the context block is missing
// (pre-fetch failure), the agent re-fetches via the original bash batch.
package skillcontext

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"time"

	"go-lamp.autonomous.ai/lib/usercanon"
	"go-lamp.autonomous.ai/lib/wellbeing"
)

const (
	usersDir         = "/root/local/users"
	patternsSubpath  = "habit/patterns.json"
	wellbeingSubdir  = "wellbeing"
	patternsFreshAge = 6 * time.Hour
	bootstrapMinDays = 3
)

// reactionCountActions are the user-driven reset actions the skill surfaces
// as "lần thứ N hôm nay" reaction fuel. Sedentary labels are intentionally
// excluded — counting them would explode the map and isn't useful phrasing.
var reactionCountActions = []string{"drink", "break"}

// nonActivityActions are wellbeing-log rows that don't represent a user
// motion.activity event: presence boundaries written by the backend, and
// agent-written nudge/reminder logs. Used to decide first_activity_today —
// the morning-greeting route fires on the first REAL motion event of the
// day, not on a presence.enter row that landed at wake-up.
var nonActivityActions = map[string]bool{
	"enter":            true,
	"leave":            true,
	"nudge_hydration":  true,
	"nudge_break":      true,
	"morning_greeting": true,
	"sleep_winddown":   true,
	"meal_reminder":    true,
}

// Lunch / dinner meal-reminder windows. Used by activity-router routes:
// when the current hour falls inside a window AND no meal_reminder has been
// logged in that window today, the agent fires the reminder once.
const (
	lunchWindowStartHour  = 11 // 11:30 — start offset applied in inMealWindow
	lunchWindowEndHour    = 13 // 13:30
	dinnerWindowStartHour = 18 // 18:30
	dinnerWindowEndHour   = 20 // 20:30
	morningEndHour        = 11 // morning greeting fires on first activity 5-11h
	morningStartHour      = 5
	sleepWinddownHour     = 21 // sedentary at >=21h routes to sleep wind-down
)

// wellbeingContext is the digest the agent reads. Deltas are pre-computed so
// the skill only applies thresholds; raw history is dropped from the prompt.
type wellbeingContext struct {
	HydrationDeltaMin           int                      `json:"hydration_delta_min"` // minutes since last drink/enter/nudge_hydration; -1 if no reset today
	BreakDeltaMin               int                      `json:"break_delta_min"`     // minutes since last break/enter/nudge_break;     -1 if no reset today
	LatestActivity              string                   `json:"latest_activity"`     // most recent action label (sedentary or reset); "" if no events today
	CountToday                  map[string]int           `json:"count_today,omitempty"` // count of reset actions today (drink, break); zeros omitted
	TimeOfDay                   string                   `json:"time_of_day"`         // morning|noon|afternoon|evening|night — flavors reaction phrasing
	CurrentHour                 int                      `json:"current_hour"`        // exact hour (0-23) for routing — finer than time_of_day
	FirstActivityToday          bool                     `json:"first_activity_today"` // true when no wellbeing events logged yet today (this event is the first)
	MealWindow                  string                   `json:"meal_window,omitempty"` // "lunch" | "dinner" | "" — set when current_hour is inside a meal window
	MealReminderDoneThisWindow  bool                     `json:"meal_reminder_done_this_window"` // true when a meal_reminder was already logged in the current window today
	MorningGreetingDoneToday    bool                     `json:"morning_greeting_done_today"`    // true when a morning_greeting action exists today
	SleepWinddownDoneToday      bool                     `json:"sleep_winddown_done_today"`      // true when a sleep_winddown action exists today
	Patterns                    map[string]patternDigest `json:"patterns,omitempty"`  // wellbeing_patterns from patterns.json, keyed by action ("drink"/"break")
	BootstrapNeeded             bool                     `json:"bootstrap_needed"`    // patterns missing/stale AND days >= 3 → invoke habit Flow A only when nudging
}

type patternDigest struct {
	TypicalHour   int    `json:"typical_hour"`
	TypicalMinute int    `json:"typical_minute,omitempty"`
	Strength      string `json:"strength"`
}

// BuildWellbeingContext returns a `[wellbeing_context: ...]` block for
// motion.activity events. All decision math (delta, latest activity,
// pattern lookup, bootstrap eligibility) runs here; SKILL.md only applies
// thresholds and picks phrasing.
//
// Returns "" on hard failure so the SKILL.md fallback bash batch can run.
func BuildWellbeingContext(user string) string {
	user = usercanon.Resolve(user)
	if user == "" {
		user = "unknown"
	}
	now := time.Now()
	today := now.Format("2006-01-02")

	events := wellbeing.Query(user, today, 0)
	hydrationDelta := computeDeltaMin(events, now, []string{"drink", "enter", "nudge_hydration"})
	breakDelta := computeDeltaMin(events, now, []string{"break", "enter", "nudge_break"})
	latestActivity := latestAction(events)
	countToday := countTodayActions(events, reactionCountActions)
	timeOfDay := timeOfDayLabel(now)
	currentHour := now.Hour()
	firstActivityToday := isFirstActivityToday(events)
	mealWindow := mealWindowFor(now)
	mealReminderDoneThisWindow := hasMealReminderInWindow(events, mealWindow, now)
	morningGreetingDone := hasActionToday(events, "morning_greeting")
	sleepWinddownDone := hasActionToday(events, "sleep_winddown")

	patterns, patternsFresh := readWellbeingPatterns(user)
	days := countWellbeingDays(user)
	bootstrapNeeded := !patternsFresh && days >= bootstrapMinDays

	ctx := wellbeingContext{
		HydrationDeltaMin:          hydrationDelta,
		BreakDeltaMin:              breakDelta,
		LatestActivity:             latestActivity,
		CountToday:                 countToday,
		TimeOfDay:                  timeOfDay,
		CurrentHour:                currentHour,
		FirstActivityToday:         firstActivityToday,
		MealWindow:                 mealWindow,
		MealReminderDoneThisWindow: mealReminderDoneThisWindow,
		MorningGreetingDoneToday:   morningGreetingDone,
		SleepWinddownDoneToday:     sleepWinddownDone,
		Patterns:                   patterns,
		BootstrapNeeded:            bootstrapNeeded,
	}

	body, err := json.Marshal(ctx)
	if err != nil {
		slog.Warn("wellbeing context: marshal failed", "component", "skillcontext", "error", err)
		return ""
	}
	return fmt.Sprintf("\n[wellbeing_context: %s]", string(body))
}

// computeDeltaMin returns minutes since the most recent event with an action
// in resetActions. Returns -1 when no reset event has happened today (delta
// is undefined, skill treats as "no nudge yet").
func computeDeltaMin(events []wellbeing.Event, now time.Time, resetActions []string) int {
	var latestTS float64
	for _, e := range events {
		if !contains(resetActions, e.Action) {
			continue
		}
		if e.TS > latestTS {
			latestTS = e.TS
		}
	}
	if latestTS == 0 {
		return -1
	}
	return int(now.Sub(time.Unix(int64(latestTS), 0)).Minutes())
}

// latestAction returns the action label of the most recent event today
// (regardless of whether it is a reset point).
func latestAction(events []wellbeing.Event) string {
	if len(events) == 0 {
		return ""
	}
	return events[len(events)-1].Action
}

// countTodayActions tallies how many times each tracked action appears in
// today's events. Empty entries are dropped so the JSON block stays compact
// (a missing key reads as zero).
func countTodayActions(events []wellbeing.Event, actions []string) map[string]int {
	counts := make(map[string]int, len(actions))
	for _, a := range actions {
		counts[a] = 0
	}
	for _, e := range events {
		if _, ok := counts[e.Action]; ok {
			counts[e.Action]++
		}
	}
	for k, v := range counts {
		if v == 0 {
			delete(counts, k)
		}
	}
	if len(counts) == 0 {
		return nil
	}
	return counts
}

// timeOfDayLabel buckets the hour into a coarse phrase the skill can weave
// into reactions ("cuối ngày rồi mà...", "morning kickoff..."). Boundaries
// are intentionally fuzzy — exact hour is in the patterns block when needed.
func timeOfDayLabel(now time.Time) string {
	switch h := now.Hour(); {
	case h >= 5 && h < 11:
		return "morning"
	case h >= 11 && h < 13:
		return "noon"
	case h >= 13 && h < 18:
		return "afternoon"
	case h >= 18 && h < 22:
		return "evening"
	default:
		return "night"
	}
}

// mealWindowFor returns "lunch" or "dinner" when now falls inside the
// respective meal-reminder window, or "" otherwise. Windows are
// minute-precise (lunch 11:30-13:30, dinner 18:30-20:30).
func mealWindowFor(now time.Time) string {
	mins := now.Hour()*60 + now.Minute()
	switch {
	case mins >= lunchWindowStartHour*60+30 && mins < (lunchWindowEndHour+0)*60+30:
		return "lunch"
	case mins >= dinnerWindowStartHour*60+30 && mins < (dinnerWindowEndHour+0)*60+30:
		return "dinner"
	default:
		return ""
	}
}

// hasMealReminderInWindow returns true when a meal_reminder action was
// already logged today inside the same named window. Used to suppress
// re-firing the same meal reminder.
func hasMealReminderInWindow(events []wellbeing.Event, window string, now time.Time) bool {
	if window == "" {
		return false
	}
	for _, e := range events {
		if e.Action != "meal_reminder" {
			continue
		}
		ts := time.Unix(int64(e.TS), 0).In(now.Location())
		if mealWindowFor(ts) == window {
			return true
		}
	}
	return false
}

// hasActionToday returns true when any event in today's events has the given
// action label. Used by morning_greeting and sleep_winddown one-per-day gates.
func hasActionToday(events []wellbeing.Event, action string) bool {
	for _, e := range events {
		if e.Action == action {
			return true
		}
	}
	return false
}

// isFirstActivityToday returns true when no prior REAL user activity event
// has been logged today. Presence boundaries (enter/leave) and agent-written
// nudge/reminder rows don't count — they're not motion.activity events.
func isFirstActivityToday(events []wellbeing.Event) bool {
	for _, e := range events {
		if !nonActivityActions[e.Action] {
			return false
		}
	}
	return true
}

func contains(haystack []string, needle string) bool {
	for _, s := range haystack {
		if s == needle {
			return true
		}
	}
	return false
}

// readWellbeingPatterns parses patterns.json and returns the wellbeing_patterns
// subset, keyed by action. The second return value is true when the file is
// fresh (mtime < patternsFreshAge); false → stale or missing.
func readWellbeingPatterns(user string) (map[string]patternDigest, bool) {
	path := filepath.Join(usersDir, user, patternsSubpath)
	info, err := os.Stat(path)
	if err != nil {
		return nil, false
	}
	if time.Since(info.ModTime()) >= patternsFreshAge {
		return nil, false
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	var raw struct {
		WellbeingPatterns []struct {
			Action        string `json:"action"`
			TypicalHour   int    `json:"typical_hour"`
			TypicalMinute int    `json:"typical_minute"`
			Strength      string `json:"strength"`
		} `json:"wellbeing_patterns"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, true // file is fresh but malformed; skip patterns, no need to bootstrap
	}
	out := make(map[string]patternDigest, len(raw.WellbeingPatterns))
	for _, p := range raw.WellbeingPatterns {
		// Only surface "moderate" or "strong" — weak patterns add noise to
		// phrasing without changing decisions.
		if p.Strength != "moderate" && p.Strength != "strong" {
			continue
		}
		out[strings.ToLower(p.Action)] = patternDigest{
			TypicalHour:   p.TypicalHour,
			TypicalMinute: p.TypicalMinute,
			Strength:      p.Strength,
		}
	}
	return out, true
}

// countWellbeingDays counts per-day wellbeing JSONL files for habit bootstrap
// eligibility (Flow A requires >=3 days).
func countWellbeingDays(user string) int {
	dir := filepath.Join(usersDir, user, wellbeingSubdir)
	entries, err := os.ReadDir(dir)
	if err != nil {
		return 0
	}
	n := 0
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".jsonl") {
			n++
		}
	}
	return n
}
