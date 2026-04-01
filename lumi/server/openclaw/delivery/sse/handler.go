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

	// musicTurns tracks runIDs where /audio/play was invoked so we can
	// suppress TTS on lifecycle end (speaker is shared — TTS would collide with music).
	musicMu    sync.Mutex
	musicTurns map[string]bool

	// runIDMap maps OpenClaw-assigned UUIDs back to device-originated idempotencyKeys.
	// When lifecycle_start arrives with UUID while a device trace is active, we store
	// the mapping so all subsequent events for that UUID use the device ID for flow tracing.
	runIDMapMu sync.Mutex
	runIDMap   map[string]string // OpenClaw UUID → device idempotencyKey

	debugMu sync.Mutex
}

// ProvideOpenClawHandler returns an OpenClaw events handler.
func ProvideOpenClawHandler(gw domain.AgentGateway, bus *monitor.Bus, sled *statusled.Service) OpenClawHandler {
	// Init flow emitter here so ws_connect events (fired from StartWS before any HTTP request)
	// are broadcast to SSE. Lumi is a single-user device so the global trace ID is sufficient;
	// concurrent turn interleaving is not a concern in normal operation.
	flow.Init(bus, config.LumiVersion)
	return OpenClawHandler{
		agentGateway: gw,
		monitorBus:   bus,
		statusLED:    sled,
		assistantBuf: make(map[string]*strings.Builder),
		musicTurns:   make(map[string]bool),
		runIDMap:     make(map[string]string),
	}
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

// flushAssistantText returns the accumulated text for runId and clears the buffer.
func (h *OpenClawHandler) flushAssistantText(runID string) string {
	h.assistantMu.Lock()
	defer h.assistantMu.Unlock()
	buf, ok := h.assistantBuf[runID]
	if !ok || buf.Len() == 0 {
		return ""
	}
	text := strings.TrimSpace(buf.String())
	delete(h.assistantBuf, runID)
	return text
}

// markMusicTurn flags a runID as having triggered music playback.
func (h *OpenClawHandler) markMusicTurn(runID string) {
	h.musicMu.Lock()
	defer h.musicMu.Unlock()
	h.musicTurns[runID] = true
}

// clearMusicTurn removes the music flag for a runID and returns whether it was set.
func (h *OpenClawHandler) clearMusicTurn(runID string) bool {
	h.musicMu.Lock()
	defer h.musicMu.Unlock()
	was := h.musicTurns[runID]
	delete(h.musicTurns, runID)
	return was
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

// appendDebugJSONL appends a JSON object into local/openclaw_debug_payloads.jsonl.
// Best-effort only: logging failures must not break event handling.
func (h *OpenClawHandler) appendDebugJSONL(record map[string]any) {
	h.debugMu.Lock()
	defer h.debugMu.Unlock()

	record["at"] = time.Now().UTC().Format(time.RFC3339Nano)
	path := filepath.Join("local", "openclaw_debug_payloads.jsonl")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()

	b, err := json.Marshal(record)
	if err != nil {
		return
	}
	_, _ = f.Write(append(b, '\n'))
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
		// If a device trace is active, OpenClaw's UUID should resolve to it for all events in this turn.
		if payload.Stream == "lifecycle" && payload.Data.Phase == "start" && payload.RunID != "" {
			if deviceTrace := flow.GetTrace(); deviceTrace != "" && deviceTrace != payload.RunID {
				h.mapRunID(payload.RunID, deviceTrace)
				slog.Info("mapped OpenClaw runId to device trace", "component", "agent", "openclawId", payload.RunID, "deviceId", deviceTrace)
				slog.Info("flow correlation", "op", "openclaw_uuid_map", "section", "openclaw",
					"openclaw_run_id", payload.RunID, "device_run_id", deviceTrace,
					"note", "JSONL/monitor use device_run_id for this turn")
			}
		}

		// Resolve OpenClaw UUID → device ID for consistent flow tracing across all agent events
		flowRunID := h.resolveRunID(payload.RunID)
		// Full raw dump: persist every OpenClaw agent-stream payload so debugging can reconstruct
		// the exact upstream timeline (lifecycle/tool/thinking/assistant deltas, etc.).
		h.appendDebugJSONL(map[string]any{
			"source":      "openclaw_raw",
			"event":       evt.Event,
			"stream":      payload.Stream,
			"run_id":      payload.RunID,
			"flow_run_id": flowRunID,
			"session_key": payload.SessionKey,
			"phase":       payload.Data.Phase,
			"raw_payload": string(evt.Payload),
		})

		switch payload.Stream {
		case "lifecycle":
			slog.Info("lifecycle event", "component", "agent", "phase", payload.Data.Phase, "runId", payload.RunID, "flowRunId", flowRunID, "session", payload.SessionKey)

			// Detect Telegram/channel-initiated turns: lifecycle_start arrives without an active
			// sensing trace (device didn't initiate via chat.send — OpenClaw received externally).
			// Skip if run_id looks like Lumi-originated chat.send (lumi-chat-* or legacy lumi-sensing-*) —
			// these can appear traceless after a server restart but are NOT from Telegram.
			if payload.Data.Phase == "start" && payload.RunID != "" && flow.GetTrace() == "" &&
				!isLumiOutboundChatRunID(payload.RunID) && !isLumiOutboundChatRunID(flowRunID) {
				h.appendDebugJSONL(map[string]any{
					"source":      "agent.lifecycle_start_fallback_chat_input",
					"run_id":      payload.RunID,
					"stream":      payload.Stream,
					"phase":       payload.Data.Phase,
					"raw_payload": string(evt.Payload),
				})

				// Emit chat_input immediately (no message text yet).
				flow.Log("chat_input", map[string]any{"run_id": payload.RunID, "source": "channel"}, payload.RunID)
				h.monitorBus.Push(domain.MonitorEvent{
					Type:    "chat_input",
					Summary: "[telegram]",
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
					h.appendDebugJSONL(map[string]any{
						"source":       "chat_history_on_channel_turn",
						"run_id":       capturedRunID,
						"session_key":  capturedSessionKey,
						"raw_history":  string(historyPayload),
					})
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
					if userMsg != "" {
						displayMsg := userMsg
						if len(displayMsg) > 200 {
							displayMsg = displayMsg[:200] + "…"
						}
						prefix := "[telegram]"
						if senderLabel != "" {
							prefix = "[telegram:" + senderLabel + "]"
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
			} else if payload.Data.Phase == "end" {
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
						var hist struct {
							Messages []struct {
								Role  string     `json:"role"`
								Usage *histUsage `json:"usage,omitempty"`
							} `json:"messages"`
						}
						if json.Unmarshal(histPayload, &hist) != nil {
							return
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
								break
							}
						}
					}()
				}
			}

			flow.Log("lifecycle_"+payload.Data.Phase, map[string]any{"run_id": flowRunID, "error": payload.Data.Error}, flowRunID)
			monEvt := domain.MonitorEvent{
				Type:    "lifecycle",
				Summary: fmt.Sprintf("Agent %s", payload.Data.Phase),
				RunID:   flowRunID,
				Phase:   payload.Data.Phase,
				Error:   payload.Data.Error,
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
			if payload.Data.Phase == "end" {
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
					h.markMusicTurn(payload.RunID)
					slog.Info("music tool detected, TTS will be suppressed for this turn", "component", "agent", "runId", payload.RunID)
				}
				// Detect LED tool calls so ambient breathing doesn't override agent-set colors.
				if strings.Contains(toolArgs, "/led/solid") ||
					strings.Contains(toolArgs, "/led/effect") ||
					strings.Contains(toolArgs, "/scene") ||
					strings.Contains(toolArgs, "/emotion") {
					h.monitorBus.Push(domain.MonitorEvent{Type: "led_set", Summary: "agent tool: " + toolName})
				}
				if strings.Contains(toolArgs, "/led/off") {
					h.monitorBus.Push(domain.MonitorEvent{Type: "led_off", Summary: "agent tool: " + toolName})
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
		// Suppress TTS if the agent played music this turn (shared speaker).
		if payload.Stream == "lifecycle" && payload.Data.Phase == "end" {
			musicPlaying := h.clearMusicTurn(payload.RunID)
			if text := h.flushAssistantText(payload.RunID); text != "" {
				if isAgentNoReply(text) {
					// NO_REPLY: show on monitor as response but don't speak and don't light TTS node
					slog.Info("agent replied NO_REPLY, skipping TTS", "component", "agent", "run_id", flowRunID)
					flow.Log("no_reply", map[string]any{"run_id": flowRunID}, flowRunID)
					h.monitorBus.Push(domain.MonitorEvent{
						Type:    "chat_response",
						Summary: "[no reply]",
						RunID:   flowRunID,
						State:   "final",
						Detail:  map[string]string{"role": "assistant", "message": "[no reply]"},
					})
				} else if musicPlaying {
					slog.Info("assistant turn done, TTS suppressed (music playing)", "component", "agent", "text", text[:min(len(text), 100)])
					flow.Log("tts_suppressed", map[string]any{"run_id": flowRunID, "reason": "music_playing", "text": text}, flowRunID)
				} else {
					slog.Info("assistant turn done, sending to TTS", "component", "agent", "text", text[:min(len(text), 100)])
					flow.Log("tts_send", map[string]any{"run_id": flowRunID, "text": text}, flowRunID)
					go func(t string) {
						if err := h.agentGateway.SendToLeLampTTS(t); err != nil {
							slog.Error("TTS delivery failed", "component", "agent", "error", err)
						}
					}(text)
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
		// Debug: log raw session.tool payload to identify field mapping issues
		h.appendDebugJSONL(map[string]any{
			"source":      "session_tool_raw",
			"run_id":      payload.RunID,
			"flow_run_id": flowRunID,
			"tool_name":   toolName,
			"tool_args":   toolArgs,
			"phase":       payload.Data.Phase,
			"raw_payload": string(evt.Payload),
		})
		summary := toolName
		if payload.Data.Phase == "start" {
			summary = fmt.Sprintf("Tool %s started", toolName)
			if strings.Contains(toolArgs, "/audio/play") {
				h.markMusicTurn(payload.RunID)
				slog.Info("music tool detected (session.tool), TTS suppressed", "component", "agent", "runId", payload.RunID)
			}
			if strings.Contains(toolArgs, "/led/solid") ||
				strings.Contains(toolArgs, "/led/effect") ||
				strings.Contains(toolArgs, "/scene") ||
				strings.Contains(toolArgs, "/emotion") {
				h.monitorBus.Push(domain.MonitorEvent{Type: "led_set", Summary: "agent tool: " + toolName})
			}
			if strings.Contains(toolArgs, "/led/off") {
				h.monitorBus.Push(domain.MonitorEvent{Type: "led_off", Summary: "agent tool: " + toolName})
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
		// Full raw dump: persist every OpenClaw chat payload as well.
		h.appendDebugJSONL(map[string]any{
			"source":      "openclaw_raw",
			"event":       evt.Event,
			"stream":      "chat",
			"run_id":      payload.RunID,
			"flow_run_id": flowRunID,
			"session_key": payload.SessionKey,
			"role":        payload.Role,
			"state":       payload.State,
			"raw_payload": string(evt.Payload),
		})
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
		h.appendDebugJSONL(map[string]any{
			"source":        "chat_event",
			"run_id":        payload.RunID,
			"flow_run_id":   flowRunID,
			"role":          payload.Role,
			"state":         payload.State,
			"session_key":   payload.SessionKey,
			"message":       payload.Message,
			"raw_message":   string(payload.RawMessage),
			"raw_payload":   string(evt.Payload),
		})

		// (OpenClaw gateway never broadcasts role:"user" on the chat stream.
		// User messages are captured via lifecycle_start + chat.history above.)

		// Push assistant/partial chat events to monitor (user input tracked via lifecycle_start — already tracked as chat_input)
		if payload.Role != "user" {
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
	}

	return nil
}

// Status returns the current agent connection status.
func (h *OpenClawHandler) Status(c *gin.Context) {
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"name":       h.agentGateway.Name(),
		"connected":  h.agentGateway.IsReady(),
		"sessionKey": h.agentGateway.GetSessionKey() != "",
	}))
}

// Recent returns the latest flow events from today's JSONL file only.
// This keeps Flow UI deterministic by using a single source of truth (file log).
func (h *OpenClawHandler) Recent(c *gin.Context) {
	events := recentFlowFromJSONL(time.Now().Format("2006-01-02"), 500)
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
	scanner.Buffer(make([]byte, 0, 64*1024), 256*1024)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return lines, nil
}

// recentFlowFromJSONL reads the last n lines from flow JSONL for a given date (YYYY-MM-DD)
// and converts them to MonitorEvents.
func recentFlowFromJSONL(day string, n int) []domain.MonitorEvent {
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
		ev := flowEventToMonitor(fe)
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
	if last > 2000 {
		last = 2000
	}
	events := recentFlowFromJSONL(day, last)
	if events == nil {
		events = []domain.MonitorEvent{}
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
				events := recentFlowFromJSONL(day, 500)
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
func flowEventToMonitor(fe flow.Event) domain.MonitorEvent {
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
			summary = fmt.Sprintf("[telegram] %s", msg)
		} else {
			summary = "[telegram]"
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

// ClearDebugLogs truncates the raw OpenClaw debug payload JSONL file.
func (h *OpenClawHandler) ClearDebugLogs(c *gin.Context) {
	path := filepath.Join("local", "openclaw_debug_payloads.jsonl")
	if _, err := os.Stat(path); os.IsNotExist(err) {
		c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
			"cleared": false,
			"file":    path,
			"note":    "file not found",
		}))
		return
	}
	if err := os.Truncate(path, 0); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError("clear debug log failed: "+err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"cleared": true,
		"file":    path,
	}))
}

// DebugLogs serves the OpenClaw raw debug payload log file for download.
// Optional query param: last=<n> to return only the last N lines (default: full file).
func (h *OpenClawHandler) DebugLogs(c *gin.Context) {
	path := filepath.Join("local", "openclaw_debug_payloads.jsonl")

	ts := time.Now().UTC().Format("2006-01-02T15-04-05-000Z")
	c.Header("Content-Disposition", fmt.Sprintf("attachment; filename=openclaw_debug_payloads_%s.jsonl", ts))
	c.Header("Content-Type", "application/x-ndjson")

	// If "last" param is set, tail the file instead of serving the whole thing.
	// Reads from end of file to avoid loading entire file into memory on Pi.
	if s := c.Query("last"); s != "" {
		n, _ := strconv.Atoi(s)
		if n <= 0 {
			n = 500
		}
		if n > 5000 {
			n = 5000
		}
		f, err := os.Open(path)
		if err != nil {
			c.JSON(http.StatusNotFound, serializers.ResponseError("no debug log file"))
			return
		}
		defer f.Close()
		stat, err := f.Stat()
		if err != nil || stat.Size() == 0 {
			c.String(http.StatusOK, "")
			return
		}
		// Read last chunk (estimate ~2KB per line)
		chunkSize := int64(n) * 2048
		if chunkSize > stat.Size() {
			chunkSize = stat.Size()
		}
		buf := make([]byte, chunkSize)
		f.Seek(stat.Size()-chunkSize, 0) //nolint:errcheck
		nr, _ := f.Read(buf)
		buf = buf[:nr]
		lines := strings.Split(string(buf), "\n")
		// Drop first partial line (unless we read from start)
		if chunkSize < stat.Size() && len(lines) > 0 {
			lines = lines[1:]
		}
		// Remove empty trailing line
		for len(lines) > 0 && strings.TrimSpace(lines[len(lines)-1]) == "" {
			lines = lines[:len(lines)-1]
		}
		if len(lines) > n {
			lines = lines[len(lines)-n:]
		}
		c.String(http.StatusOK, strings.Join(lines, "\n")+"\n")
		return
	}

	f, err := os.Open(path)
	if err != nil {
		c.JSON(http.StatusNotFound, serializers.ResponseError("no debug log file"))
		return
	}
	defer f.Close()
	io.Copy(c.Writer, f) //nolint:errcheck
}

// DebugLogLines returns parsed tail lines from openclaw debug payload JSONL.
// Query param: last=<n> (default 200, max 2000)
func (h *OpenClawHandler) DebugLogLines(c *gin.Context) {
	last := 200
	if s := c.Query("last"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			last = n
		}
	}
	if last > 2000 {
		last = 2000
	}
	path := filepath.Join("local", "openclaw_debug_payloads.jsonl")
	f, err := os.Open(path)
	if err != nil {
		c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
			"rows": []map[string]any{},
		}))
		return
	}
	defer f.Close()

	var lines []string
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 512*1024)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	if len(lines) > last {
		lines = lines[len(lines)-last:]
	}
	rows := make([]map[string]any, 0, len(lines))
	for _, line := range lines {
		var row map[string]any
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			continue
		}
		rows = append(rows, row)
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"rows": rows,
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
