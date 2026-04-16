package sse

import (
	"context"
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/internal/statusled"
	"go-lamp.autonomous.ai/lib/flow"
	"go-lamp.autonomous.ai/lib/mood"
	"go-lamp.autonomous.ai/server/config"
	"go-lamp.autonomous.ai/server/serializers"
)

// OpenClawHandler handles OpenClaw gateway WebSocket events and exposes monitor endpoints.
type OpenClawHandler struct {
	agentGateway domain.AgentGateway
	monitorBus   *monitor.Bus
	statusLED    *statusled.Service

	// assistantBuf accumulates assistant deltas per runId so we can send the
	// full text to TTS when the agent turn ends (lifecycle "end").
	assistantMu  sync.Mutex
	assistantBuf map[string]*strings.Builder

	// ttsSuppressReasons tracks runIDs that should skip TTS on lifecycle end.
	// Value is the reason: "music_playing" (speaker shared with audio) or
	// "already_spoken" (TTS tool intercepted and already routed to speaker).
	ttsSuppressMu      sync.Mutex
	ttsSuppressReasons map[string]string

	// runIDMap maps OpenClaw-assigned UUIDs back to device-originated idempotencyKeys.
	// When lifecycle_start arrives with UUID while a device trace is active, we store
	// the mapping so all subsequent events for that UUID use the device ID for flow tracing.
	runIDMapMu sync.Mutex
	runIDMap   map[string]string // OpenClaw UUID → device idempotencyKey

	// lastEmotion tracks the most recent emotion expressed by the agent.
	lastEmotionMu sync.Mutex
	lastEmotion   string

	// channelRuns tracks runs confirmed from a real channel user (Telegram/etc.)
	// via senderLabel. Prevents TTS when a Telegram UUID gets mapped to a
	// sensing trace (race: flowRunID becomes lumi-sensing-* → isChannelRun false).
	channelRunsMu sync.Mutex
	channelRuns   map[string]bool

}

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

// ProvideOpenClawHandler returns an OpenClaw events handler.
func ProvideOpenClawHandler(gw domain.AgentGateway, bus *monitor.Bus, sled *statusled.Service) OpenClawHandler {
	// Init flow emitter here so ws_connect events (fired from StartWS before any HTTP request)
	// are broadcast to SSE. Lumi is a single-user device so the global trace ID is sufficient;
	// concurrent turn interleaving is not a concern in normal operation.
	flow.Init(bus, config.LumiVersion)
	mood.Init()
	return OpenClawHandler{
		agentGateway: gw,
		monitorBus:   bus,
		statusLED:    sled,
		assistantBuf:       make(map[string]*strings.Builder),
		ttsSuppressReasons: make(map[string]string),
		runIDMap:           make(map[string]string),
		channelRuns:        make(map[string]bool),
	}
}

