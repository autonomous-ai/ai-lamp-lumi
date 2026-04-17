// Package wellbeing provides a per-user activity history logger.
//
// Logs user activity groups observed from motion.activity events
// (drink, break, sedentary, emotional). Agent posts one entry per
// observed activity with optional free-text notes.
//
// Usage:
//
//	wellbeing.Init()                                    // once at startup
//	wellbeing.LogForUser("gray", "drink", "3rd today")  // append entry
//	events := wellbeing.Query("gray", "2026-04-17", 100)
package wellbeing

import (
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// Event is one wellbeing activity record persisted to JSONL.
type Event struct {
	TS     float64 `json:"ts"`     // Unix seconds
	Seq    int64   `json:"seq"`    // global sequence
	Hour   int     `json:"hour"`   // hour of day (0-23)
	Action string  `json:"action"` // drink, break, sedentary, emotional
	Notes  string  `json:"notes"`  // optional agent observation
}

const (
	usersDir         = "/root/local/users"
	wellbeingSubdir  = "wellbeing"
	fileSuffix       = ".jsonl"
	DefaultUser      = "unknown"
	maxNormalizedLen = 64
)

var reNonLabel = regexp.MustCompile(`[^a-z0-9_-]+`)

type logger struct {
	mu   sync.Mutex
	seqN atomic.Int64
	file *os.File
	day  string
	user string
}

var global = &logger{}

// Init creates the users directory. Call once at startup.
func Init() {
	_ = os.MkdirAll(usersDir, 0o755)
}

// NormalizeUser lowercases, replaces non [a-z0-9_-] with _, strips _,
// caps at 64 chars. Mirrors the Python facerecognizer.normalize_label
// so Go-written paths match Python-written paths.
func NormalizeUser(name string) string {
	s := strings.ToLower(strings.TrimSpace(name))
	s = reNonLabel.ReplaceAllString(s, "_")
	s = strings.Trim(s, "_")
	if len(s) > maxNormalizedLen {
		s = s[:maxNormalizedLen]
	}
	if s == "" {
		return DefaultUser
	}
	return s
}

// LogForUser appends an activity entry for the given user.
func LogForUser(user, action, notes string) {
	user = NormalizeUser(user)
	now := time.Now()
	seq := global.seqN.Add(1)

	evt := Event{
		TS:     float64(now.UnixNano()) / 1e9,
		Seq:    seq,
		Hour:   now.Hour(),
		Action: action,
		Notes:  notes,
	}

	global.mu.Lock()
	global.writeJSONL(now, user, evt)
	global.mu.Unlock()
}

// Query reads wellbeing events for a given user and day (YYYY-MM-DD).
// Returns up to last n events. If n <= 0, returns all.
func Query(user, day string, n int) []Event {
	user = NormalizeUser(user)
	path := filePath(user, day)
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}

	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) == 0 || (len(lines) == 1 && lines[0] == "") {
		return nil
	}

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

func filePath(user, day string) string {
	return filepath.Join(usersDir, user, wellbeingSubdir, day+fileSuffix)
}

// writeJSONL appends the event to the user's daily JSONL file.
// Must be called with mu held.
func (l *logger) writeJSONL(now time.Time, user string, evt Event) {
	day := now.Format("2006-01-02")

	if l.day != day || l.user != user || l.file == nil {
		if l.file != nil {
			_ = l.file.Close()
		}
		path := filePath(user, day)
		_ = os.MkdirAll(filepath.Dir(path), 0o755)
		f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			slog.Error("wellbeing: failed to open log file", "path", path, "error", err)
			l.file = nil
			return
		}
		l.file = f
		l.day = day
		l.user = user
	}
	b, _ := json.Marshal(evt)
	_, _ = l.file.Write(append(b, '\n'))
}
