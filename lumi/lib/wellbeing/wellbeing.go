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
	Action string  `json:"action"` // drink, break, sedentary, emotional, enter, leave
	Notes  string  `json:"notes"`  // optional agent observation
}

const (
	usersDir         = "/root/local/users"
	wellbeingSubdir  = "wellbeing"
	fileSuffix       = ".jsonl"
	DefaultUser      = "unknown"
	maxNormalizedLen = 64
	retentionDays    = 7
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

// Init creates the users directory and starts the retention cleaner.
// Call once at startup.
func Init() {
	_ = os.MkdirAll(usersDir, 0o755)
	go cleanOldLogs()
}

// cleanOldLogs removes wellbeing JSONL files older than retentionDays.
// Runs once at startup and daily after that.
func cleanOldLogs() {
	for {
		cutoff := time.Now().AddDate(0, 0, -retentionDays).Format("2006-01-02")
		entries, err := os.ReadDir(usersDir)
		if err == nil {
			for _, userDir := range entries {
				if !userDir.IsDir() {
					continue
				}
				dir := filepath.Join(usersDir, userDir.Name(), wellbeingSubdir)
				files, err := os.ReadDir(dir)
				if err != nil {
					continue
				}
				for _, f := range files {
					name := f.Name()
					if !strings.HasSuffix(name, fileSuffix) {
						continue
					}
					day := strings.TrimSuffix(name, fileSuffix)
					if day < cutoff {
						_ = os.Remove(filepath.Join(dir, name))
					}
				}
			}
		}
		time.Sleep(24 * time.Hour)
	}
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

// presenceActions are backend-written session markers. Multiple stranger
// faces cycling in and out all collapse to user="unknown", so we must
// dedup these here (lelamp only dedups motion.activity — presence events
// bypass it). Without this, stranger_74 → stranger_75 produces two
// "enter" entries and resets the wellbeing delta twice even though, from
// Lumi's perspective, the "user" (unknown) never changed.
//
// Physical activity actions (drink/break/sedentary) and agent-written
// nudge actions are not deduped here — lelamp already dedups them at the
// source for motion.activity, and nudge entries are explicitly meant to
// act as reset points one-per-event.
var presenceActions = map[string]bool{
	"enter": true,
	"leave": true,
}

// LogForUser appends an activity entry for the given user. For presence
// markers (enter/leave) it collapses against the last PRESENCE action
// (ignoring activity rows between them) so an enter while a session is
// still open, or a leave when no session is open, is skipped. Without
// this, stranger_74 → using computer → stranger_75 → using computer
// produces a second "enter" after the activity rows hide the first
// enter from a naive last-action check.
func LogForUser(user, action, notes string) {
	user = NormalizeUser(user)
	now := time.Now()

	global.mu.Lock()
	defer global.mu.Unlock()

	if presenceActions[action] {
		day := now.Format("2006-01-02")
		lastPresence := readLastPresenceAction(user, day)
		// enter while already in an open session → skip (session still live).
		// leave while no open session → skip (nothing to close).
		if action == "enter" && lastPresence == "enter" {
			return
		}
		if action == "leave" && lastPresence != "enter" {
			return
		}
	}

	seq := global.seqN.Add(1)
	evt := Event{
		TS:     float64(now.UnixNano()) / 1e9,
		Seq:    seq,
		Hour:   now.Hour(),
		Action: action,
		Notes:  notes,
	}
	global.writeJSONL(now, user, evt)
}

// readLastPresenceAction scans today's file bottom-up and returns the most
// recent enter/leave action for the user, or empty if none. Skips
// activity rows so an activity entry between two enters doesn't mask the
// open session.
func readLastPresenceAction(user, day string) string {
	path := filePath(user, day)
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	s := strings.TrimRight(string(data), "\n")
	if s == "" {
		return ""
	}
	lines := strings.Split(s, "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		var evt Event
		if err := json.Unmarshal([]byte(lines[i]), &evt); err != nil {
			continue
		}
		if presenceActions[evt.Action] {
			return evt.Action
		}
	}
	return ""
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