// IsSleeping returns true when the last emotion expressed by the agent was "sleepy".
// Used by SensingHandler to suppress passive sensing events during sleep mode.
func (h *OpenClawHandler) IsSleeping() bool {
	h.lastEmotionMu.Lock()
	defer h.lastEmotionMu.Unlock()
	return h.lastEmotion == "sleepy"
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

// isLumiOutboundChatRunID is true when runID matches Lumi's chat.send idempotency key
// (lumi-chat-* current; lumi-sensing-* legacy). Used so traceless lifecycle_start is not
// mis-tagged as Telegram-only when the turn was initiated from Lumi.
func isLumiOutboundChatRunID(runID string) bool {
	if runID == "" {
		return false
	}
	return strings.HasPrefix(runID, "lumi-chat-") || strings.HasPrefix(runID, "lumi-sensing-")
}

// accumulateAssistantDelta appends a delta to the buffer for the given runId.
func (h *OpenClawHandler) accumulateAssistantDelta(runID, delta string) {
	if delta == "" {
		return
	}
	h.assistantMu.Lock()
	defer h.assistantMu.Unlock()
	buf, ok := h.assistantBuf[runID]
	if !ok {
		buf = &strings.Builder{}
		h.assistantBuf[runID] = buf
	}
	buf.WriteString(delta)
}

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
			// /broadcast is handled internally (not a LeLamp hardware call).
			if c.path == "/broadcast" {
				continue
			}
			resp, err := http.Post("http://127.0.0.1:5001"+c.path, "application/json", strings.NewReader(c.body))
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

// flushAssistantText returns the accumulated text for runId and clears the buffer.
// HW markers are stripped here so they never appear in Telegram or other channel replies.
// The caller is responsible for extracting and firing HW calls before flushing.
func (h *OpenClawHandler) flushAssistantText(runID string) (string, []hwCall) {
	h.assistantMu.Lock()
	defer h.assistantMu.Unlock()
	buf, ok := h.assistantBuf[runID]
	if !ok || buf.Len() == 0 {
		return "", nil
	}
	raw := buf.String()
	raw = prunedImageMarkerRe.ReplaceAllString(raw, "")
	calls, text := extractHWCalls(raw)
	text = strings.TrimSpace(text)
	delete(h.assistantBuf, runID)
	return text, calls
}

// suppressTTS flags a runID to skip TTS on lifecycle end with the given reason.
func (h *OpenClawHandler) suppressTTS(runID, reason string) {
	h.ttsSuppressMu.Lock()
	defer h.ttsSuppressMu.Unlock()
	// "music_playing" takes priority over "already_spoken" (speaker conflict is more important).
	if existing := h.ttsSuppressReasons[runID]; existing == "music_playing" && reason != "music_playing" {
		return
	}
	h.ttsSuppressReasons[runID] = reason
}

// clearTTSSuppress removes the suppress flag for a runID and returns the reason (empty if none).
func (h *OpenClawHandler) clearTTSSuppress(runID string) string {
	h.ttsSuppressMu.Lock()
	defer h.ttsSuppressMu.Unlock()
	reason := h.ttsSuppressReasons[runID]
	delete(h.ttsSuppressReasons, runID)
	return reason
}

// resolveRunID maps an OpenClaw-assigned UUID back to the device idempotencyKey if known.
// If no mapping exists, returns the original runID unchanged.
func (h *OpenClawHandler) resolveRunID(runID string) string {
	h.runIDMapMu.Lock()
	defer h.runIDMapMu.Unlock()
	if mapped, ok := h.runIDMap[runID]; ok {
		return mapped
	}
	return runID
}

// mapRunID records that OpenClaw UUID corresponds to the given device trace (idempotencyKey).
func (h *OpenClawHandler) mapRunID(openclawID, deviceID string) {
	h.runIDMapMu.Lock()
	defer h.runIDMapMu.Unlock()
	h.runIDMap[openclawID] = deviceID
	// Limit map size to prevent unbounded growth
	if len(h.runIDMap) > 200 {
		for k := range h.runIDMap {
			delete(h.runIDMap, k)
			break
		}
	}
}

// HandleEvent processes incoming WebSocket events from the OpenClaw gateway.
func (h *OpenClawHandler) HandleEvent(ctx context.Context, evt domain.WSEvent) error {
	slog.Debug("event received", "component", "agent", "event", evt.Event)

	switch evt.Event {
	case "agent":
		var payload domain.AgentPayload
		if err := json.Unmarshal(evt.Payload, &payload); err != nil {
			return err
		}
		// Capture session key from any agent event
		if payload.SessionKey != "" && h.agentGateway.GetSessionKey() == "" {
			h.agentGateway.SetSessionKey(payload.SessionKey)
		}

		// Map OpenClaw UUID → device idempotencyKey on lifecycle_start.
		// Only map when the lifecycle belongs to Lumi's own direct session — group/channel
		// sessions have independent runs that must NOT be merged into sensing traces.
		// Uses dedicated pending chat trace (not global flow.GetTrace) to avoid race conditions
		// where concurrent channel turns clear the global trace before lifecycle_start arrives.
		lumiSession := h.agentGateway.GetSessionKey()
		isLumiSession := lumiSession != "" && payload.SessionKey == lumiSession
		if payload.Stream == "lifecycle" && payload.Data.Phase == "start" && payload.RunID != "" && isLumiSession {
			if deviceTrace := h.agentGateway.ConsumePendingChatTrace(); deviceTrace != "" && deviceTrace != payload.RunID {
				h.mapRunID(payload.RunID, deviceTrace)
				slog.Info("mapped OpenClaw runId to device trace", "component", "agent", "openclawId", payload.RunID, "deviceId", deviceTrace)
				slog.Info("flow correlation", "op", "openclaw_uuid_map", "section", "openclaw",
					"openclaw_run_id", payload.RunID, "device_run_id", deviceTrace,
					"note", "JSONL/monitor use device_run_id for this turn")
			}
		}

		// Resolve OpenClaw UUID → device ID for consistent flow tracing across all agent events
		flowRunID := h.resolveRunID(payload.RunID)
		switch payload.Stream {
		case "lifecycle":
			slog.Info("lifecycle event", "component", "agent", "phase", payload.Data.Phase, "runId", payload.RunID, "flowRunId", flowRunID, "session", payload.SessionKey)

			// Detect external channel-initiated turns: lifecycle_start arrives from OpenClaw
			// with a UUID run_id (not lumi-chat-* prefix). This covers:
			// 1. No active trace (original case)
			// 2. Active trace from a different turn (sensing trace still active when Telegram arrives)
			isChannelTurn := payload.Data.Phase == "start" && payload.RunID != "" &&
				!isLumiOutboundChatRunID(payload.RunID) && !isLumiOutboundChatRunID(flowRunID)
			if isChannelTurn {
				// Emit chat_input immediately (no message text yet).
				flow.Log("chat_input", map[string]any{"run_id": payload.RunID, "source": "channel"}, payload.RunID)
				h.monitorBus.Push(domain.MonitorEvent{
					Type:    "chat_input",
					Summary: "[" + h.agentGateway.GetConfiguredChannel() + "]",
					RunID:   payload.RunID,
					Detail:  map[string]string{"role": "user"},
				})

				// Best-effort: fetch chat history in a separate goroutine to avoid
				// deadlocking the WS read loop (FetchChatHistory waits for a response
				// that can only arrive after this handler returns).
				capturedRunID := payload.RunID
				capturedSessionKey := payload.SessionKey
				go func() {
					historyPayload, histErr := h.agentGateway.FetchChatHistory(capturedSessionKey, 20)
					if histErr != nil {
						slog.Warn("chat.history fetch failed (best-effort)", "component", "agent", "run_id", capturedRunID, "err", histErr)
						return
					}
					if historyPayload == nil {
						return
					}
					slog.Info("chat.history for channel turn", "component", "agent", "run_id", capturedRunID, "history_bytes", len(historyPayload))

					// Extract last user message from history.
					var userMsg string
					var senderLabel string
					var hist struct {
						Messages []struct {
							Role        string          `json:"role"`
							Content     json.RawMessage `json:"content"`
							SenderLabel string          `json:"senderLabel"`
						} `json:"messages"`
					}
					if json.Unmarshal(historyPayload, &hist) == nil {
						for i := len(hist.Messages) - 1; i >= 0; i-- {
							if hist.Messages[i].Role == "user" {
								senderLabel = hist.Messages[i].SenderLabel
								var text string
								if json.Unmarshal(hist.Messages[i].Content, &text) == nil {
									userMsg = text
								} else {
									var blocks []struct {
										Type string `json:"type"`
										Text string `json:"text"`
									}
									if json.Unmarshal(hist.Messages[i].Content, &blocks) == nil {
										var parts []string
										for _, b := range blocks {
											if b.Type == "text" && strings.TrimSpace(b.Text) != "" {
												parts = append(parts, b.Text)
											}
										}
										userMsg = strings.Join(parts, " ")
									}
								}
								break
							}
						}
					}
					// Mark as confirmed channel run if a real sender is present.
					// Guards against race: Telegram UUID mapped to sensing trace
					// makes flowRunID = lumi-sensing-* → isChannelRun wrongly false.
					if senderLabel != "" {
						h.channelRunsMu.Lock()
						h.channelRuns[capturedRunID] = true
						h.channelRunsMu.Unlock()
					}
					if userMsg != "" {
						// Detect music-proactive cron turns — broadcast to Telegram for remote confirmation.
						if strings.Contains(userMsg, "[music-proactive]") {
							resolved := h.resolveRunID(capturedRunID)
							h.agentGateway.MarkBroadcastRun(resolved)
						}

						displayMsg := userMsg
						if len(displayMsg) > 200 {
							displayMsg = displayMsg[:200] + "…"
						}
						chName := h.agentGateway.GetConfiguredChannel()
						prefix := "[" + chName + "]"
						if senderLabel != "" {
							prefix = "[" + chName + ":" + senderLabel + "]"
						}
						flow.Log("chat_input", map[string]any{
							"run_id":  capturedRunID,
							"source":  "channel",
							"message": userMsg,
							"sender":  senderLabel,
						}, capturedRunID)
						h.monitorBus.Push(domain.MonitorEvent{
							Type:    "chat_input",
							Summary: prefix + " " + displayMsg,
							RunID:   capturedRunID,
							Detail:  map[string]string{"role": "user", "message": userMsg, "sender": senderLabel},
						})
					}
				}()
			}

			// Track busy state so passive sensing events can be suppressed during active turns.
			// LED is managed by the agent via /emotion skill calls — do not override here.
			if payload.Data.Phase == "start" {
				h.agentGateway.SetBusy(true)
			} else if payload.Data.Phase == "end" || payload.Data.Phase == "error" {
				h.agentGateway.SetBusy(false)
			}

			// Token usage: try lifecycle_end payload first, fallback to chat.history RPC.
			if payload.Data.Phase == "end" {
				slog.Info("lifecycle end raw", "component", "agent", "runId", payload.RunID, "raw", string(evt.Payload))
				if u := payload.Data.Usage; u != nil {
					slog.Info("token usage", "component", "agent", "runId", payload.RunID,
						"input", u.InputTokens, "output", u.OutputTokens,
						"cacheRead", u.CacheReadTokens, "cacheWrite", u.CacheWriteTokens,
						"total", u.TotalTokens)
					flow.Log("token_usage", map[string]any{
						"run_id":            flowRunID,
						"input_tokens":      u.InputTokens,
						"output_tokens":     u.OutputTokens,
						"cache_read_tokens": u.CacheReadTokens,
						"cache_write_tokens": u.CacheWriteTokens,
						"total_tokens":      u.TotalTokens,
					}, flowRunID)
					h.monitorBus.Push(domain.MonitorEvent{
						Type:    "token_usage",
						Summary: fmt.Sprintf("in:%d out:%d total:%d", u.InputTokens, u.OutputTokens, u.TotalTokens),
						RunID:   flowRunID,
						Detail: map[string]string{
							"input_tokens":       fmt.Sprintf("%d", u.InputTokens),
							"output_tokens":      fmt.Sprintf("%d", u.OutputTokens),
							"cache_read_tokens":  fmt.Sprintf("%d", u.CacheReadTokens),
							"cache_write_tokens": fmt.Sprintf("%d", u.CacheWriteTokens),
							"total_tokens":       fmt.Sprintf("%d", u.TotalTokens),
						},
					})
				} else {
					// OpenClaw lifecycle_end does not include usage. Fetch from chat.history instead.
					capturedFlowRunID := flowRunID
					capturedSessionKey := payload.SessionKey
					go func() {
						histPayload, err := h.agentGateway.FetchChatHistory(capturedSessionKey, 5)
						if err != nil {
							slog.Warn("chat.history usage fetch failed", "component", "agent", "run_id", capturedFlowRunID, "err", err)
							return
						}
						if histPayload == nil {
							return
						}
						type histUsage struct {
							Input       int `json:"input"`
							Output      int `json:"output"`
							TotalTokens int `json:"totalTokens"`
							CacheRead   int `json:"cacheRead"`
							CacheWrite  int `json:"cacheWrite"`
						}
						type histContent struct {
							Type     string `json:"type"`
							Text     string `json:"text,omitempty"`
							Thinking string `json:"thinking,omitempty"`
						}
						var hist struct {
							Messages []struct {
								Role    string         `json:"role"`
								Usage   *histUsage     `json:"usage,omitempty"`
								Content []histContent  `json:"content,omitempty"`
							} `json:"messages"`
						}
						if json.Unmarshal(histPayload, &hist) != nil {
							return
						}
						// Extract thinking from last assistant message and emit to monitor
						for i := len(hist.Messages) - 1; i >= 0; i-- {
							if hist.Messages[i].Role == "assistant" {
								for _, c := range hist.Messages[i].Content {
									if c.Type == "thinking" && c.Thinking != "" {
										flow.Log("agent_thinking", map[string]any{
											"run_id":  capturedFlowRunID,
											"source":  "chat_history",
											"text":    c.Thinking,
										}, capturedFlowRunID)
										h.monitorBus.Push(domain.MonitorEvent{
											Type:    "thinking",
											Summary: c.Thinking,
											RunID:   capturedFlowRunID,
										})
									}
								}
								break
							}
						}
						// Find last assistant message with usage.
						for i := len(hist.Messages) - 1; i >= 0; i-- {
							if hist.Messages[i].Role == "assistant" && hist.Messages[i].Usage != nil {
								u := hist.Messages[i].Usage
								slog.Info("token usage (from chat.history)", "component", "agent",
									"run_id", capturedFlowRunID,
									"input", u.Input, "output", u.Output,
									"cacheRead", u.CacheRead, "cacheWrite", u.CacheWrite,
									"total", u.TotalTokens)
								flow.Log("token_usage", map[string]any{
									"run_id":             capturedFlowRunID,
									"source":             "chat_history",
									"input_tokens":       u.Input,
									"output_tokens":      u.Output,
									"cache_read_tokens":  u.CacheRead,
									"cache_write_tokens": u.CacheWrite,
									"total_tokens":       u.TotalTokens,
								}, capturedFlowRunID)
								h.monitorBus.Push(domain.MonitorEvent{
									Type:    "lifecycle",
									Summary: fmt.Sprintf("Agent end — tokens: %d in / %d out", u.Input, u.Output),
									RunID:   capturedFlowRunID,
									Detail: map[string]string{
										"inputTokens":  fmt.Sprintf("%d", u.Input),
										"outputTokens": fmt.Sprintf("%d", u.Output),
										"cacheRead":    fmt.Sprintf("%d", u.CacheRead),
										"cacheWrite":   fmt.Sprintf("%d", u.CacheWrite),
										"totalTokens":  fmt.Sprintf("%d", u.TotalTokens),
									},
								})
								h.monitorBus.Push(domain.MonitorEvent{
									Type:    "token_usage",
									Summary: fmt.Sprintf("in:%d out:%d total:%d", u.Input, u.Output, u.TotalTokens),
									RunID:   capturedFlowRunID,
									Detail: map[string]string{
										"input_tokens":       fmt.Sprintf("%d", u.Input),
										"output_tokens":      fmt.Sprintf("%d", u.Output),
										"cache_read_tokens":  fmt.Sprintf("%d", u.CacheRead),
										"cache_write_tokens": fmt.Sprintf("%d", u.CacheWrite),
										"total_tokens":       fmt.Sprintf("%d", u.TotalTokens),
									},
								})
								// Auto-compact when context exceeds threshold
								const autoCompactThreshold = 120_000
								if u.TotalTokens > autoCompactThreshold {
									sk := h.agentGateway.GetSessionKey()
									slog.Info("auto-compact triggered", "component", "agent",
										"total_tokens", u.TotalTokens, "threshold", autoCompactThreshold,
										"sessionKey", sk)
									go func() {
										if err := h.agentGateway.CompactSession(sk); err != nil {
											slog.Error("auto-compact failed", "component", "agent", "error", err)
										}
									}()
								}
								break
							}
						}
					}()
				}
			}

			shortErr := shortError(payload.Data.Error)
			flow.Log("lifecycle_"+payload.Data.Phase, map[string]any{"run_id": flowRunID, "error": payload.Data.Error}, flowRunID)
			monEvt := domain.MonitorEvent{
				Type:    "lifecycle",
				Summary: fmt.Sprintf("Agent %s", payload.Data.Phase),
				RunID:   flowRunID,
				Phase:   payload.Data.Phase,
				Error:   shortErr,
			}
			if payload.Data.Phase == "error" && shortErr != "" {
				monEvt.Summary = "❌ " + shortErr
			}
			if payload.Data.Phase == "end" && payload.Data.Usage != nil {
				u := payload.Data.Usage
				monEvt.Detail = map[string]string{
					"inputTokens":  fmt.Sprintf("%d", u.InputTokens),
					"outputTokens": fmt.Sprintf("%d", u.OutputTokens),
					"cacheRead":    fmt.Sprintf("%d", u.CacheReadTokens),
					"cacheWrite":   fmt.Sprintf("%d", u.CacheWriteTokens),
					"totalTokens":  fmt.Sprintf("%d", u.TotalTokens),
				}
				monEvt.Summary = fmt.Sprintf("Agent end — tokens: %d in / %d out", u.InputTokens, u.OutputTokens)
			}
			h.monitorBus.Push(monEvt)

			// Keep flow.GetTrace() "active" for the duration of the device turn so Telegram heuristic
			// (lifecycle_start arriving while no device trace is active) can work correctly.
			// Clear only after lifecycle_end so openclaw UUID → device runId mapping still succeeds.
			if payload.Data.Phase == "end" || payload.Data.Phase == "error" {
				flow.ClearTrace()
			}

		case "tool":
			toolName := payload.ToolName()
			toolArgs := payload.ToolArguments()
			summary := toolName
			if payload.Data.Phase == "start" {
				summary = fmt.Sprintf("Tool %s started", toolName)
				// Detect music playback tool calls so we can suppress TTS on turn end.
				// The Music skill uses Bash+curl to POST /audio/play.
				if strings.Contains(toolArgs, "/audio/play") {
					h.suppressTTS(payload.RunID, "music_playing")
					slog.Info("music tool detected, TTS will be suppressed for this turn", "component", "agent", "runId", payload.RunID)
					h.monitorBus.Push(domain.MonitorEvent{Type: "hw_audio", Summary: toolArgs, RunID: flowRunID})
					flow.Log("hw_audio", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
					// music.play logged via flow.Log above
				}
				// Emit specific hardware events for flow monitor visualization.
				// Both flow.Log (for JSONL persistence + UI flow_event triggers) and monitorBus (for SSE).
				if strings.Contains(toolArgs, "/emotion") {
					h.monitorBus.Push(domain.MonitorEvent{Type: "led_set", Summary: "agent tool: " + toolName})
					h.monitorBus.Push(domain.MonitorEvent{Type: "hw_emotion", Summary: toolArgs, RunID: flowRunID})
					flow.Log("hw_emotion", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
					if e := parseEmotion(toolArgs); e != "" {
						h.lastEmotionMu.Lock()
						h.lastEmotion = e
						h.lastEmotionMu.Unlock()
					}
				} else if strings.Contains(toolArgs, "/led/solid") ||
					strings.Contains(toolArgs, "/led/effect") ||
					strings.Contains(toolArgs, "/scene") {
					h.monitorBus.Push(domain.MonitorEvent{Type: "led_set", Summary: "agent tool: " + toolName})
					h.monitorBus.Push(domain.MonitorEvent{Type: "hw_led", Summary: toolArgs, RunID: flowRunID})
					flow.Log("hw_led", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
				}
				if strings.Contains(toolArgs, "/led/off") {
					h.monitorBus.Push(domain.MonitorEvent{Type: "led_off", Summary: "agent tool: " + toolName})
					h.monitorBus.Push(domain.MonitorEvent{Type: "hw_led", Summary: toolArgs, RunID: flowRunID})
					flow.Log("hw_led", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
				}
				if strings.Contains(toolArgs, "/servo/aim") || strings.Contains(toolArgs, "/servo/play") {
					h.monitorBus.Push(domain.MonitorEvent{Type: "hw_servo", Summary: toolArgs, RunID: flowRunID})
					flow.Log("hw_servo", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
				}
				// Intercept OpenClaw built-in tts tool: extract text and route to LeLamp speaker.
				// The built-in tts generates audio server-side but never reaches the physical speaker.
				if toolName == "tts" {
					if ttsText := extractTTSText(toolArgs); ttsText != "" {
						isChannelRun := !isLumiOutboundChatRunID(payload.RunID) && !isLumiOutboundChatRunID(flowRunID)
						isWebChat := h.agentGateway.IsWebChatRun(flowRunID)
						slog.Info("intercepted built-in tts tool, routing to LeLamp", "component", "agent", "run_id", flowRunID, "text", ttsText[:min(len(ttsText), 80)], "channel_run", isChannelRun, "web_chat", isWebChat)
						flow.Log("tts_send", map[string]any{"run_id": flowRunID, "text": ttsText, "source": "tts_tool_intercept"}, flowRunID)
						if !isChannelRun && !isWebChat {
							go func(t string) {
								if err := h.agentGateway.SendToLeLampTTS(t); err != nil {
									slog.Error("TTS intercept delivery failed", "component", "agent", "error", err)
								}
							}(ttsText)
						}
						// Mark this turn as already spoken so lifecycle_end won't double-speak.
						h.suppressTTS(payload.RunID, "already_spoken")
					}
				}
			} else if payload.Data.Phase == "end" {
				result := payload.Data.Result
				if len(result) > 100 {
					result = result[:100] + "..."
				}
				summary = fmt.Sprintf("Tool %s done", toolName)
				if result != "" {
					summary += ": " + result
				}
			}
			flow.Log("tool_call", map[string]any{"tool": toolName, "phase": payload.Data.Phase, "run_id": flowRunID}, flowRunID)
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "tool_call",
				Summary: summary,
				RunID:   flowRunID,
				Phase:   payload.Data.Phase,
				Detail: map[string]string{
					"tool": toolName,
					"args": toolArgs,
				},
			})

		case "thinking":
			delta := payload.Data.Delta
			if delta == "" {
				delta = payload.Data.Text
			}
			// Don't truncate deltas — they are merged in the frontend
			if delta != "" {
				h.monitorBus.Push(domain.MonitorEvent{
					Type:    "thinking",
					Summary: delta,
					RunID:   flowRunID,
				})
			}

		case "assistant":
			delta := payload.Data.Delta
			if delta == "" {
				delta = payload.Data.Text
			}
			// Don't truncate deltas — they are merged in the frontend
			if delta != "" {
				h.monitorBus.Push(domain.MonitorEvent{
					Type:    "assistant_delta",
					Summary: delta,
					RunID:   flowRunID,
				})
			}

			// When the agent turn ends, the final assistant text should be spoken.
			// Accumulate deltas per runId and send to TTS when lifecycle "end" arrives.
			h.accumulateAssistantDelta(payload.RunID, delta)

		}

		// When agent lifecycle ends, flush accumulated assistant text to TTS.
		// Suppress TTS if the agent played music or already spoke via tool intercept.
		if payload.Stream == "lifecycle" && payload.Data.Phase == "end" {
			suppressReason := h.clearTTSSuppress(payload.RunID)
			// Web monitor chat: suppress TTS — response displayed in web UI only.
			if suppressReason == "" && h.agentGateway.ConsumeWebChatRun(flowRunID) {
				suppressReason = "web_chat"
			}
			if text, hwCalls := h.flushAssistantText(payload.RunID); text != "" || len(hwCalls) > 0 {
				// Fire HW calls with full tracking (flow.Log + lastEmotion + monitorBus).
				h.fireHWCalls(hwCalls, flowRunID)

				// Suppress TTS when HW markers include /audio/play to avoid
				// voice and music racing on the speaker (matches tool-path behavior at line 626).
				if suppressReason == "" {
					for _, c := range hwCalls {
						if strings.Contains(c.path, "/audio/play") {
							suppressReason = "music_playing"
							break
						}
					}
				}

				// Consume broadcast marker early to prevent map leak on NO_REPLY/empty/suppressed paths.
				isBroadcastRun := h.agentGateway.ConsumeBroadcastRun(flowRunID)

				// [HW:/broadcast] marker: agent requests broadcast to Telegram.
				// Used by wellbeing crons, music suggestions, and proactive care.
				// [HW:/dm:{"telegram_id":"123"}] marker: send to a specific Telegram user.
				var dmTelegramID string
				for _, c := range hwCalls {
					if c.path == "/broadcast" {
						isBroadcastRun = true
					}
					if c.path == "/dm" {
						var dm struct {
							TelegramID string `json:"telegram_id"`
						}
						if err := json.Unmarshal([]byte(c.body), &dm); err == nil && dm.TelegramID != "" {
							dmTelegramID = dm.TelegramID
						}
					}
				}

				// Guard mode: broadcast even on NO_REPLY / empty / suppressed paths.
				// The agent may choose not to speak, but we still want to alert the owner via Telegram.
				if snap, ok := h.agentGateway.ConsumeGuardRun(flowRunID); ok {
					guardText := text
					if guardText == "" || isAgentNoReply(guardText) {
						guardText = "Motion or presence detected while guard mode is active."
					}
					go func(t, s string) {
						slog.Info("guard broadcast via Telegram Bot API", "component", "agent", "run_id", flowRunID, "text", t[:min(len(t), 80)])
						if err := h.agentGateway.Broadcast(t, s); err != nil {
							slog.Error("guard broadcast failed", "component", "agent", "err", err)
						}
					}(guardText, snap)
				}

				// Detect heartbeat before sanitizing strips the sentinel.
				isHeartbeatRun := strings.Contains(strings.ToUpper(text), "HEARTBEAT_OK")
				text = sanitizeAgentText(text)
				if isAgentNoReply(text) {
					// NO_REPLY: agent explicitly decided to do nothing
					slog.Info("agent replied NO_REPLY, skipping TTS", "component", "agent", "run_id", flowRunID)
					flow.Log("no_reply", map[string]any{"run_id": flowRunID}, flowRunID)
					h.monitorBus.Push(domain.MonitorEvent{
						Type:    "chat_response",
						Summary: "[no reply]",
						RunID:   flowRunID,
						State:   "final",
						Detail:  map[string]string{"role": "assistant", "message": "[no reply]"},
					})
				} else if text == "" {
					// HW-only reply (only markers, no spoken text)
					flow.Log("hw_only_reply", map[string]any{"run_id": flowRunID}, flowRunID)
				} else if suppressReason != "" {
					slog.Info("assistant turn done, TTS suppressed", "component", "agent", "reason", suppressReason, "text", text[:min(len(text), 100)])
					flow.Log("tts_suppressed", map[string]any{"run_id": flowRunID, "reason": suppressReason, "text": text}, flowRunID)
				} else {
					isChannelRun := !isLumiOutboundChatRunID(payload.RunID) && !isLumiOutboundChatRunID(flowRunID)
					// [HW:/broadcast] forces TTS even for channel runs (like guard mode).
					if isBroadcastRun {
						isChannelRun = false
					}
					// Heartbeat cron responses must never reach the speaker.
					if isHeartbeatRun {
						isChannelRun = true
					}
					// Override: confirmed channel turn via senderLabel always suppresses TTS.
					// Covers race where Telegram UUID mapped to sensing trace (lumi-sensing-*).
					h.channelRunsMu.Lock()
					if h.channelRuns[payload.RunID] || h.channelRuns[flowRunID] {
						isChannelRun = true
					}
					delete(h.channelRuns, payload.RunID)
					delete(h.channelRuns, flowRunID)
					h.channelRunsMu.Unlock()
					slog.Info("assistant turn done, sending to TTS", "component", "agent", "text", text[:min(len(text), 100)], "channel_run", isChannelRun, "broadcast", isBroadcastRun, "heartbeat", isHeartbeatRun)
					flow.Log("tts_send", map[string]any{"run_id": flowRunID, "text": text}, flowRunID)
					if !isChannelRun {
						go func(t string) {
							if err := h.agentGateway.SendToLeLampTTS(t); err != nil {
								slog.Error("TTS delivery failed", "component", "agent", "error", err)
							}
						}(text)
					}
					// Guard broadcast is handled above (before the if/else) to ensure
					// it fires even on NO_REPLY / empty / suppressed paths.
					// DM run: send agent response to a specific Telegram user.
					// Takes priority over broadcast — if /dm is present, /broadcast is skipped.
					if dmTelegramID != "" && len(text) > 10 {
						go func(t, tid string) {
							slog.Info("dm run response to user", "component", "agent", "run_id", flowRunID, "telegram_id", tid, "text", t[:min(len(t), 80)])
							if err := h.agentGateway.SendToUser(tid, t, ""); err != nil {
								slog.Error("dm run failed", "component", "agent", "err", err)
							}
						}(text, dmTelegramID)
					} else if isBroadcastRun && len(text) > 10 {
						// Broadcast run (e.g. music.mood): send agent response to all channels
						// so user can confirm via Telegram instead of only voice.
						go func(t string) {
							slog.Info("broadcast run response to channels", "component", "agent", "run_id", flowRunID, "text", t[:min(len(t), 80)])
							if err := h.agentGateway.Broadcast(t, ""); err != nil {
								slog.Error("broadcast run failed", "component", "agent", "err", err)
							}
						}(text)
					}
				}
			}
		}

	case "session.tool":
		// Tool events for session-subscribed clients (covers Telegram-initiated turns).
		var payload domain.AgentPayload
		if err := json.Unmarshal(evt.Payload, &payload); err != nil {
			slog.Warn("session.tool unmarshal error", "component", "agent", "err", err)
			return nil
		}
		flowRunID := h.resolveRunID(payload.RunID)
		toolName := payload.ToolName()
		toolArgs := payload.ToolArguments()
		summary := toolName
		if payload.Data.Phase == "start" {
			summary = fmt.Sprintf("Tool %s started", toolName)
			if strings.Contains(toolArgs, "/audio/play") {
				h.suppressTTS(payload.RunID, "music_playing")
				slog.Info("music tool detected (session.tool), TTS suppressed", "component", "agent", "runId", payload.RunID)
				h.monitorBus.Push(domain.MonitorEvent{Type: "hw_audio", Summary: toolArgs, RunID: flowRunID})
				flow.Log("hw_audio", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
			}
			// Emit specific hardware events for flow monitor visualization.
			// Both flow.Log (for JSONL persistence + UI flow_event triggers) and monitorBus (for SSE).
			if strings.Contains(toolArgs, "/emotion") {
				h.monitorBus.Push(domain.MonitorEvent{Type: "led_set", Summary: "agent tool: " + toolName})
				h.monitorBus.Push(domain.MonitorEvent{Type: "hw_emotion", Summary: toolArgs, RunID: flowRunID})
				flow.Log("hw_emotion", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
				if e := parseEmotion(toolArgs); e != "" {
					h.lastEmotionMu.Lock()
					h.lastEmotion = e
					h.lastEmotionMu.Unlock()
				}
			} else if strings.Contains(toolArgs, "/led/solid") ||
				strings.Contains(toolArgs, "/led/effect") ||
				strings.Contains(toolArgs, "/scene") {
				h.monitorBus.Push(domain.MonitorEvent{Type: "led_set", Summary: "agent tool: " + toolName})
				h.monitorBus.Push(domain.MonitorEvent{Type: "hw_led", Summary: toolArgs, RunID: flowRunID})
				flow.Log("hw_led", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
			}
			if strings.Contains(toolArgs, "/led/off") {
				h.monitorBus.Push(domain.MonitorEvent{Type: "led_off", Summary: "agent tool: " + toolName})
				h.monitorBus.Push(domain.MonitorEvent{Type: "hw_led", Summary: toolArgs, RunID: flowRunID})
				flow.Log("hw_led", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
			}
			if strings.Contains(toolArgs, "/servo/aim") || strings.Contains(toolArgs, "/servo/play") {
				h.monitorBus.Push(domain.MonitorEvent{Type: "hw_servo", Summary: toolArgs, RunID: flowRunID})
				flow.Log("hw_servo", map[string]any{"args": toolArgs, "run_id": flowRunID}, flowRunID)
			}
			// Intercept OpenClaw built-in tts tool (session.tool path).
			if toolName == "tts" {
				if ttsText := extractTTSText(toolArgs); ttsText != "" {
					isChannelRun := !isLumiOutboundChatRunID(payload.RunID) && !isLumiOutboundChatRunID(flowRunID)
					isWebChat := h.agentGateway.IsWebChatRun(flowRunID)
					slog.Info("intercepted built-in tts tool (session.tool), routing to LeLamp", "component", "agent", "run_id", flowRunID, "text", ttsText[:min(len(ttsText), 80)], "channel_run", isChannelRun, "web_chat", isWebChat)
					flow.Log("tts_send", map[string]any{"run_id": flowRunID, "text": ttsText, "source": "tts_tool_intercept"}, flowRunID)
					if !isChannelRun && !isWebChat {
						go func(t string) {
							if err := h.agentGateway.SendToLeLampTTS(t); err != nil {
								slog.Error("TTS intercept delivery failed", "component", "agent", "error", err)
							}
						}(ttsText)
					}
					h.suppressTTS(payload.RunID, "already_spoken")
				}
			}
		} else if payload.Data.Phase == "end" {
			result := payload.Data.Result
			if len(result) > 100 {
				result = result[:100] + "..."
			}
			summary = fmt.Sprintf("Tool %s done", toolName)
			if result != "" {
				summary += ": " + result
			}
		}
		flow.Log("tool_call", map[string]any{"tool": toolName, "phase": payload.Data.Phase, "run_id": flowRunID, "source": "session.tool", "args": toolArgs}, flowRunID)
		h.monitorBus.Push(domain.MonitorEvent{
			Type:    "tool_call",
			Summary: summary,
			RunID:   flowRunID,
			Phase:   payload.Data.Phase,
			Detail: map[string]string{
				"tool": toolName,
				"args": toolArgs,
			},
		})

	case "chat":
		slog.Debug("chat raw payload", "component", "agent", "payload", string(evt.Payload))
		var payload domain.ChatPayload
		if err := json.Unmarshal(evt.Payload, &payload); err != nil {
			slog.Error("chat parse error", "component", "agent", "error", err, "raw", string(evt.Payload))
			return nil
		}
		payload.ResolveChatMessage()
		slog.Info(">>> CHAT EVENT RECEIVED", "component", "agent",
			"run_id", payload.RunID,
			"role", payload.Role,
			"state", payload.State,
			"message_len", len(payload.Message),
			"message", payload.Message,
			"raw_message", string(payload.RawMessage))
		// Same as agent stream: OpenClaw may send UUID while lifecycle/tool/tts used resolved device id.
		flowRunID := h.resolveRunID(payload.RunID)
		// Debug alignment: OpenClaw "chat" stream may or may not include user messages for outbound chat.send.
		// When flowRunID belongs to Lumi, log role/state/message so we can confirm whether chat_input can be emitted.
		if strings.HasPrefix(flowRunID, "lumi-") {
			msgPreview := payload.Message
			msgPreview = strings.ReplaceAll(msgPreview, "\n", " ")
			if len(msgPreview) > 120 {
				msgPreview = msgPreview[:120] + "…"
			}
			slog.Info("openclaw chat event (lumi)", "component", "agent",
				"openclaw_run_id", payload.RunID,
				"flow_run_id", flowRunID,
				"role", payload.Role,
				"state", payload.State,
				"has_message", strings.TrimSpace(msgPreview) != "",
				"message_preview", msgPreview)
		}
		if payload.RunID != "" && flowRunID != payload.RunID {
			slog.Info("flow correlation", "op", "chat_run_resolve", "section", "openclaw_chat",
				"openclaw_run_id", payload.RunID, "device_run_id", flowRunID,
				"role", payload.Role, "state", payload.State)
		}


		// (OpenClaw gateway never broadcasts role:"user" on the chat stream.
		// User messages are captured via lifecycle_start + chat.history above.)

		// Chat error: OpenClaw reports agent processing failure
		if payload.State == "error" {
			errMsg := payload.ErrorMessage
			if errMsg == "" {
				errMsg = "unknown error"
			}
			slog.Error("OpenClaw chat error", "component", "agent", "run_id", flowRunID, "error", errMsg)
			flow.Log("agent_error", map[string]any{"run_id": flowRunID, "error": errMsg}, flowRunID)
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "chat_response",
				Summary: "❌ " + shortError(errMsg),
				RunID:   flowRunID,
				State:   "error",
				Error:   shortError(errMsg),
				Detail:  map[string]string{"error": shortError(errMsg)},
			})
		}

		// Push assistant/partial chat events to monitor (user input tracked via lifecycle_start — already tracked as chat_input)
		if payload.Role != "user" && payload.State != "error" {
			summary := payload.Message
			if len(summary) > 120 {
				summary = summary[:120] + "..."
			}
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "chat_response",
				Summary: summary,
				RunID:   flowRunID,
				State:   payload.State,
				Detail: map[string]string{
					"role":    payload.Role,
					"message": payload.Message,
				},
			})
		}

		// TTS is sent from the lifecycle_end path above (assistant delta accumulation).
		// The chat stream's final message is not used for TTS to avoid speaking responses twice.

	default:
		// Unhandled WS events (health, heartbeat, cron, shutdown, etc.) — no-op.
	}

	return nil
}

// Status returns the current agent connection status.
// StopTTS interrupts active TTS playback on LeLamp.
func (h *OpenClawHandler) StopTTS(c *gin.Context) {
	if err := h.agentGateway.StopTTS(); err != nil {
		slog.Warn("StopTTS failed", "component", "openclaw", "error", err)
		c.JSON(http.StatusBadGateway, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(nil))
}

// SetBusy marks the agent as busy from an external signal (e.g. turn-gate hook firing at
// message:preprocessed before lifecycle_start SSE arrives). Closes the timing gap for
// channel-initiated turns (Telegram, Slack, Discord) that bypass Lumi server entirely.
func (h *OpenClawHandler) SetBusy(c *gin.Context) {
	h.agentGateway.SetBusy(true)
	c.JSON(http.StatusOK, serializers.ResponseSuccess(nil))
}

func (h *OpenClawHandler) Status(c *gin.Context) {
	h.lastEmotionMu.Lock()
	emotion := h.lastEmotion
	h.lastEmotionMu.Unlock()
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"name":       h.agentGateway.Name(),
		"connected":  h.agentGateway.IsReady(),
		"sessionKey": h.agentGateway.GetSessionKey() != "",
		"emotion":    emotion,
	}))
}

// Recent returns the latest flow events from today's JSONL file only.
// This keeps Flow UI deterministic by using a single source of truth (file log).
func (h *OpenClawHandler) Recent(c *gin.Context) {
	events := recentFlowFromJSONL(time.Now().Format("2006-01-02"), 500, h.agentGateway.GetConfiguredChannel())
	if events == nil {
		events = []domain.MonitorEvent{}
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(events))
}

// readAllJSONLines reads every line from a flow_events_*.jsonl file (full day).
func readAllJSONLines(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var lines []string
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 2*1024*1024) // 2MB max line
	for scanner.Scan() {
		line := scanner.Text()
		if len(line) == 0 || line[0] != '{' {
			continue // skip corrupt/binary lines
		}
		lines = append(lines, line)
	}
	// Don't fail on scanner error — return what we have so far
	if err := scanner.Err(); err != nil {
		slog.Warn("readAllJSONLines: scanner error, returning partial results", "path", path, "lines_read", len(lines), "error", err)
	}
	return lines, nil
}

// recentFlowFromJSONL reads the last n lines from flow JSONL for a given date (YYYY-MM-DD)
// and converts them to MonitorEvents.
func recentFlowFromJSONL(day string, n int, channelName string) []domain.MonitorEvent {
	path := filepath.Join("local", fmt.Sprintf("flow_events_%s.jsonl", day))
	lines, err := readAllJSONLines(path)
	if err != nil {
		return nil
	}

	// Take last n lines
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}

	events := make([]domain.MonitorEvent, 0, len(lines))
	for _, line := range lines {
		var fe flow.Event
		if err := json.Unmarshal([]byte(line), &fe); err != nil {
			continue
		}
		ev := flowEventToMonitor(fe, channelName)
		events = append(events, ev)
	}
	return events
}

