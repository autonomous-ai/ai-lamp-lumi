package sse

import (
	"context"
	"encoding/json"
	"log"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/openclaw"
)

// OpenClawHandler handles OpenClaw gateway WebSocket events.
type OpenClawHandler struct {
	openclawService *openclaw.Service
}

// ProvideOpenClawHandler returns an OpenClaw events handler.
func ProvideOpenClawHandler(svc *openclaw.Service) OpenClawHandler {
	return OpenClawHandler{openclawService: svc}
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
		if payload.Stream == "lifecycle" {
			log.Printf("[openclaw] lifecycle: phase=%s runId=%s session=%s",
				payload.Data.Phase, payload.RunID, payload.SessionKey)
			// Capture session key from the first lifecycle event
			if payload.SessionKey != "" && h.openclawService.GetSessionKey() == "" {
				h.openclawService.SetSessionKey(payload.SessionKey)
			}
		}

	case "chat":
		var payload domain.ChatPayload
		if err := json.Unmarshal(evt.Payload, &payload); err != nil {
			log.Printf("[openclaw] chat parse error: %v", err)
			return nil
		}
		// Only forward final assistant messages to TTS
		if payload.State == "final" && payload.Role == "assistant" && payload.Message != "" {
			log.Printf("[openclaw] chat response (final): %s", payload.Message[:min(len(payload.Message), 100)])
			go func() {
				if err := h.openclawService.SendToLeLampTTS(payload.Message); err != nil {
					log.Printf("[openclaw] TTS delivery failed: %v", err)
				}
			}()
		}
	}

	return nil
}
