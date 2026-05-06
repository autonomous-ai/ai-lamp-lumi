package sse

import (
	"encoding/json"
	"log/slog"
	"regexp"
	"strings"
)

var emotionRe = regexp.MustCompile(`(?:\\"|")emotion(?:\\"|")\s*:\s*(?:\\"|")([a-zA-Z_]+)(?:\\"|")`)

// parseEmotion extracts the emotion name from a tool call args string.
// Handles both plain JSON ("emotion": "sad") and escaped JSON (\"emotion\": \"sad\").
func parseEmotion(toolArgs string) string {
	if m := emotionRe.FindStringSubmatch(toolArgs); len(m) == 2 {
		return m[1]
	}
	return ""
}

// extractTTSText parses the text argument from an OpenClaw built-in tts tool call.
// Args can be JSON like {"text":"hello"} or a plain string.
func extractTTSText(toolArgs string) string {
	var obj struct {
		Text string `json:"text"`
	}
	if json.Unmarshal([]byte(toolArgs), &obj) == nil && obj.Text != "" {
		return obj.Text
	}
	return strings.TrimSpace(toolArgs)
}

// isAgentNoReply returns true if text is an OpenClaw framework "silent" sentinel
// (e.g. "NO_REPLY", "NO_RE") or a bare "NO" the LLM sometimes emits instead.
// These should never be spoken aloud or shown to the user.
func isAgentNoReply(text string) bool {
	t := strings.TrimSpace(strings.ToUpper(text))
	if t == "NO" {
		slog.Warn("agent emitted bare NO instead of NO_REPLY — suppressing TTS", "component", "agent", "raw", text)
		return true
	}
	if strings.HasPrefix(t, "NO_") {
		slog.Warn("agent no-reply sentinel — suppressing TTS", "component", "agent", "raw", text)
		return true
	}
	return false
}

// sanitizeAgentText strips internal sentinels the LLM sometimes appends to real replies.
// e.g. "Hello! NO_REPLY" → "Hello!", "...done! HEARTBEAT_OK" → "...done!"
func sanitizeAgentText(text string) string {
	for _, sentinel := range []string{"NO_REPLY", "HEARTBEAT_OK"} {
		if idx := strings.LastIndex(strings.ToUpper(text), sentinel); idx >= 0 {
			cleaned := strings.TrimRight(text[:idx], " \t\n!.,—–-")
			if cleaned != "" {
				slog.Warn("stripped trailing sentinel from agent text", "component", "agent", "sentinel", sentinel, "before", text[:min(len(text), 100)], "after", cleaned)
				text = cleaned
			}
		}
	}
	return text
}

// sayTagRe captures the content between the first <say>...</say> pair.
// The (?s) flag lets `.` match newlines so multi-line content is supported.
var sayTagRe = regexp.MustCompile(`(?s)<say>(.*?)</say>`)

// extractSayTag pulls the spoken sentence out of a <say>...</say> wrapper.
// Skills (currently wellbeing) instruct the model to wrap the one caring sentence
// in <say> tags so its free-form reasoning in the text block doesn't leak to TTS.
// Passthrough when no tag is present so skills that don't opt in stay unchanged.
// Empty tag (`<say></say>`) collapses to NO_REPLY.
func extractSayTag(text string) string {
	m := sayTagRe.FindStringSubmatch(text)
	if m == nil {
		return text
	}
	inner := strings.TrimSpace(m[1])
	if inner == "" {
		slog.Info("empty <say> tag — treating as NO_REPLY", "component", "agent")
		return "NO_REPLY"
	}
	slog.Info("extracted <say> tag", "component", "agent", "before_len", len(text), "after", inner[:min(len(inner), 100)])
	return inner
}

// isLumiOutboundChatRunID is true when runID matches Lumi's chat.send idempotency key
// (lumi-chat-* current; lumi-sensing-* legacy). Used so traceless lifecycle_start is not
// mis-tagged as Telegram-only when the turn was initiated from Lumi.
func isLumiOutboundChatRunID(runID string) bool {
	if runID == "" {
		return false
	}
	return strings.HasPrefix(runID, "lumi-chat-") || strings.HasPrefix(runID, "lumi-sensing-")
}

// extractMessageContentText collects text from a session.message `content`
// field. OpenClaw emits content as either a plain string or an array of typed
// blocks ({"type":"text","text":"..."} / {"type":"toolCall",...}). Only
// `type == "text"` blocks contribute to the joined output; tool blocks
// carry no spoken text.
func extractMessageContentText(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	var s string
	if err := json.Unmarshal(raw, &s); err == nil {
		return s
	}
	var blocks []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	if err := json.Unmarshal(raw, &blocks); err != nil {
		return ""
	}
	parts := make([]string, 0, len(blocks))
	for _, b := range blocks {
		if b.Type == "text" && strings.TrimSpace(b.Text) != "" {
			parts = append(parts, b.Text)
		}
	}
	return strings.Join(parts, "")
}

// telegramChatIDRe extracts the chat_id from OpenClaw queue-mode metadata
// injected at the top of a Telegram-originated user message, e.g.
// `"chat_id": "telegram:158406741"`.
var telegramChatIDRe = regexp.MustCompile(`"chat_id"\s*:\s*"telegram:(\d+)"`)

// extractTelegramChatID returns the numeric Telegram chat_id from a session
// message body when OpenClaw injected the conversation metadata block; "" if
// the marker is absent (non-Telegram message or older OpenClaw format).
func extractTelegramChatID(text string) string {
	if m := telegramChatIDRe.FindStringSubmatch(text); len(m) == 2 {
		return m[1]
	}
	return ""
}

// senderLabelTelegramIDRe captures the numeric id from senderLabel formats
// emitted by OpenClaw, e.g. "Leo (@squall_leo_hart) id:158406741" or
// "Leo (158406741)". Used as fallback when the message content lacks the
// `chat_id: telegram:<id>` metadata block (sometimes injected, sometimes not).
var senderLabelTelegramIDRe = regexp.MustCompile(`(?:id:|\()(\d{6,})\)?`)

// extractTelegramIDFromSenderLabel returns the numeric Telegram user ID found
// in a senderLabel string. Returns "" if no id-like substring matches.
func extractTelegramIDFromSenderLabel(label string) string {
	if label == "" {
		return ""
	}
	if m := senderLabelTelegramIDRe.FindStringSubmatch(label); len(m) == 2 {
		return m[1]
	}
	return ""
}

// shortError extracts a short, readable message from a potentially large error string.
// Strips HTML bodies (e.g. Cloudflare 403 pages) down to the status line.
func shortError(errMsg string) string {
	// Extract leading status code + domain if it looks like "403 <!DOCTYPE..."
	if idx := strings.Index(errMsg, "<!"); idx > 0 {
		prefix := strings.TrimSpace(errMsg[:idx])
		// Try to find domain from <h2> "unable to access X"
		if i := strings.Index(errMsg, "unable_to_access"); i > 0 {
			if j := strings.Index(errMsg[i:], ">"); j > 0 {
				if k := strings.Index(errMsg[i+j:], "<"); k > 0 {
					domain := strings.TrimSpace(errMsg[i+j+1 : i+j+k])
					if domain != "" {
						return prefix + " blocked by Cloudflare (" + domain + ")"
					}
				}
			}
		}
		return prefix + " (HTML error page)"
	}
	if len(errMsg) > 120 {
		return errMsg[:120] + "..."
	}
	return errMsg
}
