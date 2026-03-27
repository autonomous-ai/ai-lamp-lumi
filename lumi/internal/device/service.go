package device

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/beclient"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/server/config"
)

type Service struct {
	config         *config.Config
	networkService *network.Service
	agentGateway   domain.AgentGateway
	beClient       *beclient.Client
}

func ProvideService(config *config.Config, ns *network.Service, gw domain.AgentGateway, be *beclient.Client) *Service {
	return &Service{
		config:         config,
		networkService: ns,
		agentGateway:   gw,
		beClient:       be,
	}
}

func (s *Service) Setup(data domain.SetupRequest) error {
	slog.Info("starting setup", "component", "device")
	result, err := s.networkService.SetupNetwork(data.SSID, data.Password)
	if err != nil {
		return fmt.Errorf("setup network: %w", err)
	}
	if !result {
		return fmt.Errorf("network setup failed")
	}

	if err := s.agentGateway.SetupAgent(data); err != nil {
		return err
	}

	llmAPIKey := data.LLMAPIKey
	llmModel := data.LLMModel
	llmBaseURL := data.LLMBaseURL
	channel := data.EffectiveChannel()

	s.config.LLMAPIKey = llmAPIKey
	s.config.LLMBaseURL = llmBaseURL
	s.config.LLMModel = llmModel
	s.config.Channel = channel
	switch channel {
	case "slack":
		s.config.SlackBotToken = data.SlackBotToken
		s.config.SlackAppToken = data.SlackAppToken
		s.config.SlackUserID = data.SlackUserID
	case "discord":
		s.config.DiscordBotToken = data.DiscordBotToken
		s.config.DiscordUserID = data.DiscordUserID
	default:
		s.config.TelegramBotToken = data.TelegramBotToken
		s.config.TelegramUserID = data.TelegramUserID
	}
	s.config.DeviceID = data.DeviceID
	s.config.DeepgramAPIKey = data.DeepgramAPIKey
	s.config.MQTTEndpoint = data.MQTTEndpoint
	s.config.MQTTUsername = data.MQTTUsername
	s.config.MQTTPassword = data.MQTTPassword
	s.config.MQTTPort = data.MQTTPort
	s.config.FAChannel = data.FAChannel
	s.config.FDChannel = data.FDChannel
	if err := s.config.Save(); err != nil {
		slog.Error("save config failed", "component", "device", "error", err)
	}
	slog.Info("config saved", "component", "device")

	// Wait for agent gateway to be ready before marking device as working.
	if ok := s.WaitForAgentReady(120 * time.Second); !ok {
		return fmt.Errorf("agent gateway ready timeout, something went wrong")
	}

	s.config.SetUpCompleted = true
	if err := s.config.Save(); err != nil {
		slog.Error("save config failed", "component", "device", "error", err)
	}

	slog.Info("agent gateway is ready", "component", "device")
	if s.beClient != nil && llmAPIKey != "" {
		s.beClient.PingSafe(llmAPIKey, beclient.PingPayload{
			Status:         "working",
			SetupCompleted: true,
			Mac:            GetDeviceMac(),
			Version:        config.LumiVersion,
		})
	}
	return nil
}

// AddChannel adds a messaging channel to the agent without re-running full setup.
func (s *Service) AddChannel(data domain.AddChannelRequest) error {
	if err := s.agentGateway.AddChannel(data); err != nil {
		return fmt.Errorf("add channel in agent: %w", err)
	}

	channel := data.EffectiveChannel()
	s.config.Channel = channel
	switch channel {
	case "slack":
		s.config.SlackBotToken = data.SlackBotToken
		s.config.SlackAppToken = data.SlackAppToken
		s.config.SlackUserID = data.SlackUserID
	case "discord":
		s.config.DiscordBotToken = data.DiscordBotToken
		s.config.DiscordUserID = data.DiscordUserID
	default:
		s.config.TelegramBotToken = data.TelegramBotToken
		s.config.TelegramUserID = data.TelegramUserID
	}
	if err := s.config.Save(); err != nil {
		slog.Error("save config failed", "component", "device", "error", err)
	}
	slog.Info("added channel", "component", "device", "channel", channel)
	return nil
}

// StartStatusReporter periodically pings the autonomous backend.
// Uses LLMAPIKey as Bearer token. Exits when ctx is cancelled.
// If the backend response contains MQTT config, it saves to config (triggers config notify).
func (s *Service) StartStatusReporter(ctx context.Context) {
	if s.beClient == nil || s.config.LLMAPIKey == "" {
		return
	}
	ticker := time.NewTicker(beclient.StatusReportInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if !s.agentGateway.IsReady() {
				continue
			}
			resp := s.beClient.PingSafe(s.config.LLMAPIKey, beclient.PingPayload{
				Status:         "working",
				SetupCompleted: s.config.SetUpCompleted,
				Mac:            GetDeviceMac(),
				Version:        config.LumiVersion,
			})
			dump, _ := json.Marshal(resp)
			slog.Debug("received response from backend", "component", "status-reporter", "response", string(dump))
			if resp.DeviceID != "" && resp.DeviceID != s.config.DeviceID {
				s.config.DeviceID = resp.DeviceID
			}
			if resp.HasMQTT() && resp.GetMQTT().Endpoint != s.config.MQTTEndpoint {
				mqttCfg := resp.GetMQTT()
				slog.Info("received MQTT config from backend", "component", "status-reporter", "endpoint", mqttCfg.Endpoint)
				s.config.MQTTEndpoint = mqttCfg.Endpoint
				port, _ := strconv.Atoi(mqttCfg.Port)
				s.config.MQTTPort = port
				s.config.MQTTUsername = mqttCfg.Username
				s.config.MQTTPassword = mqttCfg.Password
				s.config.FAChannel = mqttCfg.FaChannel
				s.config.FDChannel = mqttCfg.FdChannel
				if err := s.config.Save(); err != nil {
					slog.Error("save MQTT config failed", "component", "status-reporter", "error", err)
				}
			}
		}
	}
}

// WaitForAgentReady polls agentGateway.IsReady until it returns true or the timeout elapses.
func (s *Service) WaitForAgentReady(timeout time.Duration) bool {
	if s.agentGateway == nil {
		return false
	}
	deadline := time.Now().Add(timeout)
	for {
		if s.agentGateway.IsReady() {
			return true
		}
		if time.Now().After(deadline) {
			return false
		}
		time.Sleep(500 * time.Millisecond)
	}
}
