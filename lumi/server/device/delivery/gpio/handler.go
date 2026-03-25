package http

import (
	"log"
	"os/exec"
	"time"

	"go-lamp.autonomous.ai/internal/led"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/internal/openclaw"
	"go-lamp.autonomous.ai/server/config"
)

// DeviceGPIOHandler represents the GPIO handler for device
type DeviceGPIOHandler struct {
	config          *config.Config
	networkService  *network.Service
	openclawService *openclaw.Service
	ledEngine       *led.Engine
}

func ProvideDeviceGPIOHandler(config *config.Config, networkService *network.Service, openclawService *openclaw.Service, ledEngine *led.Engine) DeviceGPIOHandler {
	return DeviceGPIOHandler{
		config:          config,
		networkService:  networkService,
		openclawService: openclawService,
		ledEngine:       ledEngine,
	}
}

// HandleResetButtonPress is called on short press (click) of GPIO 26. Not called when the button is long-pressed.
func (h *DeviceGPIOHandler) HandleResetButtonPress() {
	log.Println("reset button: restarting openclaw")
	if err := h.openclawService.RestartOpenclaw(); err != nil {
		log.Printf("reset button: restart openclaw: %v", err)
		return
	}
	log.Println("reset button: done")
}

// HandleResetButtonPowerOffThreshold is called when GPIO 26 hold crosses 3s (while still holding).
// Used to change LED to indicate power-off imminent. Inhibits SetState so network monitor etc. cannot overwrite.
func (h *DeviceGPIOHandler) HandleResetButtonPowerOffThreshold() {
	log.Println("reset button: power off threshold (3s hold)")
	h.ledEngine.UninhibitSetState("reset-btn-power-off-threshold")
	h.ledEngine.SetState(led.PowerOff, "reset-btn-3s", led.WithInhibit())
}

// HandleResetButtonFactoryResetThreshold is called when GPIO 26 hold crosses 10s (while still holding).
// Used to change LED to indicate factory reset imminent. Inhibits SetState so network monitor etc. cannot overwrite.
func (h *DeviceGPIOHandler) HandleResetButtonFactoryResetThreshold() {
	h.ledEngine.UninhibitSetState("reset-btn-factory-reset-threshold")
	h.ledEngine.SetState(led.FactoryReset, "reset-btn-10s", led.WithInhibit())
}

// HandleResetButtonPowerOff is called when GPIO 26 is held for >= 3s then released. Powers off the device.
func (h *DeviceGPIOHandler) HandleResetButtonPowerOff() {
	log.Println("reset button: power off (3s hold)")
	h.ledEngine.UninhibitSetState("reset-btn-power-off")
	log.Println("reset button: power off close led")
	h.ledEngine.Close()
	time.Sleep(3 * time.Second)
	if err := exec.Command("systemctl", "poweroff").Run(); err != nil {
		log.Printf("reset button: power off: %v", err)
	}
}

// HandleResetButtonFactoryReset is called when GPIO 26 is held for >= 10s. Switches to AP mode first so wlan0
// stays available, then resets config to default and saves.
func (h *DeviceGPIOHandler) HandleResetButtonFactoryReset() {
	log.Println("reset button: factory reset (10s hold)")
	h.ledEngine.UninhibitSetState("reset-btn-factory-reset")
	h.ledEngine.SetState(led.Booting, "reset-btn-factory")
	if err := h.openclawService.ResetOpenclaw(); err != nil {
		log.Printf("reset button: reset openclaw: %v", err)
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
	h.ledEngine.UninhibitSetState("reset-btn-done")
	log.Println("reset button: config reset to default (factory reset)")
}
