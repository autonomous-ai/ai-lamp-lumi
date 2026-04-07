package openclaw

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/lib/flow"
	"go-lamp.autonomous.ai/lib/lelamp"
	"go-lamp.autonomous.ai/server/config"
)

const (
	defaultGatewayWSURL = "ws://127.0.0.1:18789"
	customProviderName  = "autonomous"
	defaultGatewayMode  = "local"
	defaultGatewayBind  = "loopback"
	defaultGatewayPort  = 18789
	openclawRuntimeUser = "root"
	defaultModelKey     = "claude-haiku-4-5"
)

// Compile-time check: *Service implements domain.AgentGateway.
var _ domain.AgentGateway = (*Service)(nil)

// Service provides setup, reset, restart of openclaw config/gateway and StartWS.
type Service struct {
	config      *config.Config
	monitorBus  *monitor.Bus
	wsConnected atomic.Bool // true when gateway WebSocket is connected and ready to receive messages
	activeTurn  atomic.Bool // true while agent is processing a turn (lifecycle start → end)

	// wsConn is the active WebSocket connection; guarded by wsMu.
	wsConn *websocket.Conn
	wsMu   sync.Mutex
	// lastSessionKey is the most recent session key observed from agent lifecycle events.
	lastSessionKey atomic.Value // string
	// reqCounter is used to generate unique request IDs for outgoing RPC calls.
	reqCounter atomic.Int64

	// pendingRPC tracks in-flight RPC requests waiting for a response.
	pendingRPCMu sync.Mutex
	pendingRPC   map[string]chan json.RawMessage // reqID → response channel
}

// ProvideService constructs the openclaw service.
func ProvideService(cfg *config.Config, bus *monitor.Bus) *Service {
	return &Service{
		config:     cfg,
		monitorBus: bus,
		pendingRPC: make(map[string]chan json.RawMessage),
	}
}

// defaultModels is the hardcoded list of supported models.
var defaultModels = []domain.LLMModel{
	{
		Key:       "claude-opus-4-6",
		Name:      "claude-opus-4-6",
		Reasoning: true,
		Input:     []string{"text", "image"},
		Privacy:   "private",
		Capabilities: &domain.LLMModelCapabilities{
			SupportsReasoning:       true,
			SupportsVision:          true,
			SupportsFunctionCalling: true,
		},
	},
	{
		Key:       "claude-haiku-4-5",
		Name:      "claude-haiku-4-5",
		Reasoning: true,
		Input:     []string{"text", "image"},
		Privacy:   "private",
		Capabilities: &domain.LLMModelCapabilities{
			SupportsReasoning:       true,
			SupportsVision:          true,
			SupportsFunctionCalling: true,
		},
	},
}

// listModelsFromAPI returns the hardcoded default models list.
func (s *Service) listModelsFromAPI(apiBaseURL string) (*domain.LLMModelsListResponse, error) {
	return &domain.LLMModelsListResponse{
		Count:  len(defaultModels),
		Models: defaultModels,
	}, nil
}

// Name returns the display name of this agent gateway.
func (s *Service) Name() string {
	return "OpenClaw"
}

// IsReady returns true when the gateway WebSocket is connected and OpenClaw is ready to receive messages.
func (s *Service) IsReady() bool {
	return s.wsConnected.Load()
}

// IsBusy returns true while the agent is processing a turn (between lifecycle start and end).
func (s *Service) IsBusy() bool {
	return s.activeTurn.Load()
}

// SetBusy marks the agent as busy or idle. Called by the SSE handler on lifecycle start/end.
func (s *Service) SetBusy(busy bool) {
	s.activeTurn.Store(busy)
}

