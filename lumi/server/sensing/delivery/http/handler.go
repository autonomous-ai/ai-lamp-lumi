package http

import (
	"log"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/intent"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/server/config"
	"go-lamp.autonomous.ai/server/serializers"
)

// SensingEventRequest is the payload from LeLamp sensing detectors.
type SensingEventRequest struct {
	// Type is the event category: motion, sound, environment, voice, etc.
	Type string `json:"type" validate:"required"`
	// Message is a natural-language description of what was detected.
	Message string `json:"message" validate:"required"`
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

	// Push sensing input to monitor
	h.monitorBus.Push(domain.MonitorEvent{
		Type:    "sensing_input",
		Summary: "[" + req.Type + "] " + req.Message,
	})

	// Voice commands: try local intent matching first for instant response
	if req.Type == "voice" && h.config.LocalIntentEnabled() {
		if result := intent.Match(req.Message); result != nil {
			log.Printf("[sensing] local intent matched: %q", req.Message)
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
			h.monitorBus.Push(domain.MonitorEvent{
				Type:    "intent_match",
				Summary: "[local] " + req.Message + " → " + result.TTSText,
			})
			c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{
				"handler": "local",
			}))
			return
		}
	}

	// No local match — forward to OpenClaw agent
	if !h.agentGateway.IsReady() {
		c.JSON(http.StatusServiceUnavailable, serializers.ResponseError("agent gateway not connected"))
		return
	}

	msg := "[sensing:" + req.Type + "] " + req.Message
	runID, err := h.agentGateway.SendChatMessage(msg)
	if err != nil {
		log.Printf("[sensing] failed to send event: %v", err)
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}

	log.Printf("[sensing] event forwarded: type=%s runId=%s", req.Type, runID)
	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]string{
		"runId": runID,
	}))
}
