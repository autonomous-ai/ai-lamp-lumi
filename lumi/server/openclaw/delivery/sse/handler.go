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
// (e.g. "NO_REPLY", "NO_RE"). The gateway emits these when the agent decides not
// to respond; they should never be spoken aloud or shown to the user.
func isAgentNoReply(text string) bool {
	t := strings.TrimSpace(strings.ToUpper(text))
	return strings.HasPrefix(t, "NO_RE")
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
			}
		}

		// Resolve OpenClaw UUID → device ID for consistent flow tracing across all agent events
		flowRunID := h.resolveRunID(payload.RunID)

		switch payload.Stream {
		case "lifecycle":
			slog.Info("lifecycle event", "component", "agent", "phase", payload.Data.Phase, "runId", payload.RunID, "flowRunId", flowRunID, "session", payload.SessionKey)

			// Detect Telegram/channel-initiated turns: lifecycle_start arrives without an active
			// sensing trace (device didn't initiate via chat.send — OpenClaw received externally).
			// Skip if run_id looks like a device-originated sensing turn (lumi-sensing-*) —
			// these can appear traceless after a server restart but are NOT from Telegram.
			if payload.Data.Phase == "start" && payload.RunID != "" && flow.GetTrace() == "" &&
				!strings.HasPrefix(payload.RunID, "lumi-sensing-") && !strings.HasPrefix(flowRunID, "lumi-sensing-") {
				h.appendDebugJSONL(map[string]any{
					"source":      "agent.lifecycle_start_fallback_chat_input",
					"run_id":      payload.RunID,
					"stream":      payload.Stream,
					"phase":       payload.Data.Phase,
					"raw_payload": string(evt.Payload),
				})
				flow.Log("chat_input", map[string]any{"run_id": payload.RunID, "source": "channel"}, payload.RunID)
				h.monitorBus.Push(domain.MonitorEvent{
					Type:    "chat_input",
					Summary: "[telegram]",
					RunID:   payload.RunID,
					Detail:  map[string]string{"role": "user"},
				})
			}

			// Status LED: show processing state while agent is thinking
			if payload.Data.Phase == "start" {
				h.statusLED.Set(statusled.StateProcessing)
			} else if payload.Data.Phase == "end" {
				h.statusLED.Clear(statusled.StateProcessing)
			}

			// Log raw payload on lifecycle end for token usage debugging
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
					slog.Warn("no usage data in lifecycle end", "component", "agent", "runId", payload.RunID)
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

		case "tool":
			toolName := payload.Data.Tool
			summary := toolName
			if payload.Data.Phase == "start" {
				summary = fmt.Sprintf("Tool %s started", toolName)
				// Detect music playback tool calls so we can suppress TTS on turn end.
				// The Music skill uses Bash+curl to POST /audio/play.
				if strings.Contains(payload.Data.ToolArgs, "/audio/play") {
					h.markMusicTurn(payload.RunID)
					slog.Info("music tool detected, TTS will be suppressed for this turn", "component", "agent", "runId", payload.RunID)
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
					"args": payload.Data.ToolArgs,
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
			if text := h.flushAssistantText(payload.RunID); text != "" && !isAgentNoReply(text) {
				if musicPlaying {
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

	case "chat":
		slog.Debug("chat raw payload", "component", "agent", "payload", string(evt.Payload))
		var payload domain.ChatPayload
		if err := json.Unmarshal(evt.Payload, &payload); err != nil {
			slog.Error("chat parse error", "component", "agent", "error", err, "raw", string(evt.Payload))
			return nil
		}
		payload.ResolveChatMessage()
		h.appendDebugJSONL(map[string]any{
			"source":       "chat_event",
			"run_id":       payload.RunID,
			"role":         payload.Role,
			"state":        payload.State,
			"session_key":  payload.SessionKey,
			"message":      payload.Message,
			"raw_message":  string(payload.RawMessage),
			"raw_payload":  string(evt.Payload),
		})

		// Inbound user message from Telegram/Slack/Discord
		if payload.State == "final" && payload.Role == "user" && payload.RunID != "" {
			flow.Log("chat_input", map[string]any{"run_id": payload.RunID, "message": payload.Message}, payload.RunID)
			displayMsg := payload.Message
			if len(displayMsg) > 200 {
				displayMsg = displayMsg[:200] + "…"
			}
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "chat_input",
				Summary: "[telegram] " + displayMsg,
				RunID:   payload.RunID,
				Detail:  map[string]string{"role": "user", "message": payload.Message},
			})
		}

		// Push assistant/partial chat events to monitor (skip inbound user messages — already tracked as chat_input)
		if payload.Role != "user" {
			summary := payload.Message
			if len(summary) > 120 {
				summary = summary[:120] + "..."
			}
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "chat_response",
				Summary: summary,
				RunID:   payload.RunID,
				State:   payload.State,
				Detail: map[string]string{
					"role":    payload.Role,
					"message": payload.Message,
				},
			})
		}

		// TODO(double-tts): This path sends TTS from the chat stream's final assistant message.
		// The agent stream's lifecycle_end handler (above) ALSO flushes accumulated assistant
		// deltas to TTS. When both streams carry the same response, the device speaks it twice.
		// Fix: deduplicate with a per-runID "tts already sent" guard, or remove one path.
		if payload.State == "final" && payload.Role == "assistant" && payload.Message != "" && !isAgentNoReply(payload.Message) {
			slog.Info("chat response (final)", "component", "agent", "message", payload.Message[:min(len(payload.Message), 100)])
			go func() {
				if err := h.agentGateway.SendToLeLampTTS(payload.Message); err != nil {
					slog.Error("TTS delivery failed", "component", "agent", "error", err)
				}
			}()
		}
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

// recentFlowFromJSONL reads the last n lines from flow JSONL for a given date (YYYY-MM-DD)
// and converts them to MonitorEvents.
func recentFlowFromJSONL(day string, n int) []domain.MonitorEvent {
	path := filepath.Join("local", fmt.Sprintf("flow_events_%s.jsonl", day))
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()

	// Read all lines (flow files are typically <10MB)
	var lines []string
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 256*1024)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
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
// Query param ?date=YYYY-MM-DD selects a historical file; defaults to today.
func (h *OpenClawHandler) FlowLogs(c *gin.Context) {
	date := c.Query("date")
	if date == "" {
		date = time.Now().Format("2006-01-02")
	}
	path := fmt.Sprintf("local/flow_events_%s.jsonl", date)
	f, err := os.Open(path)
	if err != nil {
		c.JSON(http.StatusNotFound, serializers.ResponseError("no log for date: "+date))
		return
	}
	defer f.Close()
	filename := fmt.Sprintf("lumi_flow_%s.jsonl", date)
	c.Header("Content-Disposition", "attachment; filename="+filename)
	c.Header("Content-Type", "application/x-ndjson")
	io.Copy(c.Writer, f) //nolint:errcheck
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

// DebugLogs serves the OpenClaw raw debug payload log file for download.
func (h *OpenClawHandler) DebugLogs(c *gin.Context) {
	path := filepath.Join("local", "openclaw_debug_payloads.jsonl")
	f, err := os.Open(path)
	if err != nil {
		c.JSON(http.StatusNotFound, serializers.ResponseError("no debug log file"))
		return
	}
	defer f.Close()
	c.Header("Content-Disposition", "attachment; filename=openclaw_debug_payloads.jsonl")
	c.Header("Content-Type", "application/x-ndjson")
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
