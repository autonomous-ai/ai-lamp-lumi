package sse

import (
	"context"
	"encoding/json"
	"log"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/led"
)

// OpenClawHandler runs the OpenClaw gateway WebSocket client with a handler that updates LED from lifecycle events.
type OpenClawHandler struct {
	ledEngine *led.Engine
}

// ProvideOpenClawHandler returns an OpenClaw events handler that uses openclaw.Service.StartWS.
func ProvideOpenClawHandler(ledEngine *led.Engine) OpenClawHandler {
	return OpenClawHandler{
		ledEngine: ledEngine,
	}
}

// Start runs the gateway WebSocket loop via openclaw.Service.StartWS with a handler that drives LED from lifecycle events.
func (h *OpenClawHandler) HandleEvent(ctx context.Context, evt domain.WSEvent) error {
	log.Printf("OpenClawHandler event: %s", evt.Event)
	if evt.Event != "agent" {
		return nil
	}
	var payload domain.AgentPayload
	if err := json.Unmarshal(evt.Payload, &payload); err != nil {
		return err
	}
	if payload.Stream != "lifecycle" {
		return nil
	}
	log.Printf("OpenClaw lifecycle: phase=%s runId=%s session=%s",
		payload.Data.Phase, payload.RunID, payload.SessionKey)
	if h.ledEngine == nil {
		return nil
	}
	switch payload.Data.Phase {
	case "start":
		h.ledEngine.SetState(led.Thinking, "openclaw-lifecycle")
	case "end":
		h.ledEngine.SetState(led.Working, "openclaw-lifecycle")
	case "error":
		h.ledEngine.SetState(led.Error, "openclaw-lifecycle")
	}
	return nil
}