// SetupAgent writes openclaw.json from the setup request and restarts the gateway.
func (s *Service) SetupAgent(data domain.SetupRequest) error {
	slog.Debug("checking openclaw in PATH", "component", "openclaw")
	if _, err := exec.LookPath("openclaw"); err != nil {
		return fmt.Errorf("openclaw not found in PATH: %w", err)
	}
	slog.Debug("openclaw found", "component", "openclaw")

	llmAPIKey := data.LLMAPIKey
	llmBaseURL := data.LLMBaseURL
	llmModel := data.LLMModel
	if llmModel == "" {
		llmModel = defaultModelKey
	}
	channel := data.EffectiveChannel()

	configPath := filepath.Join(s.config.OpenclawConfigDir, "openclaw.json")
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		slog.Debug("config does not exist, running onboardOpenclaw", "component", "openclaw")
		if err := s.onboardOpenclaw(); err != nil {
			return fmt.Errorf("onboard openclaw: %w", err)
		}
	}
	slog.Debug("loading config", "component", "openclaw", "path", configPath)
	var configData map[string]interface{}
	if data, err := os.ReadFile(configPath); err == nil {
		if err := json.Unmarshal(data, &configData); err != nil {
			return fmt.Errorf("parse openclaw config: %w", err)
		}
		slog.Debug("config loaded and parsed", "component", "openclaw")
	} else {
		configData = make(map[string]interface{})
		slog.Debug("no existing config, starting fresh", "component", "openclaw")
	}

	slog.Debug("listing models from API", "component", "openclaw", "baseURL", llmBaseURL)
	modelsResp, err := s.listModelsFromAPI(llmBaseURL)
	if err != nil {
		return fmt.Errorf("list llm models from api: %w", err)
	}
	slog.Debug("got models from API", "component", "openclaw", "count", len(modelsResp.Models))

	if len(modelsResp.Models) == 0 {
		return fmt.Errorf("no llm models found")
	}

	slog.Debug("resolving config model in list", "component", "openclaw", "model", llmModel)
	defaultModel, err := findModelByLLMModel(modelsResp.Models, llmModel)
	if err != nil {
		return err
	}
	slog.Debug("selected default model", "component", "openclaw", "key", defaultModel.Key, "name", defaultModel.Name)

	slog.Debug("building models.providers.autonomous", "component", "openclaw")
	modelsMap := ensureMap(configData, "models")
	modelsMap["mode"] = "merge"
	providersMap := ensureMap(modelsMap, "providers")
	modelsEntries := make([]any, 0, len(modelsResp.Models))
	for _, m := range modelsResp.Models {
		if s.config.LLMThinkingDisabled() {
			m.Reasoning = false
		}
		modelsEntries = append(modelsEntries, openclawModelToProviderEntry(m))
	}
	providersMap[customProviderName] = map[string]any{
		"baseUrl": llmBaseURL,
		"api":     defaultModel.OpenClawAPIType(),
		"apiKey":  llmAPIKey,
		"models":  modelsEntries,
	}
	configData["models"] = modelsMap

	slog.Debug("building agents.defaults", "component", "openclaw")
	agentsMap := ensureMap(configData, "agents")
	defaultsMap := ensureMap(agentsMap, "defaults")
	workspace := filepath.Join(s.config.OpenclawConfigDir, "workspace")
	defaultsMap["workspace"] = workspace
	defaultsMap["elevatedDefault"] = "full"
	sandboxMap := ensureMap(defaultsMap, "sandbox")
	sandboxMap["mode"] = "off"
	defaultsMap["sandbox"] = sandboxMap
	agentModelsMap := ensureMap(defaultsMap, "models")
	for _, m := range modelsResp.Models {
		agentModelsMap[m.Key] = map[string]any{}
	}
	defaultsMap["model"] = map[string]any{
		"primary": fmt.Sprintf("%s/%s", customProviderName, defaultModel.Name),
	}
	defaultsMap["models"] = agentModelsMap
	agentsMap["defaults"] = defaultsMap
	configData["agents"] = agentsMap

	channelsMap := ensureMap(configData, "channels")
	pluginsMap := ensureMap(configData, "plugins")
	entriesMap := ensureMap(pluginsMap, "entries")

	switch channel {
	case "slack":
		slog.Debug("setting channels.slack (socket mode)", "component", "openclaw")
		slackMap := ensureMap(channelsMap, "slack")
		slackMap["enabled"] = true
		slackMap["mode"] = "socket"
		slackMap["botToken"] = data.SlackBotToken
		slackMap["appToken"] = data.SlackAppToken
		if data.SlackUserID != "" {
			slackMap["dmPolicy"] = "allowlist"
			slackMap["allowFrom"] = mergeStringList(slackMap["allowFrom"], data.SlackUserID)
		} else {
			slackMap["dmPolicy"] = "open"
			slackMap["allowFrom"] = mergeStringList(slackMap["allowFrom"], "*")
		}
		channelsMap["slack"] = slackMap
		if telegramMap, ok := channelsMap["telegram"].(map[string]any); ok {
			telegramMap["enabled"] = false
		}
		slackEntryMap := ensureMap(entriesMap, "slack")
		slackEntryMap["enabled"] = true
	case "discord":
		slog.Debug("setting channels.discord", "component", "openclaw")
		discordMap := ensureMap(channelsMap, "discord")
		discordMap["enabled"] = true
		discordMap["dmPolicy"] = "allowlist"
		discordMap["token"] = data.DiscordBotToken
		discordMap["allowFrom"] = mergeStringList(discordMap["allowFrom"], data.DiscordUserID)
		if data.DiscordGuildID != "" {
			discordMap["groupPolicy"] = "allowlist"
			discordMap["guilds"] = map[string]any{
				data.DiscordGuildID: map[string]any{
					"requireMention": false,
					"users": []string{
						data.DiscordUserID,
					},
				},
			}
		}
		channelsMap["discord"] = discordMap
		discordEntryMap := ensureMap(entriesMap, "discord")
		discordEntryMap["enabled"] = true
	default:
		slog.Debug("setting channels.telegram", "component", "openclaw")
		telegramMap := ensureMap(channelsMap, "telegram")
		telegramMap["enabled"] = true
		telegramMap["botToken"] = data.TelegramBotToken
		if data.TelegramUserID != "" {
			telegramMap["dmPolicy"] = "allowlist"
			telegramMap["allowFrom"] = mergeStringList(telegramMap["allowFrom"], data.TelegramUserID)
		} else {
			telegramMap["dmPolicy"] = "open"
			telegramMap["allowFrom"] = mergeStringList(telegramMap["allowFrom"], "*")
		}
		channelsMap["telegram"] = telegramMap
		telegramEntryMap := ensureMap(entriesMap, "telegram")
		telegramEntryMap["enabled"] = true
	}
	configData["channels"] = channelsMap

	slog.Debug("ensuring gateway defaults", "component", "openclaw")
	gatewayMap := ensureMap(configData, "gateway")
	setDefaultValue(gatewayMap, "mode", defaultGatewayMode)
	setDefaultValue(gatewayMap, "bind", defaultGatewayBind)
	setDefaultValue(gatewayMap, "port", defaultGatewayPort)
	gatewayAuthMap := ensureMap(gatewayMap, "auth")
	setDefaultValue(gatewayAuthMap, "mode", "token")
	if existingToken := strings.TrimSpace(getStringValue(gatewayAuthMap, "token")); existingToken == "" {
		token, err := generateGatewayToken()
		if err != nil {
			return fmt.Errorf("generate gateway token: %w", err)
		}
		gatewayAuthMap["token"] = token
	}
	gatewayMap["auth"] = gatewayAuthMap
	configData["gateway"] = gatewayMap

	slog.Debug("ensuring full-access tools defaults", "component", "openclaw")
	toolsMap := ensureMap(configData, "tools")
	toolsMap["profile"] = "full"
	execMap := ensureMap(toolsMap, "exec")
	execMap["host"] = "gateway"
	execMap["security"] = "full"
	execMap["ask"] = "off"
	toolsMap["exec"] = execMap
	elevatedMap := ensureMap(toolsMap, "elevated")
	elevatedMap["enabled"] = true
	elevatedAllowFrom := ensureMap(elevatedMap, "allowFrom")
	elevatedAllowFrom[channel] = []any{"*"}
	elevatedMap["allowFrom"] = elevatedAllowFrom
	toolsMap["elevated"] = elevatedMap
	configData["tools"] = toolsMap

	slog.Debug("ensuring messages defaults", "component", "openclaw")
	messagesMap := ensureMap(configData, "messages")
	messagesMap["responsePrefix"] = "auto"
	messagesMap["ackReactionScope"] = "all"
	messagesMap["removeAckAfterReply"] = true
	configData["messages"] = messagesMap

	slog.Debug("ensuring logging defaults", "component", "openclaw")
	loggingMap := ensureMap(configData, "logging")
	loggingMap["consoleStyle"] = "pretty"
	loggingMap["file"] = "/var/log/openclaw/lumi.log"
	loggingMap["level"] = "debug"
	configData["logging"] = loggingMap

	slog.Debug("ensuring commands defaults", "component", "openclaw")
	commandsMap := ensureMap(configData, "commands")
	commandsMap["native"] = true
	commandsMap["nativeSkills"] = true
	commandsMap["text"] = true
	commandsMap["bash"] = true
	commandsMap["bashForegroundMs"] = 2000
	commandsMap["config"] = true
	commandsMap["debug"] = true
	commandsMap["restart"] = true
	commandsMap["useAccessGroups"] = false
	commandsMap["ownerAllowFrom"] = []any{"*"}
	configData["commands"] = commandsMap

	slog.Debug("ensuring skills defaults", "component", "openclaw")
	skillsMap := ensureMap(configData, "skills")
	loadMap := ensureMap(skillsMap, "load")
	skillsDir := filepath.Join(workspace, "skills")
	loadMap["extraDirs"] = []any{skillsDir}
	loadMap["watch"] = true
	skillsMap["load"] = loadMap
	configData["skills"] = skillsMap

	slog.Debug("marshalling and writing openclaw.json", "component", "openclaw")
	written, err := json.MarshalIndent(configData, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal openclaw config: %w", err)
	}
	if err := os.MkdirAll(s.config.OpenclawConfigDir, 0755); err != nil {
		return fmt.Errorf("create openclaw config dir: %w", err)
	}
	if err := os.WriteFile(configPath, written, 0600); err != nil {
		return fmt.Errorf("write openclaw config: %w", err)
	}
	if err := chownRuntimeUserIfRoot(configPath, openclawRuntimeUser); err != nil {
		return fmt.Errorf("set openclaw config ownership: %w", err)
	}
	slog.Info("wrote openclaw config", "component", "openclaw", "path", configPath)

	slog.Debug("restarting openclaw gateway", "component", "openclaw")
	if err := restartOpenclawGateway(); err != nil {
		return err
	}
	slog.Info("gateway restart completed", "component", "openclaw")
	return nil
}

