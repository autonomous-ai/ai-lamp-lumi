package http

import (
	"encoding/base64"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/intent"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/internal/statusled"
	"go-lamp.autonomous.ai/lib/flow"
	"go-lamp.autonomous.ai/lib/mood"
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

	// Track current user for per-user mood logging.
	if req.Type == "presence.enter" {
		if name := extractUserName(req.Message); name != "" {
			mood.SetCurrentUser(name)
		}
	} else if req.Type == "presence.leave" || req.Type == "presence.away" {
		mood.ClearCurrentUser()
	}

	// Log mood-relevant events to dedicated mood history.
	mood.Log(req.Type, 0, req.Message)

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

	// When agent is busy:
	// - voice_command (wake word confirmed) always passes through immediately.
	// - presence.enter / presence.leave are queued and replayed when agent becomes idle.
	// - All other passive events (motion, voice, light.level) are dropped.
	isPassive := req.Type != "voice_command"
	if isPassive && h.agentGateway.IsBusy() {
		if req.Type == "presence.enter" || req.Type == "presence.leave" {
			h.agentGateway.QueuePendingEvent(req.Type, req.Message, req.Image)
			c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{"handler": "queued"}))
			return
		}
		slog.Info("sensing event dropped — agent busy", "component", "sensing", "type", req.Type)
		h.monitorBus.Push(domain.MonitorEvent{
			Type:    "sensing_drop",
			Summary: "[" + req.Type + "] " + req.Message,
			Detail:  map[string]any{"type": req.Type, "reason": "agent_busy"},
		})
		c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{"handler": "dropped"}))
		return
	}

	// Guard mode: mark the run so SSE handler broadcasts the response via Telegram Bot API.
	guardActive := isPassive && h.config.GuardModeEnabled() && (req.Type == "presence.enter" || req.Type == "motion")
	if guardActive {
		slog.Info("guard mode active", "component", "sensing", "type", req.Type)
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
	mood.TrackRun(runID, req.Type)
	flow.SetTrace(runID)

	// Mark this run as guard-active so SSE handler broadcasts the agent response via Telegram.
	if guardActive {
		snap := extractSnapshotPath(req.Message)
		h.agentGateway.MarkGuardRun(runID, snap)
	}
	// Mark music.mood runs for broadcast so the user can confirm via Telegram or voice.
	if req.Type == "music.mood" {
		h.agentGateway.MarkBroadcastRun(runID)
	}
	// Important: pass explicit runID to flow.Start to avoid global trace race (another goroutine may interleave
	// between SetTrace() and Start()).
	turnStart := flow.Start("sensing_input", startPayload, runID)

	var msg string
	if req.Type == "voice_command" {
		// Wake word confirmed — agent always responds conversationally.
		msg = req.Message
	} else if req.Type == "voice" {
		// Ambient speech — no wake word. Agent always reacts (emotion minimum), speaks if relevant.
		msg = "[ambient] " + req.Message
	} else if guardActive {
		// Guard mode: tag so the system broadcasts the response via Telegram.
		// Include custom instruction if the owner provided one when enabling guard mode.
		guardTag := "[sensing:" + req.Type + "][guard-active]"
		if inst := h.config.GuardInstruction; inst != "" {
			guardTag += "[guard-instruction: " + inst + "]"
		}
		msg = guardTag + " " + req.Message
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

// EnableGuardRequest is the optional payload for enabling guard mode.
type EnableGuardRequest struct {
	Instruction string `json:"instruction,omitempty"`
}

// EnableGuard activates guard mode with an optional custom instruction.
func (h *SensingHandler) EnableGuard(c *gin.Context) {
	var req EnableGuardRequest
	// Body is optional — ignore bind errors (empty body is fine).
	_ = c.ShouldBindJSON(&req)

	t := true
	h.config.GuardMode = &t
	h.config.GuardInstruction = req.Instruction
	if err := h.config.Save(); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	slog.Info("guard mode enabled", "component", "sensing", "instruction", req.Instruction)
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"guard_mode":  true,
		"instruction": req.Instruction,
	}))
}

// DisableGuard deactivates guard mode and clears any custom instruction.
func (h *SensingHandler) DisableGuard(c *gin.Context) {
	f := false
	h.config.GuardMode = &f
	h.config.GuardInstruction = ""
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

// PostGuardAlert broadcasts an alert message to all chat sessions (manual alerts only).
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
	var imagePath string
	if req.Image != "" {
		if data, err := base64.StdEncoding.DecodeString(req.Image); err == nil {
			tmp := filepath.Join(os.TempDir(), fmt.Sprintf("guard-alert-%d.jpg", time.Now().UnixMilli()))
			if err := os.WriteFile(tmp, data, 0644); err == nil {
				imagePath = tmp
				defer os.Remove(tmp)
			}
		}
	}
	if err := h.agentGateway.Broadcast(req.Message, imagePath); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(nil))
}

// GetSnapshot serves a sensing snapshot image.
// Checks persistent dir first (/var/log/lumi/snapshots/), falls back to tmp.
func (h *SensingHandler) GetSnapshot(c *gin.Context) {
	name := c.Param("name")
	if !strings.HasPrefix(name, "sensing_") || !strings.HasSuffix(name, ".jpg") {
		c.Status(http.StatusNotFound)
		return
	}
	// Prefer persistent dir (survives reboot), fall back to tmp buffer.
	persistPath := filepath.Join("/var/log/lumi/snapshots", name)
	if _, err := os.Stat(persistPath); err == nil {
		c.File(persistPath)
		return
	}
	tmpPath := filepath.Join("/tmp/lumi-sensing-snapshots", name)
	c.File(tmpPath)
}

// --- Guard helpers ---

var reSnapshotPath = regexp.MustCompile(`\[snapshot:\s*([^\]]+)\]`)

// extractSnapshotPath extracts the snapshot file path from a sensing message.
// reUserName matches "owner (gray)" or "friend (chloe)" in presence.enter messages.
var reUserName = regexp.MustCompile(`(?:owner|friend)\s*\(([^)]+)\)`)

// extractUserName returns the first recognized owner/friend name from a presence.enter message.
func extractUserName(message string) string {
	m := reUserName.FindStringSubmatch(message)
	if m == nil {
		return ""
	}
	return strings.ToLower(strings.TrimSpace(m[1]))
}

func extractSnapshotPath(message string) string {
	m := reSnapshotPath.FindStringSubmatch(message)
	if m == nil {
		return ""
	}
	return strings.TrimSpace(m[1])
}
