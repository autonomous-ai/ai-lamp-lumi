// Package mood provides a dedicated mood history logger per user.
//
// Logs mood-relevant sensing events (presence, wellbeing, light, sound) to daily
// JSONL files under each user's data directory. The music suggestion skill and
// wellbeing crons query this history to build a mood picture.
//
// Usage:
//
//	mood.Init()                                      // once at startup
//	mood.SetCurrentUser("gray")                      // on presence.enter
//	mood.Log("presence.enter", 0, "Person detected") // log event to user's mood dir
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
	TS          float64 `json:"ts"`                     // Unix seconds
	Seq         int64   `json:"seq"`                    // global sequence
	Event       string  `json:"event"`                  // "presence.enter", "music.mood", "mood.assessed", etc.
	PresenceMin int     `json:"presence_min,omitempty"` // minutes since presence started
	Hour        int     `json:"hour"`                   // hour of day (0-23) for time-of-day context
	Message     string  `json:"message,omitempty"`      // brief description (for sensing input events)
	User        string  `json:"user,omitempty"`         // who was present when this event was logged

	// Assessment fields (only for "mood.assessed" events)
	Emotion  string `json:"emotion,omitempty"`  // LLM's emotion response (e.g. "caring", "curious")
	Source   string `json:"source,omitempty"`   // which sensing event triggered this assessment
	Response string `json:"response,omitempty"` // what LLM said (or "" for NO_REPLY)
	NoReply  bool   `json:"no_reply,omitempty"` // true if agent decided not to respond
}

const (
	usersDir      = "/root/local/users"
	moodSubdir    = "mood"
	filePrefix    = "mood_"
	fileSuffix    = ".jsonl"
	retentionDays = 30

	// Legacy global path for backward compat queries
	legacyDir = "local"
)

// mood-relevant sensing event types
var moodEvents = map[string]bool{
	"presence.enter":      true,
	"presence.leave":      true,
	"presence.away":       true,
	"wellbeing.hydration": true,
	"wellbeing.break":     true,
	"music.mood":          true,
	"music.play":          true,
	"music.proactive":     true,
	"light.level":         true,
	"sound":               true,
	"motion.activity":     true,
}

type logger struct {
	mu   sync.Mutex
	seqN atomic.Int64
	file *os.File
	day  string
	user string // current file's user

	// Current user tracking
	currentUserMu sync.RWMutex
	currentUser   string

	// pendingRuns tracks sensing runID → event type for assessment logging.
	pendingMu   sync.Mutex
	pendingRuns map[string]pendingRun
}

type pendingRun struct {
	eventType string
	user      string
}

var global = &logger{
	pendingRuns: make(map[string]pendingRun),
}

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

// IsMoodEvent returns true if the event type is mood-relevant and should be logged.
func IsMoodEvent(eventType string) bool {
	return moodEvents[eventType]
}

// Log records a mood-relevant sensing event to the current user's mood directory.
// If no user is set, logs to legacy global path.
func Log(eventType string, presenceMin int, message string) {
	if !moodEvents[eventType] {
		return
	}

	user := CurrentUser()
	now := time.Now()
	seq := global.seqN.Add(1)

	evt := Event{
		TS:          float64(now.UnixNano()) / 1e9,
		Seq:         seq,
		Event:       eventType,
		PresenceMin: presenceMin,
		Hour:        now.Hour(),
		Message:     message,
		User:        user,
	}

	global.mu.Lock()
	global.writeJSONL(now, user, evt)
	global.mu.Unlock()
}

// TrackRun registers a sensing run so we can log the LLM's mood assessment
// when the agent lifecycle ends. Call from sensing handler after sending event.
func TrackRun(runID string, eventType string) {
	if !moodEvents[eventType] {
		return
	}
	user := CurrentUser()
	global.pendingMu.Lock()
	global.pendingRuns[runID] = pendingRun{eventType: eventType, user: user}
	global.pendingMu.Unlock()
}

// CompleteRun logs the LLM's mood assessment for a tracked sensing run.
// Returns the sensing event type if found (empty string if runID was not tracked).
func CompleteRun(runID string, emotion string, responseText string) string {
	global.pendingMu.Lock()
	pr, ok := global.pendingRuns[runID]
	if ok {
		delete(global.pendingRuns, runID)
	}
	global.pendingMu.Unlock()

	if !ok {
		return ""
	}

	now := time.Now()
	seq := global.seqN.Add(1)

	isNoReply := responseText == "" || strings.EqualFold(strings.TrimSpace(responseText), "no_reply") ||
		strings.EqualFold(strings.TrimSpace(responseText), "[no reply]")

	evt := Event{
		TS:       float64(now.UnixNano()) / 1e9,
		Seq:      seq,
		Event:    "mood.assessed",
		Hour:     now.Hour(),
		Emotion:  emotion,
		Source:   pr.eventType,
		Response: responseText,
		NoReply:  isNoReply,
		User:     pr.user,
	}

	global.mu.Lock()
	global.writeJSONL(now, pr.user, evt)
	global.mu.Unlock()

	return pr.eventType
}

// Query reads mood events for a given user and day (YYYY-MM-DD format).
// If user is empty, reads from legacy global path.
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
	if user == "" {
		return filepath.Join(legacyDir, filePrefix+day+fileSuffix)
	}
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

	// Clean legacy global logs
	cleanDir(legacyDir, cutoff)

	// Clean per-user mood logs
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
		// Extract date from filename: mood_YYYY-MM-DD.jsonl or YYYY-MM-DD.jsonl
		date := strings.TrimSuffix(name, fileSuffix)
		date = strings.TrimPrefix(date, filePrefix)
		if date < cutoff {
			path := filepath.Join(dir, name)
			if err := os.Remove(path); err == nil {
				slog.Info("removed old mood log", "component", "mood", "file", path)
			}
		}
	}
}