// AddChannel adds a messaging channel to openclaw.json (multi-channel) and restarts the gateway.
func (s *Service) AddChannel(data domain.AddChannelRequest) error {
	channel := data.EffectiveChannel()

	configPath := filepath.Join(s.config.OpenclawConfigDir, "openclaw.json")
	var configData map[string]interface{}
	if raw, err := os.ReadFile(configPath); err == nil {
		if err := json.Unmarshal(raw, &configData); err != nil {
			return fmt.Errorf("parse openclaw config: %w", err)
		}
	} else {
		return fmt.Errorf("read openclaw config: %w (device must be set up first)", err)
	}

	channelsMap := ensureMap(configData, "channels")
	pluginsMap := ensureMap(configData, "plugins")
	entriesMap := ensureMap(pluginsMap, "entries")

	switch channel {
	case "slack":
		slackMap := ensureMap(channelsMap, "slack")
		slackMap["enabled"] = true
		slackMap["mode"] = "socket"
		slackMap["botToken"] = data.SlackBotToken
		slackMap["appToken"] = data.SlackAppToken
		if data.SlackUserID != "" {
			slackMap["dmPolicy"] = "allowlist"
			slackMap["allowFrom"] = mergeStringList(slackMap["allowFrom"], data.SlackUserID)
		} else {
			slackMap["dmPolicy"] = "open"
			slackMap["allowFrom"] = mergeStringList(slackMap["allowFrom"], "*")
		}
		channelsMap["slack"] = slackMap
		slackEntryMap := ensureMap(entriesMap, "slack")
		slackEntryMap["enabled"] = true
	case "discord":
		discordMap := ensureMap(channelsMap, "discord")
		discordMap["enabled"] = true
		discordMap["dmPolicy"] = "allowlist"
		discordMap["token"] = data.DiscordBotToken
		discordMap["allowFrom"] = mergeStringList(discordMap["allowFrom"], data.DiscordUserID)
		if data.DiscordGuildID != "" {
			discordMap["groupPolicy"] = "allowlist"
			discordMap["guilds"] = map[string]any{
				data.DiscordGuildID: map[string]any{
					"requireMention": false,
					"users": []string{
						data.DiscordUserID,
					},
				},
			}
		}
		channelsMap["discord"] = discordMap
		discordEntryMap := ensureMap(entriesMap, "discord")
		discordEntryMap["enabled"] = true
	default:
		telegramMap := ensureMap(channelsMap, "telegram")
		telegramMap["enabled"] = true
		telegramMap["botToken"] = data.TelegramBotToken
		if data.TelegramUserID != "" {
			telegramMap["dmPolicy"] = "allowlist"
			telegramMap["allowFrom"] = mergeStringList(telegramMap["allowFrom"], data.TelegramUserID)
		} else {
			telegramMap["dmPolicy"] = "open"
			telegramMap["allowFrom"] = mergeStringList(telegramMap["allowFrom"], "*")
		}
		channelsMap["telegram"] = telegramMap
		telegramEntryMap := ensureMap(entriesMap, "telegram")
		telegramEntryMap["enabled"] = true
	}
	configData["channels"] = channelsMap

	// Add elevated.allowFrom for the new channel
	if toolsMap, ok := configData["tools"].(map[string]any); ok {
		if elevatedMap, ok := toolsMap["elevated"].(map[string]any); ok {
			elevatedAllowFrom := ensureMap(elevatedMap, "allowFrom")
			elevatedAllowFrom[channel] = []any{"*"}
			elevatedMap["allowFrom"] = elevatedAllowFrom
		}
	}

	written, err := json.MarshalIndent(configData, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal openclaw config: %w", err)
	}
	if err := os.WriteFile(configPath, written, 0600); err != nil {
		return fmt.Errorf("write openclaw config: %w", err)
	}
	if err := chownRuntimeUserIfRoot(configPath, openclawRuntimeUser); err != nil {
		return fmt.Errorf("set openclaw config ownership: %w", err)
	}
	slog.Info("wrote openclaw config", "component", "openclaw", "path", configPath, "channel", channel)

	if err := restartOpenclawGateway(); err != nil {
		return err
	}
	slog.Info("gateway restarted", "component", "openclaw")
	return nil
}

// ResetAgent overwrites openclaw.json with a minimal default config and restarts the gateway.
func (s *Service) ResetAgent() error {
	slog.Debug("checking openclaw in PATH", "component", "openclaw")
	if _, err := exec.LookPath("openclaw"); err != nil {
		return fmt.Errorf("openclaw not found in PATH: %w", err)
	}
	slog.Debug("openclaw found", "component", "openclaw")
	if err := os.RemoveAll(s.config.OpenclawConfigDir); err != nil {
		return fmt.Errorf("remove openclaw config dir: %w", err)
	}
	if err := os.MkdirAll(s.config.OpenclawConfigDir, 0755); err != nil {
		return fmt.Errorf("recreate openclaw config dir: %w", err)
	}
	configPath := filepath.Join(s.config.OpenclawConfigDir, "openclaw.json")
	if err := s.onboardOpenclaw(); err != nil {
		return fmt.Errorf("onboard openclaw: %w", err)
	}
	if err := chownRuntimeUserIfRoot(configPath, openclawRuntimeUser); err != nil {
		return fmt.Errorf("set openclaw config ownership: %w", err)
	}
	slog.Info("wrote default config", "component", "openclaw", "path", configPath)

	slog.Debug("restarting openclaw gateway", "component", "openclaw")
	if err := restartOpenclawGateway(); err != nil {
		return err
	}
	slog.Info("reset completed", "component", "openclaw")
	return nil
}

// RefreshModelsConfig patches the models reasoning fields in openclaw.json
// based on current config and restarts the agent. Safe to call after UpdateConfig.
func (s *Service) RefreshModelsConfig() error {
	configPath := filepath.Join(s.config.OpenclawConfigDir, "openclaw.json")
	data, err := os.ReadFile(configPath)
	if err != nil {
		return fmt.Errorf("read openclaw config: %w", err)
	}
	var configData map[string]any
	if err := json.Unmarshal(data, &configData); err != nil {
		return fmt.Errorf("parse openclaw config: %w", err)
	}

	disableThinking := s.config.LLMThinkingDisabled()

	// Patch models.providers.autonomous.models[*].reasoning
	if modelsMap, ok := configData["models"].(map[string]any); ok {
		if providersMap, ok := modelsMap["providers"].(map[string]any); ok {
			if providerEntry, ok := providersMap[customProviderName].(map[string]any); ok {
				if modelsList, ok := providerEntry["models"].([]any); ok {
					for _, entry := range modelsList {
						if m, ok := entry.(map[string]any); ok {
							if disableThinking {
								m["reasoning"] = false
							} else {
								m["reasoning"] = true
							}
						}
					}
				}
			}
		}
	}

	written, err := json.MarshalIndent(configData, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal openclaw config: %w", err)
	}
	if err := os.WriteFile(configPath, written, 0600); err != nil {
		return fmt.Errorf("write openclaw config: %w", err)
	}
	slog.Info("refreshed models config in openclaw.json", "component", "openclaw", "disableThinking", disableThinking)

	if err := restartOpenclawGateway(); err != nil {
		return err
	}
	slog.Info("restart completed after models config refresh", "component", "openclaw")
	return nil
}

// RestartAgent restarts the openclaw gateway only.
func (s *Service) RestartAgent() error {
	slog.Debug("restarting openclaw gateway", "component", "openclaw")
	if err := restartOpenclawGateway(); err != nil {
		return err
	}
	slog.Info("restart completed", "component", "openclaw")
	return nil
}

// StartWS connects to the gateway WebSocket and runs the read loop, calling handler for each event.
// It runs until ctx is cancelled. Auto-reconnects when disconnected.
func (s *Service) StartWS(ctx context.Context, handler domain.AgentEventHandler) {
	backoff := 5 * time.Second
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		err := s.runWSConn(ctx, handler)
		if ctx.Err() != nil {
			return
		}
		if err != nil {
			slog.Warn("websocket disconnected, reconnecting", "component", "openclaw", "error", err, "backoff", backoff)
			flow.Log("ws_disconnect", map[string]any{"error": err.Error(), "backoff_s": backoff.Seconds()})
		} else {
			slog.Warn("websocket connection closed, reconnecting", "component", "openclaw", "backoff", backoff)
			flow.Log("ws_disconnect", map[string]any{"reason": "closed", "backoff_s": backoff.Seconds()})
		}
		if !sleepCtx(ctx, backoff) {
			return
		}
	}
}

