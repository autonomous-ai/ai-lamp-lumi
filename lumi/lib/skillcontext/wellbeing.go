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
	usersDir          = "/root/local/users"
	patternsSubpath   = "habit/patterns.json"
	wellbeingSubdir   = "wellbeing"
	patternsFreshAge  = 6 * time.Hour
	wellbeingHistoryN = 50
	bootstrapMinDays  = 3
)

// wellbeingContext is the digest the agent reads. Deltas are pre-computed so
// the skill only applies thresholds; raw history is dropped from the prompt.
type wellbeingContext struct {
	HydrationDeltaMin int                      `json:"hydration_delta_min"` // minutes since last drink/enter/nudge_hydration; -1 if no reset today
	BreakDeltaMin     int                      `json:"break_delta_min"`     // minutes since last break/enter/nudge_break;     -1 if no reset today
	LatestActivity    string                   `json:"latest_activity"`     // most recent action label (sedentary or reset); "" if no events today
	Patterns          map[string]patternDigest `json:"patterns,omitempty"`  // wellbeing_patterns from patterns.json, keyed by action ("drink"/"break")
	BootstrapNeeded   bool                     `json:"bootstrap_needed"`    // patterns missing/stale AND days >= 3 → invoke habit Flow A only when nudging
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

	events := wellbeing.Query(user, today, wellbeingHistoryN)
	hydrationDelta := computeDeltaMin(events, now, []string{"drink", "enter", "nudge_hydration"})
	breakDelta := computeDeltaMin(events, now, []string{"break", "enter", "nudge_break"})
	latestActivity := latestAction(events)

	patterns, patternsFresh := readWellbeingPatterns(user)
	days := countWellbeingDays(user)
	bootstrapNeeded := !patternsFresh && days >= bootstrapMinDays

	ctx := wellbeingContext{
		HydrationDeltaMin: hydrationDelta,
		BreakDeltaMin:     breakDelta,
		LatestActivity:    latestActivity,
		Patterns:          patterns,
		BootstrapNeeded:   bootstrapNeeded,
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
