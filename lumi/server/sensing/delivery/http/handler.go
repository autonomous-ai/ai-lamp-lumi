package http

import (
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/intent"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/lib/flow"
	"go-lamp.autonomous.ai/server/config"
	"go-lamp.autonomous.ai/server/serializers"
)

// SensingEventRequest is the payload from LeLamp sensing detectors.
type SensingEventRequest struct {
	// Type is the event category: motion, sound, presence.enter, presence.leave, light.level, etc.
	Type string `json:"type" validate:"required"`
	// Message is a natural-language description of what was detected.
	Message string `json:"message" validate:"required"`
	// Image is an optional base64-encoded JPEG snapshot from the camera.
	// Attached automatically for significant events (large motion, face detected) so AI can see.
	Image string `json:"image,omitempty"`
}

// SensingHandler handles incoming sensing events from LeLamp and forwards them to the agent.
type SensingHandler struct {
	agentGateway domain.AgentGateway
	monitorBus   *monitor.Bus
	config       *config.Config
}

// ProvideSensingHandler constructs a SensingHandler.
func ProvideSensingHandler(gw domain.AgentGateway, bus *monitor.Bus, cfg *config.Config) SensingHandler {
	return SensingHandler{agentGateway: gw, monitorBus: bus, config: cfg}
}

// PostEvent receives a sensing event and sends it to the agent as a chat message.
// Voice events are first checked against local intent rules for instant response.
func (h *SensingHandler) PostEvent(c *gin.Context) {
	var req SensingEventRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	if err := validator.New().Struct(req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}

	slog.Info("sensing event received", "component", "sensing", "type", req.Type, "message", req.Message)

	startPayload := map[string]any{"type": req.Type, "message": req.Message}

	// Push sensing input to monitor
	h.monitorBus.Push(domain.MonitorEvent{
		Type:    "sensing_input",
		Summary: "[" + req.Type + "] " + req.Message,
	})

	// Voice commands: try local intent matching first for instant response
	if (req.Type == "voice" || req.Type == "voice_command") && h.config.LocalIntentEnabled() {
		if result := intent.Match(req.Message); result != nil {
			turnStart := flow.Start("sensing_input", startPayload)
			flow.Log("intent_match", map[string]any{"message": req.Message, "tts": result.TTSText})
			if result.TTSText != "" {
				go func() {
					resp, err := http.Post(
						"http://127.0.0.1:5001/voice/speak",
						"application/json",
						strings.NewReader(`{"text":"`+result.TTSText+`"}`),
					)
					if err == nil {
						resp.Body.Close()
					}
				}()
			}
			// Signal ambient service about LED state changes
			if result.LEDChanged {
				h.monitorBus.Push(domain.MonitorEvent{Type: "led_set", Summary: "intent: " + req.Message})
			} else if result.LEDOff {
				h.monitorBus.Push(domain.MonitorEvent{Type: "led_off", Summary: "intent: " + req.Message})
			}
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "intent_match",
				Summary: "[local] " + req.Message + " → " + result.TTSText,
			})
			flow.End("sensing_input", turnStart, map[string]any{"path": "local"})
			c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{
				"handler": "local",
			}))
			return
		}
	}

	// No local match — forward to OpenClaw agent
	if !h.agentGateway.IsReady() {
		turnStart := flow.Start("sensing_input", startPayload)
		flow.End("sensing_input", turnStart, map[string]any{"error": "agent not connected"})
		c.JSON(http.StatusServiceUnavailable, serializers.ResponseError("agent gateway not connected"))
		return
	}

	// Same run_id as chat.send / JSONL: SetTrace before flow.Start so enter matches this turn (not previous).
	reqID, runID := h.agentGateway.NextChatRunID()
	flow.SetTrace(runID)
	// Important: pass explicit runID to flow.Start to avoid global trace race (another goroutine may interleave
	// between SetTrace() and Start()).
	turnStart := flow.Start("sensing_input", startPayload, runID)

	msg := "[sensing:" + req.Type + "] " + req.Message

	var err error
	if req.Image != "" {
		// Send with image attachment so AI can see what triggered the event
		_, err = h.agentGateway.SendChatMessageWithImageAndRun(msg, req.Image, reqID, runID)
	} else {
		_, err = h.agentGateway.SendChatMessageWithRun(msg, reqID, runID)
	}

	if err != nil {
		slog.Error("failed to send event", "component", "sensing", "error", err)
		flow.End("sensing_input", turnStart, map[string]any{"error": err.Error()})
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}

	flow.End("sensing_input", turnStart, map[string]any{"path": "agent", "run_id": runID}, runID)
	flow.Log("agent_call", map[string]any{"type": req.Type, "run_id": runID}, runID)

	slog.Info("flow correlation", "op", "lelamp_agent_out", "section", "lelamp_to_openclaw",
		"device_run_id", runID, "sensing_type", req.Type,
		"note", "OpenClaw lifecycle UUID maps to device_run_id on lifecycle_start in SSE handler")
	slog.Info("event forwarded", "component", "sensing", "type", req.Type, "hasImage", req.Image != "", "runId", runID)
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{
		"runId": runID,
	}))
}
