package mqtthandler

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/device"
)

func (h *DeviceMQTTHandler) handleSetGoogleCredentials(cmd domain.MQTTMessage) error {
	var req domain.MQTTSetGoogleCredentialsCommand
	if err := json.Unmarshal(cmd.Raw(), &req); err != nil {
		log.Printf("[mqtt] set_google_credentials: invalid payload: %v", err)
		return h.publishSetGoogleCredentialsFailure("invalid payload")
	}

	if req.ClientID == "" || req.ClientSecret == "" || req.RefreshToken == "" {
		log.Printf("[mqtt] set_google_credentials: missing required fields")
		return h.publishSetGoogleCredentialsFailure("client_id, client_secret, and refresh_token are required")
	}

	if err := h.storeCredentials(req); err != nil {
		log.Printf("[mqtt] set_google_credentials: failed to store: %v", err)
		return h.publishSetGoogleCredentialsFailure("failed to store credentials: " + err.Error())
	}

	email, err := h.verifyCredentials()
	if err != nil {
		log.Printf("[mqtt] set_google_credentials: verification failed: %v", err)
		return h.publishSetGoogleCredentialsFailure("invalid credentials: " + err.Error())
	}

	log.Printf("[mqtt] set_google_credentials: verified for %s", email)

	resp := domain.MQTTSetGoogleCredentialsResponse{
		MQTTInfoResponse: domain.NewMQTTInfoResponse(h.config, "set_google_credentials", device.GetDeviceMac()),
		Status:           "success",
		GoogleEmail:      email,
	}
	return h.publish(resp)
}

func (h *DeviceMQTTHandler) credentialsPath() string {
	return filepath.Join(h.config.OpenclawConfigDir, "credentials", gwsCredentialsFile)
}

func (h *DeviceMQTTHandler) storeCredentials(req domain.MQTTSetGoogleCredentialsCommand) error {
	credDir := filepath.Join(h.config.OpenclawConfigDir, "credentials")
	if err := os.MkdirAll(credDir, 0700); err != nil {
		return fmt.Errorf("create credentials dir: %w", err)
	}

	creds := map[string]interface{}{
		"client_id":     req.ClientID,
		"client_secret": req.ClientSecret,
		"refresh_token": req.RefreshToken,
	}
	if len(req.Scopes) > 0 {
		creds["scopes"] = req.Scopes
	}

	data, err := json.MarshalIndent(creds, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal credentials: %w", err)
	}

	credPath := h.credentialsPath()
	if err := os.WriteFile(credPath, data, 0600); err != nil {
		return fmt.Errorf("write credentials: %w", err)
	}

	log.Printf("[mqtt] set_google_credentials: stored at %s", credPath)
	return nil
}

func (h *DeviceMQTTHandler) verifyCredentials() (string, error) {
	credPath := h.credentialsPath()
	out, err := exec.Command("gws", "auth", "login", "--cred", credPath).CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("gws auth login: %s", strings.TrimSpace(string(out)))
	}

	out, err = exec.Command("gws", "gmail", "users", "getProfile", "--params", `{"userId":"me"}`).CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("gws gmail getProfile: %s", strings.TrimSpace(string(out)))
	}

	var result map[string]interface{}
	if err := json.Unmarshal(out, &result); err != nil {
		return "", fmt.Errorf("parse gws response: %w", err)
	}

	email, _ := result["emailAddress"].(string)
	if email == "" {
		return "", fmt.Errorf("no email in gws response")
	}
	return strings.TrimSpace(email), nil
}

func (h *DeviceMQTTHandler) publishSetGoogleCredentialsFailure(errMsg string) error {
	resp := domain.MQTTSetGoogleCredentialsResponse{
		MQTTInfoResponse: domain.NewMQTTInfoResponse(h.config, "set_google_credentials", device.GetDeviceMac()),
		Status:           "failure",
		Error:            errMsg,
	}
	return h.publish(resp)
}
