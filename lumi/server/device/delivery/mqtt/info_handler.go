package mqtthandler

import (
	"log/slog"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/device"
)

func (h *DeviceMQTTHandler) handleInfo(_ domain.MQTTMessage) error {
	msg := domain.NewMQTTInfoResponse(h.config, "info", device.GetDeviceMac())
	slog.Info("publishing device info", "component", "mqtt", "version", msg.Version, "id", msg.ID)
	return h.publish(msg)
}