// FlowEvents returns flow events from JSONL file by date.
// Query params: date=YYYY-MM-DD (default today), last=<n> (default 500, max 2000).
func (h *OpenClawHandler) FlowEvents(c *gin.Context) {
	day := c.DefaultQuery("date", time.Now().Format("2006-01-02"))
	last := 500
	if s := c.Query("last"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			last = n
		}
	}
	if last > 10000 {
		last = 10000
	}
	events := recentFlowFromJSONL(day, last, h.agentGateway.GetConfiguredChannel())
	if events == nil {
		events = []domain.MonitorEvent{}
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"date":   day,
		"events": events,
	}))
}

// MoodHistory returns mood-relevant sensing events for music suggestion context.
// Query params: user=<name> (default: current user), date=YYYY-MM-DD (default today), last=<n> (default 100, max 500).
func (h *OpenClawHandler) MoodHistory(c *gin.Context) {
	user := c.DefaultQuery("user", mood.CurrentUser())
	day := c.DefaultQuery("date", time.Now().Format("2006-01-02"))
	last := 100
	if s := c.Query("last"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			last = n
		}
	}
	if last > 500 {
		last = 500
	}
	events := mood.Query(user, day, last)
	if events == nil {
		events = []mood.Event{}
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"date":   day,
		"events": events,
	}))
}