func (s *Service) runWSConn(ctx context.Context, handler domain.AgentEventHandler) error {
	s.wsConnected.Store(false)
	defer s.wsConnected.Store(false)
	defer s.activeTurn.Store(false) // clear busy on disconnect — lifecycle_end may never arrive

	connStart := flow.Start("ws_connect", map[string]any{"url": defaultGatewayWSURL})

	dialer := websocket.Dialer{HandshakeTimeout: 10 * time.Second}
	conn, resp, err := dialer.DialContext(ctx, defaultGatewayWSURL, http.Header{})
	if err != nil {
		if resp != nil {
			flow.End("ws_connect", connStart, map[string]any{"error": err.Error(), "status": resp.Status})
			return fmt.Errorf("dial %s: %w (status %s)", defaultGatewayWSURL, err, resp.Status)
		}
		flow.End("ws_connect", connStart, map[string]any{"error": err.Error()})
		return fmt.Errorf("dial %s: %w", defaultGatewayWSURL, err)
	}
	defer func() {
		s.wsMu.Lock()
		s.wsConn = nil
		s.wsMu.Unlock()
		conn.Close()
	}()

	// Read connect.challenge from gateway
	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	_, msg, err := conn.ReadMessage()
	if err != nil {
		return fmt.Errorf("read connect.challenge: %w", err)
	}
	conn.SetReadDeadline(time.Time{})
	slog.Debug("initial event received", "component", "openclaw", "event", string(msg))

	// Parse nonce from connect.challenge
	var challenge struct {
		Payload struct {
			Nonce string `json:"nonce"`
		} `json:"payload"`
	}
	if err := json.Unmarshal(msg, &challenge); err != nil || challenge.Payload.Nonce == "" {
		return fmt.Errorf("parse connect.challenge nonce: %w", err)
	}
	nonce := challenge.Payload.Nonce

	token, err := s.readGatewayToken()
	if err != nil {
		flow.End("ws_connect", connStart, map[string]any{"error": "read token: " + err.Error()})
		return fmt.Errorf("read gateway token: %w", err)
	}

	di, err := s.loadOrCreateDeviceIdentity()
	if err != nil {
		return fmt.Errorf("device identity: %w", err)
	}

	signedAt := time.Now().UnixMilli()
	signature := di.signConnectPayload(token, nonce, signedAt)

	connectReq := map[string]interface{}{
		"type":   "req",
		"id":     "lumi-1",
		"method": "connect",
		"params": map[string]interface{}{
			"minProtocol": 3,
			"maxProtocol": 3,
			"client": map[string]interface{}{
				"id":       "node-host",
				"version":  "1.0",
				"platform": "linux",
				"mode":     "node",
			},
			"role":   "operator",
			"scopes": []string{"operator.read", "operator.write", "events.read"},
			"caps":   []string{"thinking-events", "tool-events"},
			"auth":   map[string]interface{}{"token": token},
			"device": map[string]interface{}{
				"id":        di.DeviceID,
				"publicKey": base64.StdEncoding.EncodeToString(di.PublicKey),
				"signature": signature,
				"signedAt":  signedAt,
				"nonce":     nonce,
			},
		},
	}
	connectBody, _ := json.Marshal(connectReq)
	if err := conn.WriteMessage(websocket.TextMessage, connectBody); err != nil {
		return fmt.Errorf("write connect: %w", err)
	}

	// Read connect response — extract sessionKey if present
	conn.SetReadDeadline(time.Now().Add(10 * time.Second))
	_, connectResp, err := conn.ReadMessage()
	if err != nil {
		return fmt.Errorf("read connect response: %w", err)
	}
	conn.SetReadDeadline(time.Time{})
	slog.Debug("connect response", "component", "openclaw", "response", string(connectResp))

	var connectResult struct {
		Type   string `json:"type"`
		Result struct {
			SessionKey string `json:"sessionKey"`
		} `json:"result"`
		Payload struct {
			Snapshot struct {
				SessionDefaults struct {
					MainSessionKey string `json:"mainSessionKey"`
				} `json:"sessionDefaults"`
			} `json:"snapshot"`
		} `json:"payload"`
	}
	if err := json.Unmarshal(connectResp, &connectResult); err == nil {
		sk := connectResult.Result.SessionKey
		if sk == "" {
			sk = connectResult.Payload.Snapshot.SessionDefaults.MainSessionKey
		}
		if sk != "" {
			s.SetSessionKey(sk)
			slog.Info("session key from connect", "component", "openclaw", "sessionKey", sk)
		}
	}

	// If no session key yet, request sessions.list to find an active session
	if s.GetSessionKey() == "" {
		listReq := map[string]interface{}{
			"type":   "req",
			"id":     "lumi-sessions",
			"method": "sessions.list",
		}
		listBody, _ := json.Marshal(listReq)
		if err := conn.WriteMessage(websocket.TextMessage, listBody); err == nil {
			conn.SetReadDeadline(time.Now().Add(5 * time.Second))
			_, listResp, err := conn.ReadMessage()
			conn.SetReadDeadline(time.Time{})
			if err == nil {
				slog.Debug("sessions.list response", "component", "openclaw", "response", string(listResp))
				var listResult struct {
					Result struct {
						Sessions []struct {
							SessionKey string `json:"sessionKey"`
						} `json:"sessions"`
					} `json:"result"`
				}
				if json.Unmarshal(listResp, &listResult) == nil && len(listResult.Result.Sessions) > 0 {
					sk := listResult.Result.Sessions[0].SessionKey
					s.SetSessionKey(sk)
					slog.Info("session key from sessions.list", "component", "openclaw", "sessionKey", sk)
				}
			}
		}
	}

	s.wsMu.Lock()
	s.wsConn = conn
	s.wsMu.Unlock()
	s.wsConnected.Store(true)
	flow.End("ws_connect", connStart, map[string]any{"session_key": s.GetSessionKey() != ""})
	flow.Log("ws_ready", map[string]any{"session": s.GetSessionKey() != ""})

	// Subscribe to session events so we receive tool events for all turns
	// (including Telegram-initiated turns where Lumi didn't call chat.send).
	subReq := map[string]interface{}{
		"type":   "req",
		"id":     fmt.Sprintf("sub-%d", s.reqCounter.Add(1)),
		"method": "sessions.subscribe",
		"params": map[string]interface{}{},
	}
	if body, err := json.Marshal(subReq); err == nil {
		s.wsMu.Lock()
		_ = conn.WriteMessage(websocket.TextMessage, body)
		s.wsMu.Unlock()
		slog.Info("sessions.subscribe sent", "component", "openclaw")
	}

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		_, msg, err := conn.ReadMessage()
		if err != nil {
			return err
		}

		// Try to extract sessionKey from any message (fallback if connect response didn't have it)
		if s.GetSessionKey() == "" {
			var raw struct {
				SessionKey string `json:"sessionKey"`
				Result     struct {
					SessionKey string `json:"sessionKey"`
				} `json:"result"`
				Payload json.RawMessage `json:"payload"`
			}
			if json.Unmarshal(msg, &raw) == nil {
				sk := raw.SessionKey
				if sk == "" {
					sk = raw.Result.SessionKey
				}
				if sk == "" && len(raw.Payload) > 0 {
					var p struct{ SessionKey string `json:"sessionKey"` }
					if json.Unmarshal(raw.Payload, &p) == nil {
						sk = p.SessionKey
					}
				}
				if sk != "" {
					s.SetSessionKey(sk)
				}
			}
		}

		// Dispatch RPC responses to pending callers before event handling.
		s.dispatchRPCResponse(msg)

		var evt domain.WSEvent
		if err := json.Unmarshal(msg, &evt); err != nil {
			continue
		}
		if handler != nil {
			if err := handler(ctx, evt); err != nil {
				return err
			}
		}
	}
}

