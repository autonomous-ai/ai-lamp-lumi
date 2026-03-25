package http

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/led"
)

// LedHandler represents the HTTP handler for LED control.
type LedHandler struct {
	ledEngine *led.Engine
}

// ProvideLedHandler returns a LedHandler.
func ProvideLedHandler(ledEngine *led.Engine) LedHandler {
	return LedHandler{
		ledEngine: ledEngine,
	}
}

// GetState returns the current LED state. GET /api/led
func (h *LedHandler) GetState(c *gin.Context) {
	if h.ledEngine == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "LED not available"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"state": h.ledEngine.GetState().String()})
}

// UpdateState sets the LED state. POST /api/led
// Body: {"state": "thinking"} — accepted values: booting, idle, connectionmode, thinking, working, workingnointernet, error.
func (h *LedHandler) UpdateState(c *gin.Context) {
	if h.ledEngine == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "LED not available"})
		return
	}
	var req domain.UpdateStateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "missing or invalid 'state' field", "valid": led.ValidStateNames})
		return
	}
	st, err := led.ParseState(req.State)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error(), "valid": led.ValidStateNames})
		return
	}
	h.ledEngine.SetState(st, "http-api")
	c.JSON(http.StatusOK, gin.H{"state": st.String()})
}
