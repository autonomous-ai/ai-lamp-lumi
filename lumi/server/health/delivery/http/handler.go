package http

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/server/serializers"
)

// HealthHandle  represent the httphandler for health
type HealthHandler struct {
}

func ProvideHealthHandler() HealthHandler {
	return HealthHandler{}
}

func (h *HealthHandler) Live(c *gin.Context) {
	c.JSON(http.StatusOK, serializers.ResponseSuccess("OK"))
}

func (h *HealthHandler) Readiness(c *gin.Context) {
	c.JSON(http.StatusOK, serializers.ResponseSuccess("OK"))
}
