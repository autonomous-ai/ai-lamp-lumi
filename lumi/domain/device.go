package domain

import (
	"encoding/json"
	"fmt"
	"time"

	"go-lamp.autonomous.ai/server/config"
)

type SetupRequest struct {
	// setup network
	SSID     string `json:"ssid" validate:"required"`
	Password string `json:"password" validate:"required"`

	// channel type: "telegram" (default), "slack" or "discord"
	Channel string `json:"channel"`

	// telegram channel (required when channel is telegram or empty)
	TelegramBotToken string `json:"telegram_bot_token"`
	TelegramUserID   string `json:"telegram_user_id"`

	// slack channel (required when channel is slack)
	SlackBotToken string `json:"slack_bot_token"`
	SlackAppToken string `json:"slack_app_token"`
	SlackUserID   string `json:"slack_user_id"`

	// discord channel (required when channel is discord)
	DiscordBotToken string `json:"discord_bot_token"`
	DiscordGuildID  string `json:"discord_guild_id"`
	DiscordUserID   string `json:"discord_user_id"`

	// setup custom provider for openclaw
	LLMBaseURL string `json:"llm_base_url" validate:"required"`
	LLMAPIKey  string `json:"llm_api_key" validate:"required"`
	LLMModel   string `json:"llm_model"`

	// voice pipeline (optional): Deepgram API key for STT
	DeepgramAPIKey string `json:"deepgram_api_key"`

	// optional
	DeviceID string `json:"device_id"`

	// MQTT (optional): empty broker URL means MQTT disabled
	MQTTEndpoint string `json:"mqtt_endpoint"`
	MQTTUsername string `json:"mqtt_username"`
	MQTTPassword string `json:"mqtt_password"`
	MQTTPort     int    `json:"mqtt_port"`
	FAChannel    string `json:"fa_channel"`
	FDChannel    string `json:"fd_channel"`
}

// EffectiveChannel returns the resolved channel type, defaulting to "telegram".
func (r *SetupRequest) EffectiveChannel() string {
	if r.Channel == "slack" {
		return "slack"
	}
	if r.Channel == "discord" {
		return "discord"
	}
	return "telegram"
}

// ValidateChannel checks that the required fields for the selected channel are present.
func (r *SetupRequest) ValidateChannel() error {
	switch r.EffectiveChannel() {
	case "slack":
		if r.SlackBotToken == "" {
			return fmt.Errorf("slack_bot_token is required for slack channel")
		}
		if r.SlackAppToken == "" {
			return fmt.Errorf("slack_app_token is required for slack channel")
		}
	case "discord":
		if r.DiscordBotToken == "" {
			return fmt.Errorf("discord_bot_token is required for discord channel")
		}
		if r.DiscordGuildID == "" {
			return fmt.Errorf("discord_guild_id is required for discord channel")
		}
		if r.DiscordUserID == "" {
			return fmt.Errorf("discord_user_id is required for discord channel")
		}
	default:
		if r.TelegramBotToken == "" {
			return fmt.Errorf("telegram_bot_token is required for telegram channel")
		}
		if r.TelegramUserID == "" {
			return fmt.Errorf("telegram_user_id is required for telegram channel")
		}
	}
	return nil
}

// AddChannelRequest is used to add a messaging channel after initial setup.
type AddChannelRequest struct {
	// channel type: "telegram", "slack" or "discord"
	Channel string `json:"channel" validate:"required"`

	// telegram
	TelegramBotToken string `json:"telegram_bot_token"`
	TelegramUserID   string `json:"telegram_user_id"`

	// slack
	SlackBotToken string `json:"slack_bot_token"`
	SlackAppToken string `json:"slack_app_token"`
	SlackUserID   string `json:"slack_user_id"`

	// discord
	DiscordBotToken string `json:"discord_bot_token"`
	DiscordGuildID  string `json:"discord_guild_id"`
	DiscordUserID   string `json:"discord_user_id"`
}

// EffectiveChannel returns the resolved channel type, defaulting to "telegram".
func (r *AddChannelRequest) EffectiveChannel() string {
	if r.Channel == "slack" {
		return "slack"
	}
	if r.Channel == "discord" {
		return "discord"
	}
	return "telegram"
}

