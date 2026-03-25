package mqtthandler

import (
	"log"
	"os"
	"path/filepath"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/device"
)

func (h *DeviceMQTTHandler) handleRemoveGoogleCredentials(cmd domain.MQTTMessage) error {
	credPath := filepath.Join(h.config.OpenclawConfigDir, "credentials", gwsCredentialsFile)

	if _, err := os.Stat(credPath); os.IsNotExist(err) {
		log.Printf("[mqtt] remove_google_credentials: no credentials found")
		return h.publishRemoveGoogleCredentialsResult("success")
	}

	if err := os.Remove(credPath); err != nil {
		log.Printf("[mqtt] remove_google_credentials: failed to remove: %v", err)
		return h.publishRemoveGoogleCredentialsFailure("failed to remove credentials: " + err.Error())
	}

	log.Printf("[mqtt] remove_google_credentials: credentials removed")
	return h.publishRemoveGoogleCredentialsResult("success")
}

func (h *DeviceMQTTHandler) publishRemoveGoogleCredentialsResult(status string) error {
	resp := domain.MQTTRemoveGoogleCredentialsResponse{
		MQTTInfoResponse: domain.NewMQTTInfoResponse(h.config, "remove_google_credentials", device.GetDeviceMac()),
		Status:           status,
	}
	return h.publish(resp)
}

func (h *DeviceMQTTHandler) publishRemoveGoogleCredentialsFailure(errMsg string) error {
	resp := domain.MQTTRemoveGoogleCredentialsResponse{
		MQTTInfoResponse: domain.NewMQTTInfoResponse(h.config, "remove_google_credentials", device.GetDeviceMac()),
		Status:           "failure",
		Error:            errMsg,
	}
	return h.publish(resp)
}
