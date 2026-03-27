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
	}
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

		switch payload.Stream {
		case "lifecycle":
			slog.Info("lifecycle event", "component", "agent", "phase", payload.Data.Phase, "runId", payload.RunID, "session", payload.SessionKey)

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
						"run_id":            payload.RunID,
						"input_tokens":      u.InputTokens,
						"output_tokens":     u.OutputTokens,
						"cache_read_tokens": u.CacheReadTokens,
						"cache_write_tokens": u.CacheWriteTokens,
						"total_tokens":      u.TotalTokens,
					})
				} else {
					slog.Warn("no usage data in lifecycle end", "component", "agent", "runId", payload.RunID)
				}
			}

			flow.Log("lifecycle_"+payload.Data.Phase, map[string]any{"run_id": payload.RunID, "error": payload.Data.Error})
			monEvt := domain.MonitorEvent{
				Type:    "lifecycle",
				Summary: fmt.Sprintf("Agent %s", payload.Data.Phase),
				RunID:   payload.RunID,
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
			flow.Log("tool_call", map[string]any{"tool": toolName, "phase": payload.Data.Phase, "run_id": payload.RunID})
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "tool_call",
				Summary: summary,
				RunID:   payload.RunID,
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
					RunID:   payload.RunID,
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
					RunID:   payload.RunID,
				})
			}

			// When the agent turn ends, the final assistant text should be spoken.
			// Accumulate deltas per runId and send to TTS when lifecycle "end" arrives.
			h.accumulateAssistantDelta(payload.RunID, delta)

		}

		// When agent lifecycle ends, flush accumulated assistant text to TTS
		if payload.Stream == "lifecycle" && payload.Data.Phase == "end" {
			if text := h.flushAssistantText(payload.RunID); text != "" {
				slog.Info("assistant turn done, sending to TTS", "component", "agent", "text", text[:min(len(text), 100)])
				flow.Log("tts_send", map[string]any{"run_id": payload.RunID, "text": text[:min(len(text), 100)]})
				go func(t string) {
					if err := h.agentGateway.SendToLeLampTTS(t); err != nil {
						slog.Error("TTS delivery failed", "component", "agent", "error", err)
					}
					flow.ClearTrace() // turn complete
				}(text)
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

		// Inbound user message from Telegram/Slack/Discord → start a new flow trace
		if payload.State == "final" && payload.Role == "user" && payload.RunID != "" {
			msg := payload.Message
			if len(msg) > 100 {
				msg = msg[:100]
			}
			flow.SetTrace(payload.RunID)
			flow.Log("chat_input", map[string]any{"run_id": payload.RunID, "message": msg})
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "chat_input",
				Summary: "[telegram] " + msg,
				RunID:   payload.RunID,
				Detail:  map[string]string{"role": "user"},
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

		// Only forward final assistant messages to TTS
		if payload.State == "final" && payload.Role == "assistant" && payload.Message != "" {
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

// Recent returns the last N monitor events.
func (h *OpenClawHandler) Recent(c *gin.Context) {
	events := h.monitorBus.Recent(100)
	if events == nil {
		events = []domain.MonitorEvent{}
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(events))
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
