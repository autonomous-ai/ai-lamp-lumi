// Package mood provides a per-user mood history logger.
//
// Tracks the user's emotional state over time. Mood is logged when:
// - Camera detects emotional actions (laughing, crying, yawning, etc.)
// - Agent infers mood from conversation context
//
// Usage:
//
//	mood.Init()                                      // once at startup
//	mood.SetCurrentUser("gray")                      // on presence.enter
//	mood.LogMood("happy", "camera", "laughing")       // log user mood
//	events := mood.Query("gray", "2026-04-07", 100)  // query user's history
//	mood.ClearCurrentUser()                          // on presence.leave
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
	TS      float64 `json:"ts"`              // Unix seconds
	Seq     int64   `json:"seq"`             // global sequence
	Hour    int     `json:"hour"`            // hour of day (0-23)
	Mood    string  `json:"mood"`            // user mood: happy, sad, stressed, tired, excited, etc.
	Source  string  `json:"source"`          // how mood was detected: camera, conversation
	Trigger string  `json:"trigger"`         // what triggered: action name or conversation context
}

const (
	usersDir      = "/root/local/users"
	moodSubdir    = "mood"
	fileSuffix    = ".jsonl"
	retentionDays = 7
)

type logger struct {
	mu   sync.Mutex
	seqN atomic.Int64
	file *os.File
	day  string
	user string // current file's user

	// Current user tracking
	currentUserMu sync.RWMutex
	currentUser   string
}

var global = &logger{}

// Init creates the users directory.
// Call once at startup.
func Init() {
	_ = os.MkdirAll(usersDir, 0o755)
	go cleanOldLogs()
}

// SetCurrentUser sets the user who is currently present.
// Call on presence.enter with the recognized user name.
func SetCurrentUser(name string) {
	global.currentUserMu.Lock()
	global.currentUser = strings.ToLower(strings.TrimSpace(name))
	global.currentUserMu.Unlock()
	slog.Info("mood: current user set", "user", name)
}

// ClearCurrentUser clears the current user.
// Call on presence.leave.
func ClearCurrentUser() {
	global.currentUserMu.Lock()
	global.currentUser = ""
	global.currentUserMu.Unlock()
}

// CurrentUser returns the current user name (empty if none).
func CurrentUser() string {
	global.currentUserMu.RLock()
	defer global.currentUserMu.RUnlock()
	return global.currentUser
}

// LogMood records a user mood event to the current user's mood directory.
// Falls back to "unknown" when no user is detected via presence.
func LogMood(moodStr, source, trigger string) {
	user := CurrentUser()
	if user == "" {
		user = "unknown"
	}
	LogMoodForUser(user, moodStr, source, trigger)
}

// LogMoodForUser records a user mood event for a specific user.
func LogMoodForUser(user, moodStr, source, trigger string) {
	now := time.Now()
	seq := global.seqN.Add(1)

	evt := Event{
		TS:      float64(now.UnixNano()) / 1e9,
		Seq:     seq,
		Hour:    now.Hour(),
		Mood:    moodStr,
		Source:  source,
		Trigger: trigger,
	}

	global.mu.Lock()
	global.writeJSONL(now, user, evt)
	global.mu.Unlock()
}

// Query reads mood events for a given user and day (YYYY-MM-DD format).
// Returns up to last n events. If n <= 0, returns all.
func Query(user string, day string, n int) []Event {
	path := moodFilePath(user, day)
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

// moodFilePath returns the JSONL file path for a user+day.
func moodFilePath(user, day string) string {
	return filepath.Join(usersDir, user, moodSubdir, day+fileSuffix)
}

// writeJSONL appends the event to the user's daily JSONL file.
// Must be called with mu held.
func (l *logger) writeJSONL(now time.Time, user string, evt Event) {
	day := now.Format("2006-01-02")

	// Reopen file if day or user changed
	if l.day != day || l.user != user || l.file == nil {
		if l.file != nil {
			_ = l.file.Close()
		}
		path := moodFilePath(user, day)
		_ = os.MkdirAll(filepath.Dir(path), 0o755)
		f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			slog.Error("mood: failed to open log file", "path", path, "error", err)
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

func cleanOldLogs() {
	cutoff := time.Now().AddDate(0, 0, -retentionDays).Format("2006-01-02")

	userDirs, err := os.ReadDir(usersDir)
	if err != nil {
		return
	}
	for _, ud := range userDirs {
		if !ud.IsDir() || strings.HasPrefix(ud.Name(), ".") {
			continue
		}
		moodDir := filepath.Join(usersDir, ud.Name(), moodSubdir)
		cleanDir(moodDir, cutoff)
	}
}

func cleanDir(dir, cutoff string) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	for _, e := range entries {
		name := e.Name()
		if !strings.HasSuffix(name, fileSuffix) {
			continue
		}
		date := strings.TrimSuffix(name, fileSuffix)
		if date < cutoff {
			path := filepath.Join(dir, name)
			if err := os.Remove(path); err == nil {
				slog.Info("removed old mood log", "component", "mood", "file", path)
			}
		}
	}
}
