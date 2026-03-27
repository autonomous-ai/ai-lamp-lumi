package mqtthandler

import (
	"encoding/json"
	"log/slog"

	"github.com/go-playground/validator/v10"
	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/device"
)

func (h *DeviceMQTTHandler) publishAddChannelResult(channel, status string, errMsg string) error {
	resp := domain.MQTTAddChannelResponse{
		MQTTInfoResponse: domain.NewMQTTInfoResponse(h.config, "add_channel", device.GetDeviceMac()),
		Channel:          channel,
		Status:           status,
		Error:            errMsg,
	}
	return h.publish(resp)
}

func (h *DeviceMQTTHandler) handleAddChannel(cmd domain.MQTTMessage) error {
	var req domain.MQTTAddChannelCommand
	if err := json.Unmarshal(cmd.Raw(), &req); err != nil {
		slog.Error("add_channel: invalid payload", "component", "mqtt", "error", err)
		return h.publishAddChannelResult(req.Channel, "failure", "invalid JSON payload")
	}

	channelReq := req.ToRequest()
	if err := validator.New().Struct(channelReq); err != nil {
		return h.publishAddChannelResult(req.Channel, "failure", err.Error())
	}
	if err := channelReq.ValidateChannel(); err != nil {
		return h.publishAddChannelResult(req.Channel, "failure", err.Error())
	}
	if err := h.deviceService.AddChannel(channelReq); err != nil {
		slog.Error("add_channel: failed", "component", "mqtt", "channel", req.Channel, "error", err)
		return h.publishAddChannelResult(req.Channel, "failure", err.Error())
	}

	slog.Info("add_channel: success", "component", "mqtt", "channel", req.Channel)
	return h.publishAddChannelResult(req.Channel, "success", "")
}
