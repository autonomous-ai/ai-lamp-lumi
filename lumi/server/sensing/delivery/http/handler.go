package http

import (
	"log"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/server/serializers"
)

// SensingEventRequest is the payload from LeLamp sensing detectors.
type SensingEventRequest struct {
	// Type is the event category: motion, sound, environment, etc.
	Type string `json:"type" validate:"required"`
	// Message is a natural-language description of what was detected.
	Message string `json:"message" validate:"required"`
}

// SensingHandler handles incoming sensing events from LeLamp and forwards them to the agent.
type SensingHandler struct {
	agentGateway domain.AgentGateway
	monitorBus   *monitor.Bus
}

// ProvideSensingHandler constructs a SensingHandler.
func ProvideSensingHandler(gw domain.AgentGateway, bus *monitor.Bus) SensingHandler {
	return SensingHandler{agentGateway: gw, monitorBus: bus}
}

// PostEvent receives a sensing event and sends it to the agent as a chat message.
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

	if !h.agentGateway.IsReady() {
		c.JSON(http.StatusServiceUnavailable, serializers.ResponseError("agent gateway not connected"))
		return
	}

	// Push sensing input to monitor before forwarding
	h.monitorBus.Push(domain.MonitorEvent{
		Type:    "sensing_input",
		Summary: "[" + req.Type + "] " + req.Message,
	})

	// Format the sensing event as a message for the agent
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
