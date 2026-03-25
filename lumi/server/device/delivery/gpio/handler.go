package http

import (
	"log"
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
	log.Println("reset button: restarting agent")
	if err := h.agentGateway.RestartAgent(); err != nil {
		log.Printf("reset button: restart agent: %v", err)
		return
	}
	log.Println("reset button: done")
}

// HandleResetButtonPowerOffThreshold is called when GPIO 26 hold crosses 3s (while still holding).
func (h *DeviceGPIOHandler) HandleResetButtonPowerOffThreshold() {
	log.Println("reset button: power off threshold (3s hold)")
}

// HandleResetButtonFactoryResetThreshold is called when GPIO 26 hold crosses 10s (while still holding).
func (h *DeviceGPIOHandler) HandleResetButtonFactoryResetThreshold() {
	log.Println("reset button: factory reset threshold (10s hold)")
}

// HandleResetButtonPowerOff is called when GPIO 26 is held for >= 3s then released. Powers off the device.
func (h *DeviceGPIOHandler) HandleResetButtonPowerOff() {
	log.Println("reset button: power off (3s hold)")
	if err := exec.Command("systemctl", "poweroff").Run(); err != nil {
		log.Printf("reset button: power off: %v", err)
	}
}

// HandleResetButtonFactoryReset is called when GPIO 26 is held for >= 10s. Switches to AP mode first so wlan0
// stays available, then resets config to default and saves.
func (h *DeviceGPIOHandler) HandleResetButtonFactoryReset() {
	log.Println("reset button: factory reset (10s hold)")
	if err := h.agentGateway.ResetAgent(); err != nil {
		log.Printf("reset button: reset agent: %v", err)
		return
	}
	log.Println("reset button: resetting config to default")
	if err := h.config.ResetToDefault(); err != nil {
		log.Printf("reset button: factory reset: %v", err)
		return
	}
	log.Println("reset button: resetting network")
	if err := h.networkService.ResetNetwork(); err != nil {
		log.Printf("reset button: reset network: %v", err)
		return
	}
	log.Println("reset button: switching to AP mode")
	if err := h.networkService.SwitchToAPMode(); err != nil {
		log.Printf("reset button: switch to AP mode: %v", err)
	}
	log.Println("reset button: config reset to default (factory reset)")
}
