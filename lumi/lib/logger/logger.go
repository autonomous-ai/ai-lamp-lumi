package logger

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"sync"
	"time"
)

// ANSI color codes
const (
	colorReset  = "\033[0m"
	colorRed    = "\033[31m"
	colorGreen  = "\033[32m"
	colorYellow = "\033[33m"
	colorCyan   = "\033[36m"
	colorGray   = "\033[90m"
)

// colorHandler is a slog.Handler that writes colored, human-readable log lines.
type colorHandler struct {
	w     io.Writer
	mu    sync.Mutex
	level slog.Level
	attrs []slog.Attr
	group string
}

func (h *colorHandler) Enabled(_ context.Context, level slog.Level) bool {
	return level >= h.level
}

func (h *colorHandler) Handle(_ context.Context, r slog.Record) error {
	var levelColor, levelTag string
	switch {
	case r.Level >= slog.LevelError:
		levelColor = colorRed
		levelTag = "ERROR"
	case r.Level >= slog.LevelWarn:
		levelColor = colorYellow
		levelTag = "WARN"
	case r.Level >= slog.LevelInfo:
		levelColor = colorGreen
		levelTag = "INFO"
	default:
		levelColor = colorGray
		levelTag = "DEBUG"
	}

	ts := r.Time.Format(time.DateTime)
	line := fmt.Sprintf("%s%s%s %s%-5s%s %s",
		colorGray, ts, colorReset,
		levelColor, levelTag, colorReset,
		r.Message,
	)

	// Append attributes
	r.Attrs(func(a slog.Attr) bool {
		key := a.Key
		if h.group != "" {
			key = h.group + "." + key
		}
		line += fmt.Sprintf(" %s%s=%s%v", colorCyan, key, colorReset, a.Value)
		return true
	})
	for _, a := range h.attrs {
		key := a.Key
		if h.group != "" {
			key = h.group + "." + key
		}
		line += fmt.Sprintf(" %s%s=%s%v", colorCyan, key, colorReset, a.Value)
	}
	line += "\n"

	h.mu.Lock()
	defer h.mu.Unlock()
	_, err := h.w.Write([]byte(line))
	return err
}

func (h *colorHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	newAttrs := make([]slog.Attr, len(h.attrs), len(h.attrs)+len(attrs))
	copy(newAttrs, h.attrs)
	newAttrs = append(newAttrs, attrs...)
	return &colorHandler{w: h.w, level: h.level, attrs: newAttrs, group: h.group}
}

func (h *colorHandler) WithGroup(name string) slog.Handler {
	g := name
	if h.group != "" {
		g = h.group + "." + name
	}
	newAttrs := make([]slog.Attr, len(h.attrs))
	copy(newAttrs, h.attrs)
	return &colorHandler{w: h.w, level: h.level, attrs: newAttrs, group: g}
}

// Init sets up the global slog default logger with colored output.
// Call this once at the start of main().
func Init(level slog.Level) {
	handler := &colorHandler{
		w:     os.Stderr,
		level: level,
	}
	slog.SetDefault(slog.New(handler))
}
