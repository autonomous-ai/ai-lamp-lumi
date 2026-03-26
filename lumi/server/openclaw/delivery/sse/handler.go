package sse

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/server/serializers"
)

// OpenClawHandler handles OpenClaw gateway WebSocket events and exposes monitor endpoints.
type OpenClawHandler struct {
	agentGateway domain.AgentGateway
	monitorBus   *monitor.Bus
}

// ProvideOpenClawHandler returns an OpenClaw events handler.
func ProvideOpenClawHandler(gw domain.AgentGateway, bus *monitor.Bus) OpenClawHandler {
	return OpenClawHandler{agentGateway: gw, monitorBus: bus}
}

// HandleEvent processes incoming WebSocket events from the OpenClaw gateway.
func (h *OpenClawHandler) HandleEvent(ctx context.Context, evt domain.WSEvent) error {
	log.Printf("OpenClawHandler event: %s", evt.Event)

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
			log.Printf("[agent] lifecycle: phase=%s runId=%s session=%s",
				payload.Data.Phase, payload.RunID, payload.SessionKey)
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
			log.Printf("[agent] tool: %s phase=%s runId=%s", toolName, payload.Data.Phase, payload.RunID)
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
		}

	case "chat":
		var payload domain.ChatPayload
		if err := json.Unmarshal(evt.Payload, &payload); err != nil {
			log.Printf("[agent] chat parse error: %v", err)
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
			log.Printf("[agent] chat response (final): %s", payload.Message[:min(len(payload.Message), 100)])
			go func() {
				if err := h.agentGateway.SendToLeLampTTS(payload.Message); err != nil {
					log.Printf("[agent] TTS delivery failed: %v", err)
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
