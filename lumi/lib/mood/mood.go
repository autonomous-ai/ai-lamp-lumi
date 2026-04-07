// Package mood provides a dedicated mood history logger for music suggestion.
//
// Logs mood-relevant sensing events (presence, wellbeing, light, sound) to daily
// JSONL files separate from the flow log. The music suggestion skill queries this
// history to build a mood picture for reactive suggestions.
//
// Usage:
//
//	mood.Init()                           // once at startup
//	mood.Log("wellbeing.break", 45, "User sitting 45 min")  // log a mood-relevant event
//	events := mood.Query("2026-04-07", 100) // query history
package mood

import (
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// Event is one mood history record persisted to JSONL.
type Event struct {
	TS          float64 `json:"ts"`                     // Unix seconds
	Seq         int64   `json:"seq"`                    // global sequence
	Event       string  `json:"event"`                  // sensing event type (e.g. "wellbeing.break")
	PresenceMin int     `json:"presence_min,omitempty"` // minutes since presence started
	Hour        int     `json:"hour"`                   // hour of day (0-23) for time-of-day context
	Message     string  `json:"message,omitempty"`      // brief description
}

const (
	logsDir       = "local"
	filePrefix    = "mood_"
	fileSuffix    = ".jsonl"
	retentionDays = 30
)

// mood-relevant sensing event types
var moodEvents = map[string]bool{
	"presence.enter":       true,
	"presence.leave":       true,
	"presence.away":        true,
	"wellbeing.hydration":  true,
	"wellbeing.break":      true,
	"wellbeing.music":      true,
	"light.level":          true,
	"sound":                true,
	"motion.activity":      true,
}

type logger struct {
	mu   sync.Mutex
	seqN atomic.Int64
	file *os.File
	day  string
}

var global = &logger{}

// Init creates the logs directory and cleans old mood files.
// Call once at startup.
func Init() {
	_ = os.MkdirAll(logsDir, 0o755)
	go cleanOldLogs()
}

// IsMoodEvent returns true if the event type is mood-relevant and should be logged.
func IsMoodEvent(eventType string) bool {
	return moodEvents[eventType]
}

// Log records a mood-relevant sensing event.
// presenceMin is the minutes since presence started (0 if unknown).
func Log(eventType string, presenceMin int, message string) {
	if !moodEvents[eventType] {
		return
	}

	now := time.Now()
	seq := global.seqN.Add(1)

	evt := Event{
		TS:          float64(now.UnixNano()) / 1e9,
		Seq:         seq,
		Event:       eventType,
		PresenceMin: presenceMin,
		Hour:        now.Hour(),
		Message:     message,
	}

	global.mu.Lock()
	global.writeJSONL(now, evt)
	global.mu.Unlock()
}

// Query reads mood events for a given day (YYYY-MM-DD format).
// Returns up to last n events. If n <= 0, returns all.
func Query(day string, n int) []Event {
	path := filepath.Join(logsDir, filePrefix+day+fileSuffix)
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}

	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) == 0 || (len(lines) == 1 && lines[0] == "") {
		return nil
	}

	// Take last n lines
	if n > 0 && len(lines) > n {
		lines = lines[len(lines)-n:]
	}

	events := make([]Event, 0, len(lines))
	for _, line := range lines {
		if line == "" {
			continue
		}
		var evt Event
		if err := json.Unmarshal([]byte(line), &evt); err == nil {
			events = append(events, evt)
		}
	}
	return events
}

// writeJSONL appends the event to the current day's JSONL file.
// Must be called with mu held.
func (l *logger) writeJSONL(now time.Time, evt Event) {
	day := now.Format("2006-01-02")
	if l.day != day || l.file == nil {
		if l.file != nil {
			_ = l.file.Close()
		}
		name := filepath.Join(logsDir, filePrefix+day+fileSuffix)
		f, err := os.OpenFile(name, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			return
		}
		l.file = f
		l.day = day
	}
	b, _ := json.Marshal(evt)
	_, _ = l.file.Write(append(b, '\n'))
}

func cleanOldLogs() {
	entries, err := os.ReadDir(logsDir)
	if err != nil {
		return
	}
	cutoff := time.Now().AddDate(0, 0, -retentionDays).Format("2006-01-02")
	for _, e := range entries {
		name := e.Name()
		if !strings.HasPrefix(name, filePrefix) || !strings.HasSuffix(name, fileSuffix) {
			continue
		}
		date := strings.TrimSuffix(strings.TrimPrefix(name, filePrefix), fileSuffix)
		if date < cutoff {
			path := filepath.Join(logsDir, name)
			if err := os.Remove(path); err == nil {
				slog.Info("removed old mood log", "component", "mood", "file", name)
			}
		}
	}
}