// FlowStream streams today's flow events when the JSONL file changes.
// This is file-based live mode (no monitor bus dependency).
func (h *OpenClawHandler) FlowStream(c *gin.Context) {
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	lastMtime := int64(0)
	for {
		select {
		case <-c.Request.Context().Done():
			return
		default:
		}

		day := time.Now().Format("2006-01-02")
		path := filepath.Join("local", fmt.Sprintf("flow_events_%s.jsonl", day))
		if st, err := os.Stat(path); err == nil {
			mt := st.ModTime().UnixNano()
			if mt > lastMtime {
				lastMtime = mt
				events := recentFlowFromJSONL(day, 500, h.agentGateway.GetConfiguredChannel())
				if events == nil {
					events = []domain.MonitorEvent{}
				}
				payload := map[string]any{
					"date":   day,
					"events": events,
				}
				data, _ := json.Marshal(payload)
				c.SSEvent("message", string(data))
				c.Writer.Flush()
			}
		}
		time.Sleep(1000 * time.Millisecond)
	}
}

// flowEventToMonitor converts a flow.Event (JSONL) to a domain.MonitorEvent (for UI).
func flowEventToMonitor(fe flow.Event, channelName string) domain.MonitorEvent {
	evType := "flow_" + string(fe.Kind)

	// Promote well-known nodes to their own event type for turn grouping
	switch fe.Node {
	case "sensing_input":
		if fe.Kind == "enter" {
			evType = "sensing_input"
		}
	case "chat_input":
		if fe.Kind == "enter" || fe.Kind == "event" {
			evType = "chat_input"
		}
	case "intent_match":
		if fe.Kind == "event" || fe.Kind == "exit" {
			evType = "intent_match"
		}
	}

	summary := fmt.Sprintf("[%s] %s", fe.Kind, fe.Node)
	if fe.DurationMs > 0 {
		summary += fmt.Sprintf(" (%dms)", fe.DurationMs)
	}

	// Build summary from data for well-known nodes
	if fe.Node == "sensing_input" && fe.Kind == "enter" && fe.Data != nil {
		if msg, ok := fe.Data["message"].(string); ok {
			typ, _ := fe.Data["type"].(string)
			summary = fmt.Sprintf("[%s] %s", typ, msg)
		}
	}
	if fe.Node == "chat_input" && fe.Data != nil {
		if msg, ok := fe.Data["message"].(string); ok && msg != "" {
			summary = fmt.Sprintf("[%s] %s", channelName, msg)
		} else {
			summary = "[" + channelName + "]"
		}
	}

	t := time.Unix(int64(fe.TS), int64((fe.TS-float64(int64(fe.TS)))*1e9))

	return domain.MonitorEvent{
		ID:      fmt.Sprintf("flow-%d", fe.Seq),
		Time:    t.Format(time.RFC3339Nano),
		Type:    evType,
		Summary: summary,
		RunID:   fe.TraceID,
		Phase:   string(fe.Kind),
		Detail:  map[string]any{"node": fe.Node, "dur_ms": fe.DurationMs, "data": fe.Data},
	}
}

