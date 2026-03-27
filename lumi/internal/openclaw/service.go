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

	// wsConn is the active WebSocket connection; guarded by wsMu.
	wsConn *websocket.Conn
	wsMu   sync.Mutex
	// lastSessionKey is the most recent session key observed from agent lifecycle events.
	lastSessionKey atomic.Value // string
	// reqCounter is used to generate unique request IDs for outgoing RPC calls.
	reqCounter atomic.Int64
}

// ProvideService constructs the openclaw service.
func ProvideService(cfg *config.Config, bus *monitor.Bus) *Service {
	return &Service{
		config:     cfg,
		monitorBus: bus,
	}
}

// defaultModels is the hardcoded list of supported models.
var defaultModels = []domain.LLMModel{
	{
		Key:       "claude-opus-4-6",
		Name:      "claude-opus-4-6",
		Reasoning: true,
		Input:     []string{"text"},
		Privacy:   "private",
		Capabilities: &domain.LLMModelCapabilities{
			SupportsReasoning:       true,
			SupportsVision:          false,
			SupportsFunctionCalling: true,
		},
	},
	{
		Key:       "claude-haiku-4-5",
		Name:      "claude-haiku-4-5",
		Reasoning: true,
		Input:     []string{"text"},
		Privacy:   "private",
		Capabilities: &domain.LLMModelCapabilities{
			SupportsReasoning:       true,
			SupportsVision:          false,
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
		metadata := map[string]any{}
		agentModelsMap[m.Key] = metadata
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
	// Disable device identity checks — Lumi connects locally on loopback
	gatewayMap["dangerouslyDisableDeviceAuth"] = true
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
	// To comply with your request, delete the openclaw/agents folder from the repository.
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
		} else {
			slog.Warn("websocket connection closed, reconnecting", "component", "openclaw", "backoff", backoff)
		}
		if !sleepCtx(ctx, backoff) {
			return
		}
	}
}

func (s *Service) runWSConn(ctx context.Context, handler domain.AgentEventHandler) error {
	s.wsConnected.Store(false)
	defer s.wsConnected.Store(false)

	dialer := websocket.Dialer{HandshakeTimeout: 10 * time.Second}
	conn, resp, err := dialer.DialContext(ctx, defaultGatewayWSURL, http.Header{})
	if err != nil {
		if resp != nil {
			return fmt.Errorf("dial %s: %w (status %s)", defaultGatewayWSURL, err, resp.Status)
		}
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
			"caps":   []string{"thinking-events"},
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
	env := os.Environ()
	env = append(env,
		fmt.Sprintf("OPENCLAW_CONFIG_PATH=%s/openclaw.json", s.config.OpenclawConfigDir),
		fmt.Sprintf("OPENCLAW_HOME=%s", s.config.OpenclawConfigDir),
		fmt.Sprintf("OPENCLAW_STATE_DIR=%s", s.config.OpenclawConfigDir),
	)
	cmd := exec.Command("bash", "-c", "openclaw onboard --non-interactive --accept-risk")
	cmd.Env = env
	out, err := cmd.CombinedOutput()
	if err != nil {
		slog.Error("openclaw onboard failed", "component", "openclaw", "error", err, "output", strings.TrimSpace(string(out)))
	}

	// After onboard, update openclaw.json workspace to our custom workspace path and move workspace dir
	configPath := fmt.Sprintf("%s/openclaw.json", s.config.OpenclawConfigDir)
	workspacePath := fmt.Sprintf("%s/workspace", s.config.OpenclawConfigDir)
	defaultWorkspaceDir := fmt.Sprintf("%s/.openclaw/workspace", s.config.OpenclawConfigDir)
	// Update the openclaw.json's agents.defaults.workspace field
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
	// Move the generated workspace directory to our configured workspace path if not already there
	// Only do it if the default workspace exists and custom isn't there yet
	if _, err := os.Stat(defaultWorkspaceDir); err == nil {
		if _, err2 := os.Stat(workspacePath); os.IsNotExist(err2) {
			_ = os.Rename(defaultWorkspaceDir, workspacePath)
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

// signConnectPayload builds and signs the v1 payload for device auth.
// Format: v1|deviceId|clientId|clientMode|role|scopes|signedAtMs|token|nonce
func (di *deviceIdentity) signConnectPayload(token, nonce string, signedAt int64) string {
	payload := fmt.Sprintf("v1|%s|%s|%s|%s|%s|%d|%s|%s",
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
}

// GetSessionKey returns the last observed session key, or empty string if none.
func (s *Service) GetSessionKey() string {
	v, _ := s.lastSessionKey.Load().(string)
	return v
}

// SendChatMessage sends a user message to the OpenClaw agent via WebSocket chat.send RPC.
// Returns the reqID on success.
func (s *Service) SendChatMessage(message string) (string, error) {
	s.wsMu.Lock()
	conn := s.wsConn
	s.wsMu.Unlock()
	if conn == nil {
		return "", fmt.Errorf("websocket not connected")
	}

	reqID := fmt.Sprintf("sensing-%d", s.reqCounter.Add(1))

	params := map[string]interface{}{
		"message": message,
	}
	sessionKey := s.GetSessionKey()
	if sessionKey != "" {
		params["sessionKey"] = sessionKey
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

	s.wsMu.Lock()
	err = s.wsConn.WriteMessage(websocket.TextMessage, body)
	s.wsMu.Unlock()
	if err != nil {
		return "", fmt.Errorf("write chat.send: %w", err)
	}

	slog.Info("chat.send", "component", "openclaw", "session", sessionKey, "msg", message, "id", reqID)

	s.monitorBus.Push(domain.MonitorEvent{
		Type:    "chat_send",
		Summary: message,
		RunID:   reqID,
	})

	return reqID, nil
}
