package http

import (
	"fmt"
	"log/slog"
	"net/http"
	"path/filepath"
	"strings"
	"sync"
	"time"

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

// soundTracker implements escalating reaction logic for sound sensing events.
//
// Behavior mirrors a living creature hearing noise:
//   - occurrences 1–2: pass through silently (agent expresses emotion only, no speech)
//   - occurrence 3+: marked "persistent" — agent may speak once to comment on the noise
//   - after persistent event: 3-minute suppression so Lumi doesn't keep complaining
//
// A 15-second dedup prevents flooding when LeLamp fires on every audio sample.
// The window resets after 2 minutes of silence.
type soundTracker struct {
	mu            sync.Mutex
	count         int
	windowStart   time.Time
	lastPassed    time.Time
	suppressUntil time.Time
}

const (
	soundDedupeInterval   = 15 * time.Second
	soundWindowDuration   = 2 * time.Minute
	soundPersistentAfter  = 3 // speak after this many occurrences in one window
	soundSuppressDuration = 3 * time.Minute
)

// track processes an incoming sound event and returns whether it should be forwarded to the agent,
// the current occurrence count, and whether this event crossed the persistent threshold.
func (t *soundTracker) track(now time.Time) (send bool, occurrence int, persistent bool) {
	t.mu.Lock()
	defer t.mu.Unlock()

	// Post-speak suppression: drop until cooldown expires.
	if now.Before(t.suppressUntil) {
		return false, 0, false
	}

	// Reset window after silence longer than windowDuration.
	if !t.lastPassed.IsZero() && now.Sub(t.lastPassed) > soundWindowDuration {
		t.count = 0
		t.windowStart = time.Time{}
	}

	// Dedup: forward at most one event per dedupeInterval.
	if !t.lastPassed.IsZero() && now.Sub(t.lastPassed) < soundDedupeInterval {
		return false, 0, false
	}

	if t.windowStart.IsZero() {
		t.windowStart = now
	}
	t.count++
	t.lastPassed = now

	current := t.count
	isPersistent := current >= soundPersistentAfter
	if isPersistent {
		// Agent will speak once; suppress subsequent events for cooldown period.
		t.suppressUntil = now.Add(soundSuppressDuration)
		t.count = 0
		t.windowStart = time.Time{}
	}

	return true, current, isPersistent
}

// SensingHandler handles incoming sensing events from LeLamp and forwards them to the agent.
type SensingHandler struct {
	agentGateway domain.AgentGateway
	monitorBus   *monitor.Bus
	config       *config.Config
	soundTracker *soundTracker
}

// ProvideSensingHandler constructs a SensingHandler.
func ProvideSensingHandler(gw domain.AgentGateway, bus *monitor.Bus, cfg *config.Config) SensingHandler {
	return SensingHandler{agentGateway: gw, monitorBus: bus, config: cfg, soundTracker: &soundTracker{}}
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
			flow.End("sensing_input", turnStart, map[string]any{"path": "local"}, localRunID)
			c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{
				"handler": "local",
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

	// Sound events: dedup + escalation tracking.
	// Occurrences 1–2 pass through silently; occurrence 3+ is marked persistent so the agent speaks once.
	// After speaking, a suppression window prevents further events for soundSuppressDuration.
	if req.Type == "sound" {
		send, occurrence, persistent := h.soundTracker.track(time.Now())
		if !send {
			slog.Info("sound event dropped — dedup or suppressed", "component", "sensing")
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "sound_tracker",
				Summary: "sound dropped (dedup/suppressed)",
				Detail:  map[string]any{"action": "drop"},
			})
			c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{"handler": "dropped"}))
			return
		}
		if persistent {
			req.Message += fmt.Sprintf(" — persistent (occurrence %d)", occurrence)
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "sound_tracker",
				Summary: fmt.Sprintf("sound persistent — occurrence %d → will speak", occurrence),
				Detail:  map[string]any{"action": "persistent", "occurrence": occurrence},
			})
		} else {
			req.Message += fmt.Sprintf(" — occurrence %d", occurrence)
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "sound_tracker",
				Summary: fmt.Sprintf("sound occurrence %d → silent", occurrence),
				Detail:  map[string]any{"action": "silent", "occurrence": occurrence},
			})
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

	var msg string
	if req.Type == "voice" || req.Type == "voice_command" {
		// Voice input is a human speaking — always respond conversationally,
		// even if the transcript is unclear. Never reply NO_REPLY to voice.
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