// ValidateChannel checks that the required fields for the selected channel are present.
func (r *AddChannelRequest) ValidateChannel() error {
	switch r.EffectiveChannel() {
	case "slack":
		if r.SlackBotToken == "" {
			return fmt.Errorf("slack_bot_token is required for slack channel")
		}
		if r.SlackAppToken == "" {
			return fmt.Errorf("slack_app_token is required for slack channel")
		}
	case "discord":
		if r.DiscordBotToken == "" {
			return fmt.Errorf("discord_bot_token is required for discord channel")
		}
		if r.DiscordGuildID == "" {
			return fmt.Errorf("discord_guild_id is required for discord channel")
		}
		if r.DiscordUserID == "" {
			return fmt.Errorf("discord_user_id is required for discord channel")
		}
	default:
		if r.TelegramBotToken == "" {
			return fmt.Errorf("telegram_bot_token is required for telegram channel")
		}
		if r.TelegramUserID == "" {
			return fmt.Errorf("telegram_user_id is required for telegram channel")
		}
	}
	return nil
}

type SetupResponse struct {
	Success bool `json:"success"`
}

// Command types received from server via MQTT FAChannel.
// Matches spec: docs/mqtt_specs_autonomous.md
const (
	CommandInfo                    = "info"
	CommandAddChannel              = "add_channel"
	CommandOTA = "ota"
)

// Message is the standard envelope for MQTT messages from the server (fa_channel).
// Server sends: {"cmd": "info"}, {"cmd": "add_channel", "channel": "discord", "config": {...}}
type MQTTMessage struct {
	Cmd     string          `json:"cmd"`
	RawData json.RawMessage `json:"-"`
	raw     []byte
}

// UnmarshalJSON custom unmarshals to keep the full raw payload accessible to handlers.
func (m *MQTTMessage) UnmarshalJSON(data []byte) error {
	type alias struct {
		Cmd string `json:"cmd"`
	}
	var a alias
	if err := json.Unmarshal(data, &a); err != nil {
		return err
	}
	m.Cmd = a.Cmd
	m.raw = make([]byte, len(data))
	copy(m.raw, data)
	return nil
}

// Raw returns the full original JSON payload for handlers to parse additional fields.
func (m *MQTTMessage) Raw() []byte {
	return m.raw
}

type MQTTAddChannelRequest struct {
	Channel string                 `json:"channel" validate:"required"`
	Config  map[string]interface{} `json:"config"`
}

// MQTTAddChannelCommand is the fa_channel payload for cmd:"add_channel".
// Example: {"cmd":"add_channel","channel":"discord","config":{"bot_token":"...","guild_id":"..."}}
type MQTTAddChannelCommand struct {
	Channel string                 `json:"channel"`
	Config  map[string]interface{} `json:"config"`
}

func (r *MQTTAddChannelCommand) ToRequest() AddChannelRequest {
	var req AddChannelRequest
	req.Channel = r.Channel
	cfg := r.Config
	switch r.Channel {
	case "discord":
		req.DiscordBotToken, _ = cfg["bot_token"].(string)
		req.DiscordGuildID, _ = cfg["guild_id"].(string)
		req.DiscordUserID, _ = cfg["user_id"].(string)
	case "slack":
		req.SlackBotToken, _ = cfg["bot_token"].(string)
		req.SlackAppToken, _ = cfg["app_token"].(string)
		req.SlackUserID, _ = cfg["channel_id"].(string)
	default:
		req.TelegramBotToken, _ = cfg["bot_token"].(string)
		req.TelegramUserID, _ = cfg["chat_id"].(string)
	}
	return req
}

// MQTTAddChannelResponse extends MQTTInfoResponse with channel-specific fields for fd_channel.
type MQTTAddChannelResponse struct {
	MQTTInfoResponse
	Channel string `json:"channel"`
	Status  string `json:"status"`
	Error   string `json:"error,omitempty"`
}

type MQTTRemoveChannelRequest struct {
	Channel string `json:"channel" validate:"required"`
}

type MQTTRemoveChannelResponse struct {
	Success bool `json:"success"`
}

// DeviceMessage is the base response published to fd_channel.
// All messages MUST include these required fields per spec.
type MQTTInfoResponse struct {
	Device  string `json:"device"`
	Type    string `json:"type"`
	Version string `json:"version"`
	ID      string `json:"id"`
	Mac     string `json:"mac"`
	Time    string `json:"time"`
}

// NewDeviceMessage creates a base message with required fields populated from config.
func NewMQTTInfoResponse(cfg *config.Config, msgType string, mac string) MQTTInfoResponse {
	return MQTTInfoResponse{
		Device:  "ai_lumi",
		Type:    msgType,
		Version: config.LumiVersion,
		ID:      cfg.DeviceID,
		Mac:     mac,
		Time:    time.Now().UTC().Format(time.RFC3339Nano),
	}
}
