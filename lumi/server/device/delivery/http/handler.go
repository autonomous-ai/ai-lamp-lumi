package http

import (
	"log/slog"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"
	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/device"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/server/serializers"
)

// DeviceHandler represents the HTTP handler for device
type DeviceHandler struct {
	service        *device.Service
	networkService *network.Service
}

func ProvideDeviceHandler(ds *device.Service, ns *network.Service) DeviceHandler {
	return DeviceHandler{
		service:        ds,
		networkService: ns,
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
			slog.Error("setup failed", "component", "device", "error", err)
			h.networkService.SwitchToAPMode()
			return
		}

		slog.Info("setup success", "component", "device")
	}()

	c.JSON(http.StatusOK, serializers.ResponseSuccess(true))
}

// GetConfig godoc
//
//	@Summary	get current device config
//	@Schemes
//	@Description	get current device config
//	@Tags			device
//	@Success		200	{object}	serializers.ResponseSuccess
//	@Router			/device/config [get]
func (h *DeviceHandler) GetConfig(c *gin.Context) {
	cfg := h.service.GetConfig()
	c.JSON(http.StatusOK, serializers.ResponseSuccess(cfg))
}

// UpdateConfig godoc
//
//	@Summary	update device config
//	@Schemes
//	@Description	update device config fields (all optional; saves to disk, restart Lumi for full effect)
//	@Tags			device
//	@Accept			json
//	@Param			body	body		domain.UpdateConfigRequest	true	"update config request"
//	@Success		200		{object}	serializers.ResponseSuccess
//	@Router			/device/config [put]
func (h *DeviceHandler) UpdateConfig(c *gin.Context) {
	var req domain.UpdateConfigRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, serializers.ResponseError(err.Error()))
		return
	}
	if err := h.service.UpdateConfig(req); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
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
			slog.Error("add channel failed", "component", "device", "error", err)
			return
		}
		slog.Info("add channel success", "component", "device")
	}()

	c.JSON(http.StatusOK, serializers.ResponseSuccess(true))
}
