package sse

import (
	"io"
	"log/slog"
	"net/http"
	"regexp"
	"strings"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/lib/flow"
	"go-lamp.autonomous.ai/lib/lelamp"
)

// prunedImageMarkerRe matches bracket markers echoed by the LLM after OpenClaw
// strips image payloads from conversation history (e.g. "[image description removed]").
var prunedImageMarkerRe = regexp.MustCompile(`\[image[^\]]*removed[^\]]*\]`)

// hwMarkerRe matches inline hardware markers like [HW:/emotion:{"emotion":"happy","intensity":0.9}]
// JSON body must not contain '}' except as the final closing brace (no nested objects).
var hwMarkerRe = regexp.MustCompile(`\[HW:(/[^:]+):(\{[^}]*\})\]`)

type hwCall struct {
	path string
	body string
}

// extractHWCalls parses all [HW:/path:{"json"}] markers from text,
// returns the list of calls and the text with all markers stripped.
func extractHWCalls(text string) ([]hwCall, string) {
	matches := hwMarkerRe.FindAllStringSubmatch(text, -1)
	calls := make([]hwCall, 0, len(matches))
	for _, m := range matches {
		calls = append(calls, hwCall{path: m[1], body: m[2]})
	}
	return calls, strings.TrimSpace(hwMarkerRe.ReplaceAllString(text, ""))
}

// fireHWCalls fires hardware calls to LeLamp sequentially in a goroutine,
// with full flow tracking, lastEmotion update, and monitorBus events.
// Sequential order matters (e.g. emotion sequences must fire in order).
func (h *OpenClawHandler) fireHWCalls(calls []hwCall, flowRunID string) {
	if len(calls) == 0 {
		return
	}
	go func() {
		for _, c := range calls {
			// /broadcast, /speak, /dm are internal control markers — not LeLamp endpoints.
			if c.path == "/broadcast" || c.path == "/speak" || c.path == "/dm" {
				continue
			}
			resp, err := http.Post(lelamp.BaseURL+c.path, "application/json", strings.NewReader(c.body))
			if err != nil {
				slog.Warn("HW marker call failed", "component", "openclaw", "path", c.path, "error", err)
				continue
			}
			hwOK := resp.StatusCode < 400
			if !hwOK {
				errBody, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
				resp.Body.Close()
				slog.Warn("HW marker error response", "component", "openclaw", "path", c.path, "status", resp.StatusCode, "body", string(errBody))
			} else {
				resp.Body.Close()
				slog.Info("HW marker fired", "component", "openclaw", "path", c.path)
			}
			switch {
			case strings.Contains(c.path, "/emotion"):
				flow.Log("hw_emotion", map[string]any{"path": c.path, "args": c.body, "run_id": flowRunID}, flowRunID)
				if hwOK {
					if e := parseEmotion(c.body); e != "" {
						h.lastEmotionMu.Lock()
						h.lastEmotion = e
						h.lastEmotionMu.Unlock()
					}
				}
				h.monitorBus.Push(domain.MonitorEvent{Type: "hw_emotion", Summary: c.path + " " + c.body, RunID: flowRunID})
			case strings.Contains(c.path, "/scene"), strings.Contains(c.path, "/led"):
				flow.Log("hw_led", map[string]any{"path": c.path, "args": c.body, "run_id": flowRunID}, flowRunID)
				h.monitorBus.Push(domain.MonitorEvent{Type: "hw_led", Summary: c.path + " " + c.body, RunID: flowRunID})
			case strings.Contains(c.path, "/servo"):
				flow.Log("hw_servo", map[string]any{"path": c.path, "args": c.body, "run_id": flowRunID}, flowRunID)
				h.monitorBus.Push(domain.MonitorEvent{Type: "hw_servo", Summary: c.path + " " + c.body, RunID: flowRunID})
			case strings.Contains(c.path, "/audio"):
				flow.Log("hw_audio", map[string]any{"path": c.path, "args": c.body, "run_id": flowRunID}, flowRunID)
				h.monitorBus.Push(domain.MonitorEvent{Type: "hw_audio", Summary: c.path + " " + c.body, RunID: flowRunID})
				// music.play logged via flow.Log above
			default:
				flow.Log("hw_call", map[string]any{"path": c.path, "args": c.body, "run_id": flowRunID}, flowRunID)
			}
		}
	}()
}
