package http

import (
	"fmt"
	"log/slog"
	"net/http"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/intent"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/internal/statusled"
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
	statusLED    *statusled.Service
}

// ProvideSensingHandler constructs a SensingHandler.
func ProvideSensingHandler(gw domain.AgentGateway, bus *monitor.Bus, cfg *config.Config, sled *statusled.Service) SensingHandler {
	return SensingHandler{agentGateway: gw, monitorBus: bus, config: cfg, statusLED: sled}
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

	// Light up listening LED only when wake word is confirmed (voice_command).
	// Do NOT set on voice_listening — that fires for every STT session (any RMS spike),
	// not just wake word interactions, causing false cyan after agent responds.
	if req.Type == "voice_command" {
		slog.Info("listening LED set", "component", "statusled", "reason", req.Type, "message", req.Message)
		h.statusLED.Set(statusled.StateListening)
	}
	// voice_listening / voice_listening_end are internal LED signals — don't forward to agent.
	if req.Type == "voice_listening" {
		c.JSON(http.StatusOK, serializers.ResponseSuccess(nil))
		return
	}
	if req.Type == "voice_listening_end" {
		// Mic session closed — safe to clear listening LED here: STT is done but agent
		// hasn't made any tool calls yet, so StopEffect won't race with LED changes.
		slog.Info("listening LED cleared", "component", "statusled", "reason", "voice_listening_end")
		h.statusLED.Clear(statusled.StateListening)
		c.JSON(http.StatusOK, serializers.ResponseSuccess(nil))
		return
	}

	startPayload := map[string]any{"type": req.Type, "message": req.Message}

	// Push sensing input to monitor.
	monitorDetail := map[string]any{"type": req.Type}
	h.monitorBus.Push(domain.MonitorEvent{
		Type:    "sensing_input",
		Summary: "[" + req.Type + "] " + req.Message,
		Detail:  monitorDetail,
	})

	// Voice commands: try local intent matching first for instant response
	if (req.Type == "voice" || req.Type == "voice_command") && h.config.LocalIntentEnabled() {
		if result := intent.Match(req.Message); result != nil {
			// Generate a dedicated local-intent trace ID so this turn doesn't
			// share the global trace of an in-flight agent turn.
			localRunID := fmt.Sprintf("local-intent-%d", time.Now().UnixMilli())
			turnStart := flow.Start("sensing_input", startPayload, localRunID)
			flow.Log("intent_match", map[string]any{"message": req.Message, "tts": result.TTSText, "rule": result.Rule, "actions": result.Actions}, localRunID)
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
			if result.Emotion != "" {
				h.monitorBus.Push(domain.MonitorEvent{Type: "emotion", Summary: result.Emotion})
			}
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "intent_match",
				Summary: "[local] " + req.Message + " → " + result.TTSText,
			})
			// Local intent handled — clear listening LED now (no lifecycle_start will come).
			h.statusLED.Clear(statusled.StateListening)
			flow.End("sensing_input", turnStart, map[string]any{"path": "local"}, localRunID)
			c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{
				"handler":  "local",
				"response": result.TTSText,
			}))
			return
		}
	}

	// Drop passive sensing events while agent is processing another turn.
	// Voice commands always pass through — the user is explicitly speaking.
	isPassive := req.Type != "voice" && req.Type != "voice_command"
	if isPassive && h.agentGateway.IsBusy() {
		slog.Info("sensing event dropped — agent busy", "component", "sensing", "type", req.Type)
		c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{"handler": "dropped"}))
		return
	}

	// Guard mode: also broadcast stranger/motion alerts to all chat sessions.
	// Normal flow continues — agent still does emotion, servo, TTS as usual.
	if isPassive && h.config.GuardModeEnabled() && (req.Type == "presence.enter" || req.Type == "motion") {
		slog.Info("guard mode broadcast", "component", "sensing", "type", req.Type)
		go func() {
			if err := h.agentGateway.BroadcastAlert("[guard:"+req.Type+"] "+req.Message, req.Image); err != nil {
				slog.Error("guard broadcast failed", "component", "sensing", "err", err)
			}
		}()
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

	var msg string
	if req.Type == "voice" || req.Type == "voice_command" {
		// Voice input is a human speaking — always respond conversationally.
		msg = req.Message
	} else {
		// Passive sensing (sound, motion, light, presence) — agent may choose not to respond.
		msg = "[sensing:" + req.Type + "] " + req.Message
	}

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

// MonitorEventRequest is the payload for pushing an event to the monitor bus.
type MonitorEventRequest struct {
	Type    string         `json:"type" validate:"required"`
	Summary string         `json:"summary" validate:"required"`
	Detail  map[string]any `json:"detail,omitempty"`
	RunID   string         `json:"runId,omitempty"`
}

// PostMonitorEvent allows internal services (e.g. LeLamp) to push events to the monitor bus.
func (h *SensingHandler) PostMonitorEvent(c *gin.Context) {
	var req MonitorEventRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	if err := validator.New().Struct(req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	h.monitorBus.Push(domain.MonitorEvent{
		Type:    req.Type,
		Summary: req.Summary,
		Detail:  req.Detail,
		RunID:   req.RunID,
	})
	c.JSON(http.StatusOK, serializers.ResponseSuccess(nil))
}

// EnableGuard activates guard mode.
func (h *SensingHandler) EnableGuard(c *gin.Context) {
	t := true
	h.config.GuardMode = &t
	if err := h.config.Save(); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	slog.Info("guard mode enabled", "component", "sensing")
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]bool{"guard_mode": true}))
}

// DisableGuard deactivates guard mode.
func (h *SensingHandler) DisableGuard(c *gin.Context) {
	f := false
	h.config.GuardMode = &f
	if err := h.config.Save(); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	slog.Info("guard mode disabled", "component", "sensing")
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]bool{"guard_mode": false}))
}

// GetGuardStatus returns the current guard mode state.
func (h *SensingHandler) GetGuardStatus(c *gin.Context) {
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]bool{
		"guard_mode": h.config.GuardModeEnabled(),
	}))
}

// GuardAlertRequest is the payload for manually triggering a guard broadcast.
type GuardAlertRequest struct {
	Message string `json:"message" validate:"required"`
	Image   string `json:"image,omitempty"`
}

// PostGuardAlert broadcasts an alert message to all chat sessions.
func (h *SensingHandler) PostGuardAlert(c *gin.Context) {
	var req GuardAlertRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	if err := validator.New().Struct(req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	if err := h.agentGateway.BroadcastAlert(req.Message, req.Image); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(nil))
}

// GetSnapshot serves a sensing snapshot image from /tmp/lumi-sensing-snapshots/.
func (h *SensingHandler) GetSnapshot(c *gin.Context) {
	name := c.Param("name")
	if !strings.HasPrefix(name, "sensing_") || !strings.HasSuffix(name, ".jpg") {
		c.Status(http.StatusNotFound)
		return
	}
	path := filepath.Join("/tmp/lumi-sensing-snapshots", name)
	c.File(path)
}
