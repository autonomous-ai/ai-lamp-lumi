package mqtthandler

import (
	"log"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/device"
)

func (h *DeviceMQTTHandler) handleInfo(_ domain.MQTTMessage) error {
	msg := domain.NewMQTTInfoResponse(h.config, "info", device.GetDeviceMac())
	log.Printf("[mqtt] info: publishing device info (version=%s, id=%s)", msg.Version, msg.ID)
	return h.publish(msg)
}
