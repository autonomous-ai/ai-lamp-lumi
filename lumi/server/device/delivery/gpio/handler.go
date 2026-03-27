package http

import (
	"log/slog"
	"os/exec"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/server/config"
)

// DeviceGPIOHandler represents the GPIO handler for device
type DeviceGPIOHandler struct {
	config         *config.Config
	networkService *network.Service
	agentGateway   domain.AgentGateway
}

func ProvideDeviceGPIOHandler(config *config.Config, networkService *network.Service, gw domain.AgentGateway) DeviceGPIOHandler {
	return DeviceGPIOHandler{
		config:         config,
		networkService: networkService,
		agentGateway:   gw,
	}
}

// HandleResetButtonPress is called on short press (click) of GPIO 26. Not called when the button is long-pressed.
func (h *DeviceGPIOHandler) HandleResetButtonPress() {
	slog.Info("restarting agent", "component", "reset-button")
	if err := h.agentGateway.RestartAgent(); err != nil {
		slog.Error("restart agent failed", "component", "reset-button", "error", err)
		return
	}
	slog.Info("restart agent done", "component", "reset-button")
}

// HandleResetButtonPowerOffThreshold is called when GPIO 26 hold crosses 3s (while still holding).
func (h *DeviceGPIOHandler) HandleResetButtonPowerOffThreshold() {
	slog.Info("power off threshold (3s hold)", "component", "reset-button")
}

// HandleResetButtonFactoryResetThreshold is called when GPIO 26 hold crosses 10s (while still holding).
func (h *DeviceGPIOHandler) HandleResetButtonFactoryResetThreshold() {
	slog.Info("factory reset threshold (10s hold)", "component", "reset-button")
}

// HandleResetButtonPowerOff is called when GPIO 26 is held for >= 3s then released. Powers off the device.
func (h *DeviceGPIOHandler) HandleResetButtonPowerOff() {
	slog.Info("power off (3s hold)", "component", "reset-button")
	if err := exec.Command("systemctl", "poweroff").Run(); err != nil {
		slog.Error("power off failed", "component", "reset-button", "error", err)
	}
}

// HandleResetButtonFactoryReset is called when GPIO 26 is held for >= 10s. Switches to AP mode first so wlan0
// stays available, then resets config to default and saves.
func (h *DeviceGPIOHandler) HandleResetButtonFactoryReset() {
	slog.Info("factory reset (10s hold)", "component", "reset-button")
	if err := h.agentGateway.ResetAgent(); err != nil {
		slog.Error("reset agent failed", "component", "reset-button", "error", err)
		return
	}
	slog.Debug("resetting config to default", "component", "reset-button")
	if err := h.config.ResetToDefault(); err != nil {
		slog.Error("factory reset failed", "component", "reset-button", "error", err)
		return
	}
	slog.Debug("resetting network", "component", "reset-button")
	if err := h.networkService.ResetNetwork(); err != nil {
		slog.Error("reset network failed", "component", "reset-button", "error", err)
		return
	}
	slog.Debug("switching to AP mode", "component", "reset-button")
	if err := h.networkService.SwitchToAPMode(); err != nil {
		slog.Error("switch to AP mode failed", "component", "reset-button", "error", err)
	}
	slog.Info("config reset to default (factory reset)", "component", "reset-button")
}
