package main

import "fmt"

// NarrationCategory tags a kind of activity-status announcement. The
// narrator uses these as both the throttle key and the lookup key into
// per-language template tables — adding a new category means adding an
// entry in narrationStrings for every supported language.
type NarrationCategory string

const (
	NarrateBusyStart     NarrationCategory = "busy_start"
	NarrateDone          NarrationCategory = "done"
	NarrateThinking      NarrationCategory = "thinking"
	NarrateToolWebSearch NarrationCategory = "tool_websearch"
	NarrateToolRead      NarrationCategory = "tool_read"
	NarrateToolWrite     NarrationCategory = "tool_write"
	NarrateToolEdit      NarrationCategory = "tool_edit"
	NarrateToolBash      NarrationCategory = "tool_bash"
	NarrateToolGeneric   NarrationCategory = "tool_generic" // template uses %s for the tool name
)

// fallbackLang is the language we reach for when the configured one
// has no template for a category. English keeps the widest TTS
// provider coverage and reads cleanly across most voices.
const fallbackLang = "en"

// narrationStrings is the only place narration text lives. Keep entries
// short (1–3 words for status, < ~8 words for generic) — these are
// played mid-flow while the user is reading code on the Mac.
var narrationStrings = map[string]map[NarrationCategory]string{
	"vi": {
		NarrateBusyStart:     "Claude bắt đầu",
		NarrateDone:          "Xong",
		NarrateThinking:      "Đang suy nghĩ",
		NarrateToolWebSearch: "Đang tìm web",
		NarrateToolRead:      "Đang đọc file",
		NarrateToolWrite:     "Đang viết file",
		NarrateToolEdit:      "Đang sửa file",
		NarrateToolBash:      "Đang chạy lệnh",
		NarrateToolGeneric:   "Đang dùng %s",
	},
	"en": {
		NarrateBusyStart:     "Claude starting",
		NarrateDone:          "Done",
		NarrateThinking:      "Thinking",
		NarrateToolWebSearch: "Searching the web",
		NarrateToolRead:      "Reading a file",
		NarrateToolWrite:     "Writing a file",
		NarrateToolEdit:      "Editing a file",
		NarrateToolBash:      "Running a shell command",
		NarrateToolGeneric:   "Running %s",
	},
}

// narrationText resolves a category against a language, falling back
// to English when the language is unknown or missing the entry, and
// finally to the raw category id so a missing template never silently
// swallows a narration.
func narrationText(lang string, cat NarrationCategory, args ...any) string {
	if tpl, ok := lookupTemplate(lang, cat); ok {
		return applyArgs(tpl, args...)
	}
	if lang != fallbackLang {
		if tpl, ok := lookupTemplate(fallbackLang, cat); ok {
			return applyArgs(tpl, args...)
		}
	}
	return string(cat)
}

func lookupTemplate(lang string, cat NarrationCategory) (string, bool) {
	if m, ok := narrationStrings[lang]; ok {
		if s, ok := m[cat]; ok && s != "" {
			return s, true
		}
	}
	return "", false
}

func applyArgs(tpl string, args ...any) string {
	if len(args) == 0 {
		return tpl
	}
	return fmt.Sprintf(tpl, args...)
}

// toolToCategory maps an Anthropic tool_use.name to the narration
// category that best describes the operation. Anything we don't have
// a dedicated category for falls back to NarrateToolGeneric, which
// surfaces the original name to the user so they still know what's
// running.
func toolToCategory(name string) NarrationCategory {
	switch name {
	case "WebSearch", "WebFetch":
		return NarrateToolWebSearch
	case "Read":
		return NarrateToolRead
	case "Write":
		return NarrateToolWrite
	case "Edit", "MultiEdit":
		return NarrateToolEdit
	case "Bash":
		return NarrateToolBash
	default:
		return NarrateToolGeneric
	}
}

// supportedLang returns the input language if narration strings exist
// for it, otherwise the fallback. Used when loading config so an
// invalid value doesn't silently degrade to category ids at runtime.
func supportedLang(lang string) string {
	if _, ok := narrationStrings[lang]; ok {
		return lang
	}
	return fallbackLang
}