// dispatchRPCResponse checks if msg is an RPC response and delivers it to the waiting caller.
func (s *Service) dispatchRPCResponse(msg []byte) {
	var frame struct {
		Type    string          `json:"type"`
		ID      string          `json:"id"`
		OK      bool            `json:"ok"`
		Payload json.RawMessage `json:"payload"`
	}
	if json.Unmarshal(msg, &frame) != nil || frame.Type != "res" || frame.ID == "" {
		return
	}
	s.pendingRPCMu.Lock()
	ch, ok := s.pendingRPC[frame.ID]
	if ok {
		delete(s.pendingRPC, frame.ID)
	}
	s.pendingRPCMu.Unlock()
	if ok {
		select {
		case ch <- frame.Payload:
		default:
		}
	}
}

// FetchChatHistory sends a chat.history RPC and returns the raw payload.
// Best-effort with a 3-second timeout; returns nil on any failure.
func (s *Service) FetchChatHistory(sessionKey string, limit int) (json.RawMessage, error) {
	s.wsMu.Lock()
	conn := s.wsConn
	s.wsMu.Unlock()
	if conn == nil {
		return nil, fmt.Errorf("websocket not connected")
	}
	if sessionKey == "" {
		sessionKey = s.GetSessionKey()
	}
	if sessionKey == "" {
		return nil, fmt.Errorf("no session key")
	}

	reqID := fmt.Sprintf("history-%d", s.reqCounter.Add(1))
	ch := make(chan json.RawMessage, 1)

	s.pendingRPCMu.Lock()
	s.pendingRPC[reqID] = ch
	s.pendingRPCMu.Unlock()

	req := map[string]interface{}{
		"type":   "req",
		"id":     reqID,
		"method": "chat.history",
		"params": map[string]interface{}{
			"sessionKey": sessionKey,
			"limit":      limit,
		},
	}
	body, err := json.Marshal(req)
	if err != nil {
		s.pendingRPCMu.Lock()
		delete(s.pendingRPC, reqID)
		s.pendingRPCMu.Unlock()
		return nil, fmt.Errorf("marshal chat.history: %w", err)
	}

	s.wsMu.Lock()
	conn = s.wsConn
	if conn == nil {
		s.wsMu.Unlock()
		s.pendingRPCMu.Lock()
		delete(s.pendingRPC, reqID)
		s.pendingRPCMu.Unlock()
		return nil, fmt.Errorf("websocket disconnected before send")
	}
	err = conn.WriteMessage(websocket.TextMessage, body)
	s.wsMu.Unlock()
	if err != nil {
		s.pendingRPCMu.Lock()
		delete(s.pendingRPC, reqID)
		s.pendingRPCMu.Unlock()
		return nil, fmt.Errorf("write chat.history: %w", err)
	}

	timer := time.NewTimer(3 * time.Second)
	defer timer.Stop()
	select {
	case payload := <-ch:
		return payload, nil
	case <-timer.C:
		s.pendingRPCMu.Lock()
		delete(s.pendingRPC, reqID)
		s.pendingRPCMu.Unlock()
		return nil, fmt.Errorf("chat.history timeout")
	}
}

func (s *Service) readGatewayToken() (string, error) {
	path := filepath.Join(s.config.OpenclawConfigDir, "openclaw.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	var cfg struct {
		Gateway struct {
			Auth struct {
				Token string `json:"token"`
			} `json:"auth"`
		} `json:"gateway"`
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return "", err
	}
	token := cfg.Gateway.Auth.Token
	if token == "" {
		return "", fmt.Errorf("gateway.auth.token is empty in %s", path)
	}
	return token, nil
}

func findModelByLLMModel(models []domain.LLMModel, llmModel string) (domain.LLMModel, error) {
	for _, m := range models {
		if m.Key == llmModel || strings.TrimPrefix(m.Key, fmt.Sprintf("%s/", customProviderName)) == llmModel || m.Name == llmModel {
			return m, nil
		}
	}
	return domain.LLMModel{}, fmt.Errorf("no model matching llm_model %q in openclaw models list", llmModel)
}

func openclawModelToProviderEntry(m domain.LLMModel) map[string]interface{} {
	contextWindow := 200000
	if m.ContextWindow != nil {
		contextWindow = *m.ContextWindow
	}
	maxTokens := 8192
	if m.MaxTokens != nil {
		maxTokens = *m.MaxTokens
	}
	return map[string]interface{}{
		"id":        m.Key,
		"name":      m.Name,
		"reasoning": m.Reasoning,
		"input":     m.Input,
		"cost": map[string]interface{}{
			"input":      0,
			"output":     0,
			"cacheRead":  0,
			"cacheWrite": 0,
		},
		"contextWindow": contextWindow,
		"maxTokens":     maxTokens,
	}
}

func ensureMap(parent map[string]any, key string) map[string]any {
	existing, _ := parent[key].(map[string]any)
	if existing != nil {
		return existing
	}
	created := make(map[string]any)
	parent[key] = created
	return created
}

func setDefaultValue(target map[string]any, key string, value any) {
	existing, ok := target[key]
	if !ok || existing == nil {
		target[key] = value
		return
	}
	if s, ok := existing.(string); ok && strings.TrimSpace(s) == "" {
		target[key] = value
		return
	}
	if n, ok := existing.(float64); ok && n <= 0 {
		target[key] = value
		return
	}
	if n, ok := existing.(int); ok && n <= 0 {
		target[key] = value
		return
	}
	if n, ok := existing.(int64); ok && n <= 0 {
		target[key] = value
	}
}

func mergeStringList(existing any, required ...string) []string {
	list := make([]string, 0)
	seen := map[string]struct{}{}
	appendIfMissing := func(v string) {
		v = strings.TrimSpace(v)
		if v == "" {
			return
		}
		if _, ok := seen[v]; ok {
			return
		}
		seen[v] = struct{}{}
		list = append(list, v)
	}
	switch values := existing.(type) {
	case string:
		appendIfMissing(values)
	case []string:
		for _, v := range values {
			appendIfMissing(v)
		}
	case []any:
		for _, item := range values {
			if v, ok := item.(string); ok {
				appendIfMissing(v)
			}
		}
	}
	for _, v := range required {
		appendIfMissing(v)
	}
	return list
}

func getStringValue(m map[string]any, key string) string {
	if m == nil {
		return ""
	}
	value, _ := m[key].(string)
	return value
}

func generateGatewayToken() (string, error) {
	buf := make([]byte, 24)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}

func chownRuntimeUserIfRoot(path, username string) error {
	if os.Geteuid() != 0 {
		return nil
	}
	u, err := user.Lookup(username)
	if err != nil {
		return fmt.Errorf("lookup user %q: %w", username, err)
	}
	uid, err := strconv.Atoi(u.Uid)
	if err != nil {
		return fmt.Errorf("parse uid for %q: %w", username, err)
	}
	gid, err := strconv.Atoi(u.Gid)
	if err != nil {
		return fmt.Errorf("parse gid for %q: %w", username, err)
	}
	if err := os.Chown(path, uid, gid); err != nil {
		return fmt.Errorf("chown %s to %s: %w", path, username, err)
	}
	return nil
}