// FlowLogs serves the daily flow JSONL log file for download.
// Query params: ?date=YYYY-MM-DD (default today); ?last=N (optional) — if set, only the last N lines
// are returned (same tail as GET /openclaw/flow-events?last=N). Omit ?last for the full day file.
func (h *OpenClawHandler) FlowLogs(c *gin.Context) {
	date := c.Query("date")
	if date == "" {
		date = time.Now().Format("2006-01-02")
	}
	path := filepath.Join("local", fmt.Sprintf("flow_events_%s.jsonl", date))

	last := 0
	if s := c.Query("last"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			last = n
			if last > 2000 {
				last = 2000
			}
		}
	}

	filename := fmt.Sprintf("lumi_flow_%s.jsonl", date)
	var out []byte
	if last > 0 {
		lines, err := readAllJSONLines(path)
		if err != nil {
			c.JSON(http.StatusNotFound, serializers.ResponseError("no log for date: "+date))
			return
		}
		if len(lines) > last {
			lines = lines[len(lines)-last:]
		}
		filename = fmt.Sprintf("lumi_flow_%s_last%d.jsonl", date, last)
		out = []byte(strings.Join(lines, "\n"))
		if len(out) > 0 {
			out = append(out, '\n')
		}
	} else {
		var err error
		out, err = os.ReadFile(path)
		if err != nil {
			c.JSON(http.StatusNotFound, serializers.ResponseError("no log for date: "+date))
			return
		}
	}

	c.Header("Content-Disposition", "attachment; filename="+filename)
	c.Header("Content-Type", "application/x-ndjson")
	_, _ = c.Writer.Write(out)
}

