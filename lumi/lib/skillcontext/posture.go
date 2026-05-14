// Posture context builder.
//
// Translates a parsed pose.ergo_risk event + the user's posture history into
// the slim semantic block the posture skill expects as `[posture_context:
// {...}]`. Mirrors the wellbeing/emotion builders in shape, but the agent
// reads raw sub-scores from the message text directly — the context here
// carries only derived booleans + labels (no numbers), per SKILL design.

package skillcontext

import (
	"encoding/json"
	"log/slog"
	"regexp"
	"strconv"
	"strings"
	"time"

	"go-lamp.autonomous.ai/lib/posture"
	"go-lamp.autonomous.ai/lib/usercanon"
)

// rePostureHeader extracts final score, risk_name, and per-side scores from the
// lelamp pose.ergo_risk message header. Body-region detail (per-side breakdown
// + angles + skipped joints) stays inline in the message text — the agent
// reads it via reading-message.md, not via this parser.
var rePostureHeader = regexp.MustCompile(
	`RULA score (\d+) \(([a-z_]+) risk\)\. Left.*?score=(\d+).*?Right.*?score=(\d+)`,
)

// ParsePostureMessage extracts the structured header fields from a
// pose.ergo_risk message text. Returns the zero value if the regex misses
// — callers should treat that as "skip context injection".
func ParsePostureMessage(msg string) PostureEvent {
	m := rePostureHeader.FindStringSubmatch(msg)
	if len(m) != 5 {
		return PostureEvent{}
	}
	score, _ := strconv.Atoi(m[1])
	left, _ := strconv.Atoi(m[3])
	right, _ := strconv.Atoi(m[4])
	return PostureEvent{
		Score:      score,
		Risk:       m[2],
		LeftScore:  left,
		RightScore: right,
	}
}

// PostureEvent is the parsed view of a single pose.ergo_risk event. Caller
// (service_events) extracts these from the lelamp message text.
type PostureEvent struct {
	Score      int    // 1..7+
	Risk       string // medium | high (negligible/low never reach here)
	LeftScore  int
	RightScore int
}

const (
	// Voice budget: max L4/L5 nudges in a rolling 1h window. SKILL drops to
	// L2/silent past this. Test value; tune after live data.
	voiceBudgetPerHour = 3
	// Praise eligibility window after a nudge.
	praiseMinAgeMin = 1
	praiseMaxAgeMin = 30
	// Repeated-in-episode window: a same-risk event within this many seconds
	// of the previous alert is "is_repeated".
	episodeWindowS = 600 // 10 min — looser than lelamp's 5min dedup
)

// postureContext is the digest the agent reads. Values are derived labels /
// booleans only — no raw scores or counts, those live in the message text.
type postureContext struct {
	Current     postureCurrent  `json:"current"`
	Session     postureSession  `json:"session"`
	Today       postureToday    `json:"today"`
	PatternsNow []string        `json:"patterns_now,omitempty"`
}

type postureCurrent struct {
	Risk          string `json:"risk"`                     // medium | high
	Asymmetric    bool   `json:"asymmetric"`               // |L - R| >= 2
	DominantSide  string `json:"dominant_side"`            // left | right | both
	Trend         string `json:"trend"`                    // worsening | stable | improving | new
}

type postureSession struct {
	IsRepeated      bool `json:"is_repeated"`       // same risk seen earlier this episode
	PraiseEligible  bool `json:"praise_eligible"`   // recent nudge + improving
	VoiceBudgetLeft bool `json:"voice_budget_left"` // < voiceBudgetPerHour L4/L5 in last hour
}

type postureToday struct {
	TimeOfDay           string `json:"time_of_day"`             // morning|noon|afternoon|evening|night
	Goal                string `json:"goal,omitempty"`          // set by morning ritual; empty otherwise
	MorningGreetingDone bool   `json:"morning_greeting_done"`
	EveningRecapDone    bool   `json:"evening_recap_done"`
}

// BuildPostureContext returns the JSON-encoded context block (without the
// `[posture_context: ]` wrapper) for injection into the agent prompt.
func BuildPostureContext(user string, ev PostureEvent) string {
	user = usercanon.Resolve(user)
	now := time.Now()
	today := now.Format("2006-01-02")
	hour := now.Hour()

	events := posture.Query(user, today, 0)

	ctx := postureContext{
		Current: postureCurrent{
			Risk:         strings.ToLower(ev.Risk),
			Asymmetric:   absInt(ev.LeftScore-ev.RightScore) >= 2,
			DominantSide: dominantSide(ev.LeftScore, ev.RightScore),
			Trend:        computeTrend(events, ev.Score),
		},
		Session: postureSession{
			IsRepeated:      isRepeatedEpisode(events, ev.Score, now),
			PraiseEligible:  praiseEligible(events, ev.Score, now),
			VoiceBudgetLeft: voiceBudgetLeft(events, now),
		},
		Today: postureToday{
			TimeOfDay:           timeOfDayBucket(hour),
			Goal:                readTodayGoal(events),
			MorningGreetingDone: postureHasActionToday(events, posture.ActionMorningRecap),
			EveningRecapDone:    postureHasActionToday(events, posture.ActionEveningRecap),
		},
		// PatternsNow: integrated with habit/patterns.json in a follow-up.
		PatternsNow: nil,
	}

	buf, err := json.Marshal(ctx)
	if err != nil {
		slog.Warn("posture: context marshal failed", "error", err)
		return "{}"
	}
	return string(buf)
}

