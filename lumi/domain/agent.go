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

// ChannelSender delivers messages to a specific messaging channel (Telegram, Discord, Slack, etc.).
type ChannelSender interface {
	// Name returns the channel name (e.g. "telegram", "discord", "slack").
	Name() string

	// IsConfigured returns true if this channel has valid credentials/config.
	IsConfigured() bool

	// Send delivers a message with an optional image to all targets in this channel.
	Send(msg string, imagePath string) error
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

	// MarkGuardRun marks a runID as a guard-active turn. When the agent responds,
	// the SSE handler will broadcast the response to all Telegram chats via Bot API.
	MarkGuardRun(runID string, snapshotPath string)

	// ConsumeGuardRun checks if a runID is a guard-active turn and returns the
	// snapshot path. Returns ("", false) if not a guard run.
	ConsumeGuardRun(runID string) (snapshotPath string, ok bool)

	// MarkBroadcastRun marks a runID so the agent's response is broadcast
	// to all messaging channels alongside TTS. Used for music.mood confirmations
	// and other events where the user should be able to respond via voice or channel.
	MarkBroadcastRun(runID string)

	// ConsumeBroadcastRun checks if a runID is marked for broadcast. One-shot.
	ConsumeBroadcastRun(runID string) bool

	// MarkWebChatRun marks a runID as originating from the web monitor chat.
	// TTS is suppressed for these runs — response is displayed in the web UI only.
	MarkWebChatRun(runID string)

	// IsWebChatRun checks if a runID is a web chat run (non-consuming).
	IsWebChatRun(runID string) bool

	// ConsumeWebChatRun checks and removes a web-chat-marked runID. One-shot.
	ConsumeWebChatRun(runID string) bool

	// SetPendingChatTrace stores the idempotencyKey of the most recent chat.send
	// so lifecycle_start can map OpenClaw UUID → device trace without relying on global flow trace.
	SetPendingChatTrace(runID string)

	// ConsumePendingChatTrace returns and clears the pending chat trace. One-shot.
	// Returns "" if no pending chat or expired (>2 min).
	ConsumePendingChatTrace() string

	// --- Channel abstraction (backend-agnostic) ---

	// GetTelegramBotToken returns the Telegram bot token used by the agent runtime.
	GetTelegramBotToken() string

	// GetTelegramTargets returns all Telegram chats (DMs + groups) the bot is connected to.
	GetTelegramTargets() ([]TelegramTarget, error)

	// Broadcast sends a message to all connected messaging channels.
	// Currently supports Telegram via Bot API. imagePath is an optional local image file.
	Broadcast(msg string, imagePath string) error

	// SendToUser sends a direct message to a specific Telegram user by their user ID.
	// If the user ID is empty, the message is silently dropped.
	SendToUser(telegramID string, msg string, imagePath string) error

	// SendToLeLampTTS posts response text to LeLamp for TTS playback.
	SendToLeLampTTS(text string) error

	// StopTTS interrupts active TTS playback and music on LeLamp.
	StopTTS() error

	// SetVolume sets speaker volume on LeLamp (0-100).
	SetVolume(pct int) error

	// StartLeLampVoice starts the voice pipeline on LeLamp.
	StartLeLampVoice(deepgramKey, llmKey, llmBaseURL, ttsVoice string) error

	// WatchIdentity polls IDENTITY.md and pushes updated wake words to LeLamp on rename.
	WatchIdentity(ctx context.Context)

	// GetConfiguredChannel returns the primary messaging channel type configured
	// in the agent runtime (e.g. "telegram", "discord", "slack").
	// Returns "channel" if none can be determined.
	GetConfiguredChannel() string

	// CompactSession sends a sessions.compact RPC to the agent runtime
	// to summarize and reduce conversation history for the given session.
	CompactSession(sessionKey string) error
}