func (s *Service) onboardOpenclaw() error {
	// openclaw default home is ~/.openclaw; OpenclawConfigDir must match this path.
	// No env overrides needed — let openclaw use its standard paths.
	cmd := exec.Command("bash", "-c", "openclaw onboard --non-interactive --accept-risk")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("openclaw onboard: %w — output: %s", err, strings.TrimSpace(string(out)))
	}

	// After onboard, ensure openclaw.json points workspace to our config dir's workspace.
	// Since OpenclawConfigDir matches openclaw's default home (~/.openclaw), the workspace
	// is already at the correct path; we only patch the field to be explicit.
	configPath := fmt.Sprintf("%s/openclaw.json", s.config.OpenclawConfigDir)
	workspacePath := fmt.Sprintf("%s/workspace", s.config.OpenclawConfigDir)
	if configBytes, err := os.ReadFile(configPath); err == nil {
		var configData map[string]interface{}
		if err := json.Unmarshal(configBytes, &configData); err == nil {
			agentsMap, ok := configData["agents"].(map[string]interface{})
			if !ok {
				agentsMap = make(map[string]interface{})
				configData["agents"] = agentsMap
			}
			defaultsMap, ok := agentsMap["defaults"].(map[string]interface{})
			if !ok {
				defaultsMap = make(map[string]interface{})
				agentsMap["defaults"] = defaultsMap
			}
			defaultsMap["workspace"] = workspacePath
			// Remove "tailscale" section from gateway if present
			gateway, ok := configData["gateway"].(map[string]interface{})
			if ok {
				delete(gateway, "tailscale")
			}
			configData["gateway"] = gateway
			if outBytes, err := json.MarshalIndent(configData, "", "  "); err == nil {
				_ = os.WriteFile(configPath, outBytes, 0600)
			}
		}
	}

	return nil
}

func restartOpenclawGateway() error {
	if os.Geteuid() == 0 {
		if _, err := exec.LookPath("systemctl"); err == nil {
			out, err := exec.Command("systemctl", "restart", "openclaw").CombinedOutput()
			if err == nil {
				return nil
			}
			slog.Warn("systemctl restart failed, fallback", "component", "openclaw", "output", strings.TrimSpace(string(out)))
		}
	}
	out, err := exec.Command("openclaw", "gateway", "restart").CombinedOutput()
	if err == nil {
		return nil
	}
	output := strings.TrimSpace(string(out))
	lower := strings.ToLower(output)
	if strings.Contains(lower, "systemd user services are unavailable") ||
		strings.Contains(lower, "run the gateway in the foreground") {
		slog.Warn("no supported service manager, skip restart", "component", "openclaw", "output", output)
		return nil
	}
	return fmt.Errorf("openclaw gateway restart: %w - output: %s", err, output)
}

// --- Device identity (Ed25519) for gateway auth ---

const deviceKeyFile = "lumi-device-key.json"

type deviceIdentity struct {
	PublicKey  ed25519.PublicKey
	PrivateKey ed25519.PrivateKey
	DeviceID   string // hex(SHA-256(publicKey))
}

// loadOrCreateDeviceIdentity loads the Ed25519 keypair from disk, or generates
// a new one and persists it for future connections.
func (s *Service) loadOrCreateDeviceIdentity() (*deviceIdentity, error) {
	keyPath := filepath.Join(s.config.OpenclawConfigDir, deviceKeyFile)
	if data, err := os.ReadFile(keyPath); err == nil {
		var stored struct {
			PrivateKey string `json:"privateKey"` // hex-encoded 64-byte Ed25519 seed+pub
		}
		if err := json.Unmarshal(data, &stored); err == nil {
			privBytes, err := hex.DecodeString(stored.PrivateKey)
			if err == nil && len(privBytes) == ed25519.PrivateKeySize {
				priv := ed25519.PrivateKey(privBytes)
				pub := priv.Public().(ed25519.PublicKey)
				id := deriveDeviceID(pub)
				slog.Info("loaded device identity", "component", "openclaw", "deviceId", id)
				return &deviceIdentity{PublicKey: pub, PrivateKey: priv, DeviceID: id}, nil
			}
		}
	}

	// Generate new keypair
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("generate ed25519 key: %w", err)
	}
	id := deriveDeviceID(pub)

	stored := map[string]string{"privateKey": hex.EncodeToString(priv)}
	data, _ := json.MarshalIndent(stored, "", "  ")
	if err := os.WriteFile(keyPath, data, 0600); err != nil {
		return nil, fmt.Errorf("write device key: %w", err)
	}
	_ = chownRuntimeUserIfRoot(keyPath, openclawRuntimeUser)
	slog.Info("generated new device identity", "component", "openclaw", "deviceId", id)
	return &deviceIdentity{PublicKey: pub, PrivateKey: priv, DeviceID: id}, nil
}

// deriveDeviceID returns hex(SHA-256(rawPublicKey)).
func deriveDeviceID(pub ed25519.PublicKey) string {
	h := sha256.Sum256(pub)
	return hex.EncodeToString(h[:])
}

// signConnectPayload builds and signs the v2 payload for device auth.
// Format: v2|deviceId|clientId|clientMode|role|scopes|signedAtMs|token|nonce
func (di *deviceIdentity) signConnectPayload(token, nonce string, signedAt int64) string {
	payload := fmt.Sprintf("v2|%s|%s|%s|%s|%s|%d|%s|%s",
		di.DeviceID,
		"node-host",  // clientId
		"node",       // clientMode
		"operator",   // role
		"operator.read,operator.write,events.read", // scopes
		signedAt,
		token,
		nonce,
	)
	sig := ed25519.Sign(di.PrivateKey, []byte(payload))
	return base64.StdEncoding.EncodeToString(sig)
}

func sleepCtx(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}

// WatchIdentity polls IDENTITY.md in the OpenClaw workspace and pushes updated wake words
// to LeLamp whenever the agent's name changes (e.g. user says "call yourself Noah").
func (s *Service) WatchIdentity(ctx context.Context) {
	identityPath := filepath.Join(s.config.OpenclawConfigDir, "workspace", "IDENTITY.md")
	var lastName string
	for {
		if !sleepCtx(ctx, 5*time.Second) {
			return
		}
		data, err := os.ReadFile(identityPath)
		if err != nil {
			continue
		}
		name := parseIdentityName(string(data))
		if name == "" || name == lastName {
			continue
		}
		lastName = name
		words := buildWakeWords(name)
		slog.Info("agent renamed, updating wake words", "component", "openclaw", "name", name, "words", words)
		lelamp.SetVoiceConfig(words)
	}
}

// parseIdentityName extracts the agent name from IDENTITY.md content.
// Looks for a line matching: - **Name:** <value>
func parseIdentityName(content string) string {
	for _, line := range strings.Split(content, "\n") {
		line = strings.TrimSpace(line)
		// Match: - **Name:** Lumi  or  **Name:** Lumi
		lower := strings.ToLower(line)
		idx := strings.Index(lower, "**name:**")
		if idx < 0 {
			continue
		}
		name := strings.TrimSpace(line[idx+len("**name:**"):])
		// Strip trailing markdown (e.g. " — some description")
		if i := strings.IndexAny(name, "—-|"); i > 0 {
			name = strings.TrimSpace(name[:i])
		}
		if name != "" {
			return name
		}
	}
	return ""
}

// buildWakeWords generates wake word variants from an agent name.
func buildWakeWords(name string) []string {
	n := strings.ToLower(name)
	return []string{
		"hey " + n,
		n,
		"này " + n,
		"ê " + n,
		n + " ơi",
	}
}

