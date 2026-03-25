package mqtthandler

import (
	"context"
	"encoding/json"
	"fmt"
	"log"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/device"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/lib/mqtt"
	"go-lamp.autonomous.ai/server/config"
)


// DeviceMQTTHandler handles incoming MQTT messages and dispatches to command handlers.
type DeviceMQTTHandler struct {
	config         *config.Config
	mqttFactory    *mqtt.Factory
	deviceService  *device.Service
	networkService *network.Service
}

// ProvideDeviceMQTTHandler creates DeviceMQTTHandler with all command handlers.
func ProvideDeviceMQTTHandler(cfg *config.Config, mqttFactory *mqtt.Factory, ds *device.Service, ns *network.Service) DeviceMQTTHandler {
	return DeviceMQTTHandler{
		config:         cfg,
		mqttFactory:    mqttFactory,
		deviceService:  ds,
		networkService: ns,
	}
}

func (h *DeviceMQTTHandler) publish(data interface{}) error {
	ctx := context.Background()
	mqttClient := h.mqttFactory.GetClient("lumi-device-" + h.config.DeviceID)
	if err := mqttClient.Connect(ctx); err != nil {
		return err
	}
	defer mqttClient.Close()
	payload, err := json.Marshal(data)
	if err != nil {
		return err
	}
	if err := mqttClient.Publish(ctx, h.config.FDChannel, byte(0), payload); err != nil {
		log.Printf("[mqtt] PublishToFD failed on channel=%s: %v", h.config.FDChannel, err)
		return err
	}
	log.Printf("[mqtt] PublishToFD ok channel=%s payload=%s", h.config.FDChannel, string(payload))
	return nil
}

// HandleMessage processes an incoming MQTT message (called from MQTT subscription callback or GWS HTTP).
func (h *DeviceMQTTHandler) HandleMessage(topic string, payload []byte) error {
	log.Printf("[mqtt] HandleMessage topic=%s payload=%s", topic, string(payload))

	var cmd domain.MQTTMessage
	if err := json.Unmarshal(payload, &cmd); err != nil {
		log.Printf("[mqtt] invalid payload: %v", err)
		return fmt.Errorf("unmarshal mqtt command: %w", err)
	}

	switch cmd.Cmd {
	case domain.CommandInfo:
		return h.handleInfo(cmd)
	case domain.CommandAddChannel:
		return h.handleAddChannel(cmd)
	default:
		log.Printf("[mqtt] unknown command: %s", cmd.Cmd)
		return nil
	}
}
