package http

import (
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"
	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/device"
	"go-lamp.autonomous.ai/internal/led"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/server/serializers"
)

// DeviceHandler represents the HTTP handler for device
type DeviceHandler struct {
	service        *device.Service
	ledEngine      *led.Engine
	networkService *network.Service
}

func ProvideDeviceHandler(ds *device.Service, ns *network.Service, le *led.Engine) DeviceHandler {
	return DeviceHandler{
		service:        ds,
		networkService: ns,
		ledEngine:      le,
	}
}

// Setup godoc
//
//	@Summary	setup device
//	@Schemes
//	@Description	setup device
//	@Tags			device
//	@Accept			json
//	@Param			body	body		domain.SetupRequest		true	"setup request"
//	@Success		200		{object}	serializers.ResponseSuccess
//	@Router			/device/setup [post]
func (h *DeviceHandler) Setup(c *gin.Context) {
	var req domain.SetupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	if err := validator.New().Struct(req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	if err := req.ValidateChannel(); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}

	go func() {
		time.Sleep(2 * time.Second)
		if err := h.service.Setup(req); err != nil {
			h.ledEngine.SetState(led.Error, "setup-failed")
			log.Println("Setup failed", err)
			h.networkService.SwitchToAPMode()
			return
		}

		log.Println("Setup success")
	}()

	c.JSON(http.StatusOK, serializers.ResponseSuccess(true))
}

// ChangeChannel godoc
//
//	@Summary	change messaging channel
//	@Schemes
//	@Description	change messaging channel (telegram/slack/discord) without full device re-setup
//	@Tags			device
//	@Accept			json
//	@Param			body	body		domain.ChangeChannelRequest	true	"change channel request"
//	@Success		200		{object}	serializers.ResponseSuccess
//	@Router			/device/channel [post]
func (h *DeviceHandler) ChangeChannel(c *gin.Context) {
	var req domain.AddChannelRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	if err := validator.New().Struct(req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	if err := req.ValidateChannel(); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}

	go func() {
		if err := h.service.AddChannel(req); err != nil {
			h.ledEngine.SetState(led.Error, "add-channel-failed")
			log.Println("AddChannel failed", err)
			return
		}
		log.Println("AddChannel success")
	}()

	c.JSON(http.StatusOK, serializers.ResponseSuccess(true))
}