// ClearFlowLogs truncates the daily flow JSONL log file.
// Query param ?date=YYYY-MM-DD selects a historical file; defaults to today.
func (h *OpenClawHandler) ClearFlowLogs(c *gin.Context) {
	date := c.Query("date")
	if date == "" {
		date = time.Now().Format("2006-01-02")
	}
	path := fmt.Sprintf("local/flow_events_%s.jsonl", date)
	if _, err := os.Stat(path); os.IsNotExist(err) {
		c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
			"cleared": false,
			"file":    path,
			"note":    "file not found",
		}))
		return
	}
	if err := os.Truncate(path, 0); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError("clear flow log failed: "+err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"cleared": true,
		"file":    path,
	}))
}

// Analytics returns aggregated per-day metrics from flow JSONL files.
// Query params: from=YYYY-MM-DD, to=YYYY-MM-DD (defaults to last 7 days).
func (h *OpenClawHandler) Analytics(c *gin.Context) {
	toDate := c.DefaultQuery("to", time.Now().Format("2006-01-02"))
	fromDate := c.DefaultQuery("from", time.Now().AddDate(0, 0, -7).Format("2006-01-02"))

	from, err := time.Parse("2006-01-02", fromDate)
	if err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError("invalid from date"))
		return
	}
	to, err := time.Parse("2006-01-02", toDate)
	if err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError("invalid to date"))
		return
	}

	// Per-day-version metrics keyed by "date|version"
	type dvKey struct{ date, version string }
	type dvMetrics struct {
		TurnCount    int     `json:"turnCount"`
		DurationAvg  float64 `json:"durationAvg"`
		DurationP50  float64 `json:"durationP50"`
		DurationP95  float64 `json:"durationP95"`
		TokensTotal  int     `json:"tokensTotal"`
		TokensInput  int     `json:"tokensInput"`
		TokensOutput int     `json:"tokensOutput"`
		TokensBilled int     `json:"tokensBilled"`
		TokensAvg    float64 `json:"tokensAvg"`
		InnerAvg     float64 `json:"innerAvg"`
		InnerMax     int     `json:"innerMax"`
	}

	type flowEvent struct {
		Kind       string         `json:"kind"`
		Node       string         `json:"node"`
		TS         float64        `json:"ts"`
		TraceID    string         `json:"trace_id"`
		DurationMs int64          `json:"duration_ms"`
		Data       map[string]any `json:"data"`
		Version    string         `json:"version"`
	}

	type turnData struct {
		version    string
		durationMs int64
		tokens     int
		tokensIn   int
		tokensOut  int
		cacheRead  int
		cacheWrite int
		toolCalls  int
	}

	allDates := []string{}
	versionSet := make(map[string]bool)
	// turns keyed by traceID, accumulates across a day file
	dayTurns := make(map[string]map[string]*turnData) // date -> traceID -> turnData

	for d := from; !d.After(to); d = d.AddDate(0, 0, 1) {
		dateStr := d.Format("2006-01-02")
		path := filepath.Join("local", fmt.Sprintf("flow_events_%s.jsonl", dateStr))
		f, err := os.Open(path)
		if err != nil {
			continue
		}

		turns := make(map[string]*turnData)
		scanner := bufio.NewScanner(f)
		scanner.Buffer(make([]byte, 256*1024), 256*1024)
		for scanner.Scan() {
			var ev flowEvent
			if json.Unmarshal(scanner.Bytes(), &ev) != nil {
				continue
			}
			tid := ev.TraceID
			if tid == "" {
				continue
			}
			if turns[tid] == nil {
				turns[tid] = &turnData{}
			}
			td := turns[tid]

			// Track version per turn (use first non-empty version seen)
			if ev.Version != "" && td.version == "" {
				td.version = ev.Version
				versionSet[ev.Version] = true
			}

			if ev.Node == "lifecycle_end" && ev.DurationMs > 0 {
				td.durationMs = ev.DurationMs
			}
			if ev.Node == "token_usage" && ev.Data != nil {
				if v, ok := ev.Data["total_tokens"]; ok {
					td.tokens += toInt(v)
				}
				if v, ok := ev.Data["input_tokens"]; ok {
					td.tokensIn += toInt(v)
				}
				if v, ok := ev.Data["output_tokens"]; ok {
					td.tokensOut += toInt(v)
				}
				if v, ok := ev.Data["cache_read_tokens"]; ok {
					td.cacheRead += toInt(v)
				}
				if v, ok := ev.Data["cache_write_tokens"]; ok {
					td.cacheWrite += toInt(v)
				}
			}
			if ev.Node == "tool_call" {
				td.toolCalls++
			}
		}
		f.Close()

		if len(turns) > 0 {
			allDates = append(allDates, dateStr)
			dayTurns[dateStr] = turns
		}
	}

	// Aggregate per (date, version)
	type resultRow struct {
		Date    string    `json:"date"`
		Version string    `json:"version"`
		Metrics dvMetrics `json:"metrics"`
	}

	var rows []resultRow
	versions := make([]string, 0, len(versionSet))
	for v := range versionSet {
		versions = append(versions, v)
	}
	sort.Strings(versions)
	if len(versions) == 0 {
		versions = []string{"unknown"}
	}

	for _, dateStr := range allDates {
		turns := dayTurns[dateStr]

		// Group turns by version
		grouped := make(map[string][]*turnData)
		for _, td := range turns {
			ver := td.version
			if ver == "" {
				ver = "unknown"
			}
			grouped[ver] = append(grouped[ver], td)
		}

		for ver, tds := range grouped {
			m := dvMetrics{TurnCount: len(tds)}
			var durations []float64
			for _, td := range tds {
				if td.durationMs > 0 {
					durations = append(durations, float64(td.durationMs))
				}
				m.TokensTotal += td.tokens
				m.TokensInput += td.tokensIn
				m.TokensOutput += td.tokensOut
				// Billed: cache read costs 10% of input price
				m.TokensBilled += td.tokensIn + td.cacheWrite + td.cacheRead/10 + td.tokensOut
				if td.toolCalls > m.InnerMax {
					m.InnerMax = td.toolCalls
				}
				m.InnerAvg += float64(td.toolCalls)
			}
			if m.TurnCount > 0 {
				m.TokensAvg = float64(m.TokensTotal) / float64(m.TurnCount)
				m.InnerAvg = m.InnerAvg / float64(m.TurnCount)
			}
			if len(durations) > 0 {
				sort.Float64s(durations)
				m.DurationAvg = avg(durations)
				m.DurationP50 = percentile(durations, 50)
				m.DurationP95 = percentile(durations, 95)
			}
			rows = append(rows, resultRow{Date: dateStr, Version: ver, Metrics: m})
		}
	}

	if rows == nil {
		rows = []resultRow{}
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Date != rows[j].Date {
			return rows[i].Date < rows[j].Date
		}
		return rows[i].Version < rows[j].Version
	})

	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"rows":     rows,
		"dates":    allDates,
		"versions": versions,
	}))
}