func dominantSide(left, right int) string {
	switch {
	case left > right:
		return "left"
	case right > left:
		return "right"
	default:
		return "both"
	}
}

// computeTrend looks at the prior alert rows today and compares scores to
// the current. Returns "worsening", "stable", "improving", or "new" when
// no prior alert exists.
func computeTrend(events []posture.Event, currentScore int) string {
	for i := len(events) - 1; i >= 0; i-- {
		e := events[i]
		if e.Action != posture.ActionAlert || e.Score == 0 {
			continue
		}
		switch {
		case currentScore > e.Score:
			return "worsening"
		case currentScore < e.Score:
			return "improving"
		default:
			return "stable"
		}
	}
	return "new"
}

// isRepeatedEpisode reports whether an alert with the same risk-bucketed
// level fired within the recent episode window. Treats medium and high as
// distinct buckets so a high→medium drop is NOT "repeated".
func isRepeatedEpisode(events []posture.Event, currentScore int, now time.Time) bool {
	cutoff := float64(now.Unix() - episodeWindowS)
	currentRisk := riskBucket(currentScore)
	for i := len(events) - 1; i >= 0; i-- {
		e := events[i]
		if e.TS < cutoff {
			break
		}
		if e.Action == posture.ActionAlert && riskBucket(e.Score) == currentRisk {
			return true
		}
	}
	return false
}

// praiseEligible: a nudge was fired 1-30 min ago AND the current event has
// dropped to a lower risk bucket than the last alert. Praise gate per SKILL
// rule #1.
func praiseEligible(events []posture.Event, currentScore int, now time.Time) bool {
	nudgeTS := lastActionTS(events, posture.ActionNudge)
	if nudgeTS == 0 {
		return false
	}
	ageMin := int(now.Sub(time.Unix(int64(nudgeTS), 0)).Minutes())
	if ageMin < praiseMinAgeMin || ageMin > praiseMaxAgeMin {
		return false
	}
	// Trend must be improving — i.e. current bucket below most recent alert
	// before the praise window.
	for i := len(events) - 1; i >= 0; i-- {
		e := events[i]
		if e.Action == posture.ActionAlert && e.TS < nudgeTS {
			return riskBucket(currentScore) < riskBucket(e.Score)
		}
	}
	return false
}

// voiceBudgetLeft: count L4/L5 nudges in the last hour, allow if < budget.
func voiceBudgetLeft(events []posture.Event, now time.Time) bool {
	cutoff := float64(now.Add(-1 * time.Hour).Unix())
	count := 0
	for i := len(events) - 1; i >= 0; i-- {
		e := events[i]
		if e.TS < cutoff {
			break
		}
		if e.Action == posture.ActionNudge && e.NudgeLevel >= 4 {
			count++
		}
	}
	return count < voiceBudgetPerHour
}

// readTodayGoal scans today's morning_recap row and returns its notes (which
// the agent populates with a free-text goal string). Empty if no recap.
func readTodayGoal(events []posture.Event) string {
	for i := len(events) - 1; i >= 0; i-- {
		if events[i].Action == posture.ActionMorningRecap {
			return events[i].Notes
		}
	}
	return ""
}

func postureHasActionToday(events []posture.Event, action string) bool {
	for _, e := range events {
		if e.Action == action {
			return true
		}
	}
	return false
}

func lastActionTS(events []posture.Event, action string) float64 {
	for i := len(events) - 1; i >= 0; i-- {
		if events[i].Action == action {
			return events[i].TS
		}
	}
	return 0
}

// riskBucket maps a RULA final score to its bucket index. Matches the
// `risk_name` vocabulary used by lelamp (1=negligible, 2=low, 3=medium,
// 4=high). Lumi only ever sees buckets 3 and 4 since lelamp filters lower.
func riskBucket(score int) int {
	switch {
	case score <= 2:
		return 1
	case score <= 4:
		return 2
	case score <= 6:
		return 3
	default:
		return 4
	}
}

func timeOfDayBucket(hour int) string {
	switch {
	case hour < 5:
		return "night"
	case hour < 11:
		return "morning"
	case hour < 14:
		return "noon"
	case hour < 18:
		return "afternoon"
	case hour < 22:
		return "evening"
	default:
		return "night"
	}
}

func absInt(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
