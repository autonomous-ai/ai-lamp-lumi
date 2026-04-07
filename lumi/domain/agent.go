package domain

import (
	"context"
	"encoding/json"
)

// TelegramTarget represents a Telegram chat the bot is connected to.
type TelegramTarget struct {
	ChatID string // e.g. "158406741" (DM) or "-5179782244" (group)
	Type   string // "private", "group", "supergroup", "channel"
}

// AgentEventHandler processes events from an agent gateway connection.
type AgentEventHandler func(ctx context.Context, evt WSEvent) error

// AgentGateway abstracts an agentic runtime (OpenClaw, PicoClaw, etc.).
type AgentGateway interface {
	// Name returns the display name of this agent gateway (e.g. "OpenClaw", "PicoClaw").
	Name() string

	// IsReady returns true when the agent runtime is connected and ready.
	IsReady() bool

	// IsBusy returns true when the agent is currently processing a turn.
	// Passive sensing events should be dropped while busy to avoid interrupting active commands.
	IsBusy() bool

	// SetBusy marks the agent as busy (true on lifecycle start, false on lifecycle end).
	SetBusy(busy bool)

	// QueuePendingEvent buffers a sensing event to replay when the agent becomes idle.
	// Last-write-wins per event type.
	QueuePendingEvent(eventType, msg, image string)

	// SendChatMessage sends a user message to the agent. Returns the run ID.
	SendChatMessage(msg string) (string, error)

	// SendChatMessageWithImage sends a message with a base64 JPEG image attachment.
	// Used by sensing events that include a camera snapshot for AI vision analysis.
	SendChatMessageWithImage(msg string, imageBase64 string) (string, error)

	// NextChatRunID allocates the chat request id and idempotency key for the next outbound chat.send.
	// Call flow.SetTrace(runID) before flow.Start so the sensing_input enter line matches chat_send.
	NextChatRunID() (reqID string, runID string)

	// SendChatMessageWithRun sends using a preallocated pair from NextChatRunID (same idempotency as chat.send).
	SendChatMessageWithRun(msg string, reqID string, runID string) (string, error)

	// SendChatMessageWithImageAndRun is SendChatMessageWithImage with preallocated ids.
	SendChatMessageWithImageAndRun(msg string, imageBase64 string, reqID string, runID string) (string, error)

	// GetSessionKey returns the current agent session key, or empty string.
	GetSessionKey() string

	// SetSessionKey stores the session key for outgoing messages.
	SetSessionKey(key string)

	// SetupAgent configures and starts the agent runtime from setup data.
	SetupAgent(data SetupRequest) error

	// AddChannel adds a messaging channel to the agent runtime.
	AddChannel(data AddChannelRequest) error

	// ResetAgent factory-resets the agent runtime configuration.
	ResetAgent() error

	// RestartAgent restarts the agent runtime process.
	RestartAgent() error

	// RefreshModelsConfig patches the models reasoning fields in openclaw.json
	// based on the current LLMDisableThinking config and restarts the agent.
	RefreshModelsConfig() error

	// EnsureOnboarding seeds personality/identity files into the agent workspace.
	EnsureOnboarding() error

	// FetchChatHistory sends a chat.history RPC and returns the raw messages array.
	// Best-effort: returns nil on error or timeout without failing the caller.
	FetchChatHistory(sessionKey string, limit int) (json.RawMessage, error)

	// GetConfigJSON returns the raw openclaw.json bytes.
	GetConfigJSON() (json.RawMessage, error)

	// StartWS connects to the agent runtime and runs the event read loop.
	StartWS(ctx context.Context, handler AgentEventHandler)

	// BroadcastAlert sends a message (with optional image) to ALL active
	// chat sessions via the agent runtime RPC. Used for manual guard alerts.
	BroadcastAlert(msg string, imageBase64 string) error

	// MarkGuardRun marks a runID as a guard-active turn. When the agent responds,
	// the SSE handler will broadcast the response to all Telegram chats via Bot API.
	MarkGuardRun(runID string, snapshotPath string)

	// ConsumeGuardRun checks if a runID is a guard-active turn and returns the
	// snapshot path. Returns ("", false) if not a guard run.
	ConsumeGuardRun(runID string) (snapshotPath string, ok bool)

	// --- Channel abstraction (backend-agnostic) ---

	// GetTelegramBotToken returns the Telegram bot token used by the agent runtime.
	GetTelegramBotToken() string

	// GetTelegramTargets returns all Telegram chats (DMs + groups) the bot is connected to.
	GetTelegramTargets() ([]TelegramTarget, error)

	// BroadcastTelegram sends a message directly via Telegram Bot API to all
	// connected Telegram chats. snapshotPath is an optional local image file.
	BroadcastTelegram(msg string, snapshotPath string) error

	// SendToLeLampTTS posts response text to LeLamp for TTS playback.
	SendToLeLampTTS(text string) error

	// StartLeLampVoice starts the voice pipeline on LeLamp.
	StartLeLampVoice(deepgramKey, llmKey, llmBaseURL string) error

	// WatchIdentity polls IDENTITY.md and pushes updated wake words to LeLamp on rename.
	WatchIdentity(ctx context.Context)
}
