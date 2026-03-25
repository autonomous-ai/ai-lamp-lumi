package config

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"

	"go-lamp.autonomous.ai/lib/mqtt"
)

const configPath = "config/config.json"

// LumiVersion is injected at build time via ldflags.
// Example:
//
//	-X go-lamp.autonomous.ai/server/config.LumiVersion=v1.2.3
var LumiVersion = "dev"

type Config struct {
	HttpPort int `json:"httpPort" yaml:"httpPort" validate:"required"`

	// Channel type: "telegram" or "slack" (empty defaults to telegram for backward compat)
	Channel string `json:"channel" yaml:"channel"`

	TelegramBotToken string `json:"telegram_bot_token" yaml:"telegramBotToken"`
	TelegramUserID   string `json:"telegram_user_id" yaml:"telegramUserID"`

	SlackBotToken string `json:"slack_bot_token" yaml:"slackBotToken"`
	SlackAppToken string `json:"slack_app_token" yaml:"slackAppToken"`
	SlackUserID   string `json:"slack_user_id" yaml:"slackUserID"`

	DiscordBotToken string `json:"discord_bot_token" yaml:"discordBotToken"`
	DiscordGuildID  string `json:"discord_guild_id" yaml:"discordGuildID"`
	DiscordUserID   string `json:"discord_user_id" yaml:"discordUserID"`

	LLMAPIKey  string `json:"llm_api_key" yaml:"llmAPIKey" validate:"required"`
	LLMModel   string `json:"llm_model" yaml:"llmModel" validate:"required"`
	LLMBaseURL string `json:"llm_base_url" yaml:"llmBaseURL" validate:"required"`

	OTAMetadataURL  string `json:"ota_metadata_url" yaml:"otaMetadataURL"`
	OTAPollInterval string `json:"ota_poll_interval" yaml:"otaPollInterval"`

	DeepgramAPIKey string `json:"deepgram_api_key" yaml:"deepgramAPIKey"`

	// AgentRuntime selects which agentic backend to use: "openclaw" (default), "picoclaw", "claudecode", etc.
	AgentRuntime string `json:"agent_runtime" yaml:"agentRuntime"`

	OpenclawConfigDir string `json:"openclaw_config_dir" yaml:"openclawConfigDir"`

	NetworkSSID     string `json:"network_ssid" yaml:"networkSSID" validate:"required"`
	NetworkPassword string `json:"network_password" yaml:"networkPassword" validate:"required"`

	SetUpCompleted bool `json:"set_up_completed" yaml:"setUpCompleted"`

	// DeviceID is saved at setup, used for backend status reporting
	DeviceID string `json:"device_id" yaml:"deviceID"`

	// MQTT (optional): empty broker URL means MQTT disabled
	MQTTEndpoint string `json:"mqtt_endpoint" yaml:"mqttEndpoint"`
	MQTTUsername string `json:"mqtt_username" yaml:"mqttUsername"`
	MQTTPassword string `json:"mqtt_password" yaml:"mqttPassword"`
	MQTTPort     int    `json:"mqtt_port" yaml:"mqttPort"`
	FAChannel    string `json:"fa_channel" yaml:"faChannel"`
	FDChannel    string `json:"fd_channel" yaml:"fdChannel"`

	notify chan bool
}

// Load reads config from configPath. Returns error if file is missing or invalid.
func Load() (Config, error) {
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		return Default(), fmt.Errorf("config file not found: %s", configPath)
	}
	data, err := os.ReadFile(configPath)
	if err != nil {
		return Default(), fmt.Errorf("read config %s: %w", configPath, err)
	}
	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return Default(), fmt.Errorf("parse config %s: %w", configPath, err)
	}
	cfg.notify = make(chan bool, 1)
	return cfg, nil
}

func Default() Config {
	return Config{
		HttpPort: 5000,

		TelegramBotToken: "",

		LLMAPIKey:  "",
		LLMModel:   "claude-opus-4-6",
		LLMBaseURL: "",

		OTAMetadataURL:  "",
		OTAPollInterval: "1h",

		OpenclawConfigDir: "/root/openclaw",

		NetworkSSID:     "",
		NetworkPassword: "",
		SetUpCompleted:  false,
		DeviceID:        "",

		MQTTEndpoint: "",
		MQTTUsername: "",
		MQTTPassword: "",
		MQTTPort:     0,

		notify: make(chan bool, 1),
	}
}

func ProvideConfig() *Config {
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		c := Default()
		if err := c.Save(); err != nil {
			log.Printf("save config: %v\n", err)
		}
		c.notify = make(chan bool, 1)
		return &c
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		panic(fmt.Errorf("read config %s: %w", configPath, err))
	}

	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		panic(fmt.Errorf("parse config %s: %w", configPath, err))
	}
	cfg.notify = make(chan bool, 1)
	return &cfg
}

// ResetToDefault resets all config fields to default values (keeps notify channel) and saves.
// Used e.g. by the physical reset button (press-and-hold >= 10s).
func (c *Config) ResetToDefault() error {
	notify := c.notify
	*c = Default()
	c.notify = notify
	return c.Save()
}

// Save writes the config to the config file.
func (c Config) Save() error {
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal config: %w", err)
	}

	dir := filepath.Dir(configPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("create config dir: %w", err)
	}

	if err := os.WriteFile(configPath, data, 0600); err != nil {
		return fmt.Errorf("write config %s: %w", configPath, err)
	}
	if c.notify != nil {
		select {
		case c.notify <- true:
		default:
		}
	}
	return nil
}

func (c *Config) GetNotifyChannel() chan bool {
	return c.notify
}

func ProvideMQTTConfig(c *Config) mqtt.Config {
	return mqtt.Config{
		Endpoint: c.MQTTEndpoint,
		Username: c.MQTTUsername,
		Password: c.MQTTPassword,
		Port:     c.MQTTPort,
	}
}
