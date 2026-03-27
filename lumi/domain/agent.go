package domain

import "context"

// AgentEventHandler processes events from an agent gateway connection.
type AgentEventHandler func(ctx context.Context, evt WSEvent) error

// AgentGateway abstracts an agentic runtime (OpenClaw, PicoClaw, etc.).
type AgentGateway interface {
	// Name returns the display name of this agent gateway (e.g. "OpenClaw", "PicoClaw").
	Name() string

	// IsReady returns true when the agent runtime is connected and ready.
	IsReady() bool

	// SendChatMessage sends a user message to the agent. Returns the run ID.
	SendChatMessage(msg string) (string, error)

	// SendChatMessageWithImage sends a message with a base64 JPEG image attachment.
	// Used by sensing events that include a camera snapshot for AI vision analysis.
	SendChatMessageWithImage(msg string, imageBase64 string) (string, error)

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

	// EnsureOnboarding seeds personality/identity files into the agent workspace.
	EnsureOnboarding() error

	// StartWS connects to the agent runtime and runs the event read loop.
	StartWS(ctx context.Context, handler AgentEventHandler)

	// SendToLeLampTTS posts response text to LeLamp for TTS playback.
	SendToLeLampTTS(text string) error

	// StartLeLampVoice starts the voice pipeline on LeLamp.
	StartLeLampVoice(deepgramKey, llmKey, llmBaseURL string) error
}
