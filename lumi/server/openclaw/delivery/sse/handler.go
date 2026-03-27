package sse

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/server/serializers"
)

// OpenClawHandler handles OpenClaw gateway WebSocket events and exposes monitor endpoints.
type OpenClawHandler struct {
	agentGateway domain.AgentGateway
	monitorBus   *monitor.Bus

	// assistantBuf accumulates assistant deltas per runId so we can send the
	// full text to TTS when the agent turn ends (lifecycle "end").
	assistantMu  sync.Mutex
	assistantBuf map[string]*strings.Builder
}

// ProvideOpenClawHandler returns an OpenClaw events handler.
func ProvideOpenClawHandler(gw domain.AgentGateway, bus *monitor.Bus) OpenClawHandler {
	return OpenClawHandler{
		agentGateway: gw,
		monitorBus:   bus,
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
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "lifecycle",
				Summary: fmt.Sprintf("Agent %s", payload.Data.Phase),
				RunID:   payload.RunID,
				Phase:   payload.Data.Phase,
				Error:   payload.Data.Error,
			})

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
			slog.Debug("tool event", "component", "agent", "tool", toolName, "phase", payload.Data.Phase, "runId", payload.RunID)
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
				go func(t string) {
					if err := h.agentGateway.SendToLeLampTTS(t); err != nil {
						slog.Error("TTS delivery failed", "component", "agent", "error", err)
					}
				}(text)
			}
		}

	case "chat":
		var payload domain.ChatPayload
		if err := json.Unmarshal(evt.Payload, &payload); err != nil {
			slog.Error("chat parse error", "component", "agent", "error", err)
			return nil
		}

		// Push all chat events to monitor (partial + final)
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
