// Package i18n exposes the active STT language (Lumi config) to callers
// that speak short hardcoded TTS phrases — recovery announcements, ambient
// mumbles, "brain restarting" notices. Each caller keeps its own phrase
// pools but uses Lang() to pick the active locale.
//
// The module is a singleton because the alternative — plumbing
// *config.Config through every Service constructor + Wire provider — would
// touch a lot of unrelated wiring just so an idle mumble loop can read one
// string. SetConfig is called once from server.ProvideServer / boot.
package i18n

import (
	"sync/atomic"

	"go-lamp.autonomous.ai/server/config"
)

// active holds the Config pointer set by SetConfig. atomic.Pointer because
// SetConfig may run on a different goroutine than Lang() readers.
var active atomic.Pointer[config.Config]

// SetConfig wires the live config so Lang() returns the current setting.
// Idempotent; later calls overwrite the pointer.
func SetConfig(cfg *config.Config) {
	active.Store(cfg)
}

// Lang returns the active STT language code (e.g. "vi", "en", "zh-CN").
// Empty string when SetConfig has not been called yet — callers should
// treat empty as the English fallback.
func Lang() string {
	cfg := active.Load()
	if cfg == nil {
		return ""
	}
	return cfg.STTLanguage
}