func toInt(v any) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case json.Number:
		i, _ := n.Int64()
		return int(i)
	}
	return 0
}

func avg(vals []float64) float64 {
	sum := 0.0
	for _, v := range vals {
		sum += v
	}
	return sum / float64(len(vals))
}

func percentile(sorted []float64, p float64) float64 {
	if len(sorted) == 0 {
		return 0
	}
	rank := p / 100.0 * float64(len(sorted)-1)
	lower := int(math.Floor(rank))
	upper := int(math.Ceil(rank))
	if lower == upper || upper >= len(sorted) {
		return sorted[lower]
	}
	frac := rank - float64(lower)
	return sorted[lower]*(1-frac) + sorted[upper]*frac
}

// Events streams monitor events via SSE.
func (h *OpenClawHandler) Events(c *gin.Context) {
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no") // disable nginx buffering

	sub, unsub := h.monitorBus.Subscribe()
	defer unsub()

	c.Stream(func(w io.Writer) bool {
		select {
		case evt := <-sub:
			data, _ := json.Marshal(evt)
			c.SSEvent("message", string(data))
			return true
		case <-c.Request.Context().Done():
			return false
		}
	})
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

// ConfigJSON returns the raw openclaw.json contents for the gw-config UI.
func (h *OpenClawHandler) ConfigJSON(c *gin.Context) {
	data, err := h.agentGateway.GetConfigJSON()
	if err != nil {
		c.JSON(http.StatusOK, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(data))
}
