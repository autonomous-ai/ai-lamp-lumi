package sse

import (
	"context"
	"encoding/json"
	"log"

	"go-lamp.autonomous.ai/domain"
)

// OpenClawHandler handles OpenClaw gateway WebSocket events.
type OpenClawHandler struct{}

// ProvideOpenClawHandler returns an OpenClaw events handler.
func ProvideOpenClawHandler() OpenClawHandler {
	return OpenClawHandler{}
}

// HandleEvent processes incoming WebSocket events from the OpenClaw gateway.
func (h *OpenClawHandler) HandleEvent(ctx context.Context, evt domain.WSEvent) error {
	log.Printf("OpenClawHandler event: %s", evt.Event)
	if evt.Event != "agent" {
		return nil
	}
	var payload domain.AgentPayload
	if err := json.Unmarshal(evt.Payload, &payload); err != nil {
		return err
	}
	if payload.Stream == "lifecycle" {
		log.Printf("[openclaw] lifecycle: phase=%s runId=%s session=%s",
			payload.Data.Phase, payload.RunID, payload.SessionKey)
	}
	return nil
}