// StartLeLampVoice starts the voice pipeline on LeLamp with API keys from config.
func (s *Service) StartLeLampVoice(deepgramKey, llmKey, llmBaseURL string) error {
	if deepgramKey == "" {
		return nil
	}
	url := "http://127.0.0.1:5001/voice/start"
	body, _ := json.Marshal(map[string]string{
		"deepgram_api_key": deepgramKey,
		"llm_api_key":      llmKey,
		"llm_base_url":     llmBaseURL,
	})
	resp, err := http.Post(url, "application/json", strings.NewReader(string(body)))
	if err != nil {
		return fmt.Errorf("POST /voice/start: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusOK {
		slog.Info("LeLamp voice pipeline started", "component", "openclaw")
		flow.Log("voice_pipeline_start", nil)
	}
	return nil
}

// stripForTTS removes markdown formatting and emoji so TTS reads clean spoken text.
func stripForTTS(text string) string {
	// Remove emoji (Unicode emoji ranges)
	emojiRe := regexp.MustCompile(`[\x{1F300}-\x{1F9FF}\x{2600}-\x{27BF}\x{FE00}-\x{FE0F}\x{200D}\x{20E3}\x{E0020}-\x{E007F}]`)
	text = emojiRe.ReplaceAllString(text, "")
	// Remove markdown bold/italic markers
	text = regexp.MustCompile(`\*{1,3}([^*]+)\*{1,3}`).ReplaceAllString(text, "$1")
	text = regexp.MustCompile(`_{1,3}([^_]+)_{1,3}`).ReplaceAllString(text, "$1")
	// Remove markdown links [text](url) → text
	text = regexp.MustCompile(`\[([^\]]+)\]\([^)]+\)`).ReplaceAllString(text, "$1")
	// Remove code blocks and inline code
	text = regexp.MustCompile("```[\\s\\S]*?```").ReplaceAllString(text, "")
	text = regexp.MustCompile("`([^`]+)`").ReplaceAllString(text, "$1")
	// Collapse whitespace
	text = regexp.MustCompile(`\s+`).ReplaceAllString(text, " ")
	return strings.TrimSpace(text)
}


// SendToLeLampTTS posts response text to LeLamp for TTS playback.
// Text must already be stripped of HW markers by the caller (SSE handler).
func (s *Service) SendToLeLampTTS(text string) error {
	text = stripForTTS(text)
	if text == "" {
		return nil
	}
	url := "http://127.0.0.1:5001/voice/speak"
	body, _ := json.Marshal(map[string]string{"text": text})
	resp, err := http.Post(url, "application/json", strings.NewReader(string(body)))
	if err != nil {
		return fmt.Errorf("POST /voice/speak: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("POST /voice/speak returned %d", resp.StatusCode)
	}
	slog.Info("TTS sent", "component", "openclaw", "text", text[:min(len(text), 80)])

	s.monitorBus.Push(domain.MonitorEvent{
		Type:    "tts",
		Summary: text,
	})

	return nil
}

// SetSessionKey stores the session key for outgoing chat messages.
func (s *Service) SetSessionKey(key string) {
	s.lastSessionKey.Store(key)
	slog.Info("session key stored", "component", "openclaw", "key", key)
	flow.Log("session_key_acquired", map[string]any{"key_len": len(key)})
}

// GetSessionKey returns the last observed session key, or empty string if none.
func (s *Service) GetSessionKey() string {
	v, _ := s.lastSessionKey.Load().(string)
	return v
}

// GetConfigJSON reads and returns the raw bytes of openclaw.json.
func (s *Service) GetConfigJSON() (json.RawMessage, error) {
	path := filepath.Join(s.config.OpenclawConfigDir, "openclaw.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read openclaw.json: %w", err)
	}
	return json.RawMessage(data), nil
}

// BroadcastAlert sends a message (with optional image) to ALL active OpenClaw sessions.
// It fetches the current session list via sessions.list RPC, then calls chat.send for each.
// Used by guard mode to notify all Telegram chats/groups about stranger detection.
func (s *Service) BroadcastAlert(msg string, imageBase64 string) error {
	s.wsMu.Lock()
	conn := s.wsConn
	s.wsMu.Unlock()
	if conn == nil {
		return fmt.Errorf("websocket not connected")
	}

	// Fetch all active sessions via pendingRPC dispatch (same pattern as FetchChatHistory).
	listReqID := fmt.Sprintf("guard-list-%d", time.Now().UnixMilli())
	ch := make(chan json.RawMessage, 1)

	s.pendingRPCMu.Lock()
	s.pendingRPC[listReqID] = ch
	s.pendingRPCMu.Unlock()

	listReq := map[string]interface{}{
		"type":   "req",
		"id":     listReqID,
		"method": "sessions.list",
	}
	listBody, err := json.Marshal(listReq)
	if err != nil {
		s.pendingRPCMu.Lock()
		delete(s.pendingRPC, listReqID)
		s.pendingRPCMu.Unlock()
		return fmt.Errorf("marshal sessions.list: %w", err)
	}

	s.wsMu.Lock()
	conn = s.wsConn
	if conn == nil {
		s.wsMu.Unlock()
		s.pendingRPCMu.Lock()
		delete(s.pendingRPC, listReqID)
		s.pendingRPCMu.Unlock()
		return fmt.Errorf("websocket disconnected before send")
	}
	err = conn.WriteMessage(websocket.TextMessage, listBody)
	s.wsMu.Unlock()
	if err != nil {
		s.pendingRPCMu.Lock()
		delete(s.pendingRPC, listReqID)
		s.pendingRPCMu.Unlock()
		return fmt.Errorf("write sessions.list: %w", err)
	}

	// Wait for response via main read loop dispatch.
	timer := time.NewTimer(5 * time.Second)
	defer timer.Stop()
	var listResp json.RawMessage
	select {
	case listResp = <-ch:
	case <-timer.C:
		s.pendingRPCMu.Lock()
		delete(s.pendingRPC, listReqID)
		s.pendingRPCMu.Unlock()
		return fmt.Errorf("sessions.list timeout")
	}

	slog.Info("guard sessions.list raw response", "component", "openclaw", "payload", string(listResp))

	// The payload may be {"sessions":[...]} or the sessions array directly.
	// Try both: first as object with sessions field, then as direct array.
	type deliveryCtx struct {
		Channel   string `json:"channel"`
		To        string `json:"to,omitempty"`
		AccountID string `json:"accountId,omitempty"`
	}
	type sessionEntry struct {
		SessionKey      string       `json:"sessionKey"`
		Key             string       `json:"key"`
		DeliveryContext *deliveryCtx `json:"deliveryContext,omitempty"`
		LastChannel     string       `json:"lastChannel,omitempty"`
		LastTo          string       `json:"lastTo,omitempty"`
		LastAccountID   string       `json:"lastAccountId,omitempty"`
	}
	var listResult struct {
		Sessions []sessionEntry `json:"sessions"`
	}
	if err := json.Unmarshal(listResp, &listResult); err != nil {
		return fmt.Errorf("parse sessions.list: %w", err)
	}

	sessions := listResult.Sessions
	if len(sessions) == 0 {
		// Maybe payload is directly an array
		var arr []sessionEntry
		if json.Unmarshal(listResp, &arr) == nil && len(arr) > 0 {
			sessions = arr
		}
	}

	if len(sessions) == 0 {
		slog.Warn("guard broadcast: no active sessions", "component", "openclaw")
		return nil
	}

	// Normalize: some responses use "key" instead of "sessionKey"
	for i, sess := range sessions {
		if sess.SessionKey == "" && sess.Key != "" {
			sessions[i].SessionKey = sess.Key
		}
	}

	// Skip webchat session — guard alerts only need to go to messaging channels (Telegram, etc.)
	filtered := sessions[:0]
	for _, sess := range sessions {
		ch := sess.LastChannel
		if dc := sess.DeliveryContext; dc != nil && dc.Channel != "" {
			ch = dc.Channel
		}
		if ch != "" && ch != "webchat" {
			filtered = append(filtered, sess)
		}
	}
	sessions = filtered

	if len(sessions) == 0 {
		slog.Info("guard broadcast: no messaging sessions (webchat-only skipped)", "component", "openclaw")
		return nil
	}

	slog.Info("guard broadcast", "component", "openclaw",
		"sessions", len(sessions), "hasImage", imageBase64 != "",
		"message", msg)

	// Send to each session.
	for _, sess := range sessions {
		reqID := fmt.Sprintf("guard-%d", s.reqCounter.Add(1))
		idempotencyKey := fmt.Sprintf("lumi-%s-%d", reqID, time.Now().UnixMilli())

		params := map[string]interface{}{
			"idempotencyKey": idempotencyKey,
			"sessionKey":     sess.SessionKey,
			"message":        msg,
		}

		if imageBase64 != "" {
			params["attachments"] = []map[string]interface{}{
				{
					"type":     "image",
					"mimeType": "image/jpeg",
					"content":  imageBase64,
				},
			}
		}

		req := map[string]interface{}{
			"type":   "req",
			"id":     reqID,
			"method": "chat.send",
			"params": params,
		}
		body, err := json.Marshal(req)
		if err != nil {
			slog.Error("guard broadcast marshal failed", "component", "openclaw", "session", sess.SessionKey, "err", err)
			continue
		}

		s.wsMu.Lock()
		err = conn.WriteMessage(websocket.TextMessage, body)
		s.wsMu.Unlock()
		if err != nil {
			slog.Error("guard broadcast send failed", "component", "openclaw", "session", sess.SessionKey, "err", err)
			continue
		}

		slog.Info("guard broadcast sent", "component", "openclaw",
			"session", sess.SessionKey, "reqId", reqID,
			"channel", params["channel"])
	}

	flow.Log("guard_broadcast", map[string]any{
		"sessions": len(sessions),
		"message":  msg,
	})

	return nil
}

// SendChatMessage sends a user message to the OpenClaw agent via WebSocket chat.send RPC.
// Returns the reqID on success.
func (s *Service) SendChatMessage(message string) (string, error) {
	return s.sendChat(message, "", "", "")
}

// SendChatMessageWithImage sends a message with a base64 JPEG image to the OpenClaw agent.
// The image is included as a vision content block so the LLM can analyze the camera snapshot.
func (s *Service) SendChatMessageWithImage(message string, imageBase64 string) (string, error) {
	return s.sendChat(message, imageBase64, "", "")
}

// NextChatRunID allocates ids for the next chat.send so callers can flow.SetTrace(runID) before flow.Start.
func (s *Service) NextChatRunID() (reqID string, runID string) {
	reqID = fmt.Sprintf("chat-%d", s.reqCounter.Add(1))
	runID = fmt.Sprintf("lumi-%s-%d", reqID, time.Now().UnixMilli())
	return reqID, runID
}

// SendChatMessageWithRun sends using ids from NextChatRunID (must match that pair).
func (s *Service) SendChatMessageWithRun(message string, reqID string, runID string) (string, error) {
	return s.sendChat(message, "", reqID, runID)
}

// SendChatMessageWithImageAndRun sends with image using ids from NextChatRunID.
func (s *Service) SendChatMessageWithImageAndRun(message string, imageBase64 string, reqID string, runID string) (string, error) {
	return s.sendChat(message, imageBase64, reqID, runID)
}

// sendChat is the internal implementation for sending chat messages, optionally with an image.
// If fixedReqID and fixedRunID are both non-empty, they are used (caller already incremented reqCounter via NextChatRunID).
func (s *Service) sendChat(message string, imageBase64 string, fixedReqID string, fixedRunID string) (string, error) {
	s.wsMu.Lock()
	conn := s.wsConn
	s.wsMu.Unlock()
	if conn == nil {
		return "", fmt.Errorf("websocket not connected")
	}

	// reqID labels outbound chat.send from Lumi (sensing POST, wake greeting, etc.) — not "audio only".
	// Idempotency key must stay stable for OpenClaw run_id mapping; use lumi-chat-* (not lumi-sensing-*)
	// so logs are not mistaken for sound/voice-only turns vs Telegram.
	var reqID string
	var idempotencyKey string
	if fixedReqID != "" && fixedRunID != "" {
		reqID = fixedReqID
		idempotencyKey = fixedRunID
	} else {
		reqID = fmt.Sprintf("chat-%d", s.reqCounter.Add(1))
		idempotencyKey = fmt.Sprintf("lumi-%s-%d", reqID, time.Now().UnixMilli())
	}

	params := map[string]interface{}{
		"idempotencyKey": idempotencyKey,
	}
	sessionKey := s.GetSessionKey()
	if sessionKey != "" {
		params["sessionKey"] = sessionKey
	}

	params["message"] = message
	hasImage := imageBase64 != ""
	if hasImage {
		// OpenClaw chat.send accepts attachments[]{content, mimeType} — content is raw base64 string.
		imgLen := len(imageBase64)
		params["attachments"] = []map[string]interface{}{
			{
				"type":     "image",
				"mimeType": "image/jpeg",
				"content":  imageBase64,
			},
		}
		slog.Info("[chat.send] attaching image", "component", "openclaw",
			"reqId", reqID, "runId", idempotencyKey,
			"base64Len", imgLen, "approxKB", imgLen*3/4/1024)
	}

	req := map[string]interface{}{
		"type":   "req",
		"id":     reqID,
		"method": "chat.send",
		"params": params,
	}
	body, err := json.Marshal(req)
	if err != nil {
		return "", fmt.Errorf("marshal chat.send: %w", err)
	}

	// Log full payload (mask image content to avoid log spam)
	slog.Info("[chat.send] full payload", "component", "openclaw", "reqId", reqID, "payload", string(body))
	slog.Info("[chat.send] >>> sending to OpenClaw", "component", "openclaw",
		"reqId", reqID, "runId", idempotencyKey,
		"sessionKey", sessionKey,
		"message", message,
		"hasImage", hasImage,
		"attachments", func() string {
			if !hasImage {
				return "none"
			}
			return fmt.Sprintf("1x image/jpeg ~%dKB", len(imageBase64)*3/4/1024)
		}(),
		"payloadBytes", len(body))

	s.wsMu.Lock()
	conn = s.wsConn
	if conn == nil {
		s.wsMu.Unlock()
		return "", fmt.Errorf("websocket disconnected before send")
	}
	// Set busy before write — closes the timing gap where sensing IsBusy()=false
	// because lifecycle_start SSE hasn't arrived yet. SSE lifecycle_end still clears it.
	s.activeTurn.Store(true)
	err = conn.WriteMessage(websocket.TextMessage, body)
	s.wsMu.Unlock()
	if err != nil {
		s.activeTurn.Store(false) // write failed — no turn will start, clear immediately
		slog.Error("[chat.send] write failed", "component", "openclaw",
			"reqId", reqID, "runId", idempotencyKey, "error", err)
		return "", fmt.Errorf("write chat.send: %w", err)
	}

	slog.Info("[chat.send] <<< sent OK", "component", "openclaw",
		"reqId", reqID, "runId", idempotencyKey, "hasImage", hasImage)
	flow.Log("chat_send", map[string]any{
		"run_id":      idempotencyKey,
		"has_session": sessionKey != "",
		"has_image":   hasImage,
		"image_bytes": len(imageBase64),
		"message":     message,
	}, idempotencyKey)
	slog.Info("flow correlation", "op", "ws_chat_send", "section", "lumi_to_openclaw_ws",
		"device_run_id", idempotencyKey, "req_id", reqID, "has_image", hasImage)

	s.monitorBus.Push(domain.MonitorEvent{
		Type:    "chat_send",
		Summary: message,
		RunID:   idempotencyKey,
	})

	// Return idempotencyKey (not reqID) so trace_id matches OpenClaw's run_id.
	return idempotencyKey, nil
}
