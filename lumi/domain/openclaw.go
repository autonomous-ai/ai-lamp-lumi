package domain

import "encoding/json"

// WSEvent represents a gateway WebSocket event frame.
type WSEvent struct {
	Type    string          `json:"type"`
	Event   string          `json:"event"`
	Payload json.RawMessage `json:"payload"`
}

// AgentPayload represents an agent lifecycle/stream event from the gateway.
// The Stream field distinguishes: "lifecycle", "tool", "assistant", "thinking".
type AgentPayload struct {
	RunID      string `json:"runId"`
	Stream     string `json:"stream"`
	SessionKey string `json:"sessionKey"`
	Seq        int    `json:"seq"`
	Ts         int64  `json:"ts"`
	Data       struct {
		Phase     string `json:"phase"`
		StartedAt int64  `json:"startedAt,omitempty"`
		EndedAt   int64  `json:"endedAt,omitempty"`
		Error     string `json:"error,omitempty"`
		// Tool stream fields
		Tool          string `json:"tool,omitempty"`
		ToolArgs      string `json:"toolArgs,omitempty"`
		Result        string `json:"result,omitempty"`
		PartialResult string `json:"partialResult,omitempty"`
		// Thinking/assistant stream fields
		Text  string `json:"text,omitempty"`
		Delta string `json:"delta,omitempty"`
		// Token usage (populated on lifecycle "end")
		Usage *TokenUsage `json:"usage,omitempty"`
	} `json:"data"`
}

// TokenUsage captures LLM token consumption from an agent turn.
type TokenUsage struct {
	InputTokens       int `json:"inputTokens,omitempty"`
	OutputTokens      int `json:"outputTokens,omitempty"`
	CacheReadTokens   int `json:"cacheReadTokens,omitempty"`
	CacheWriteTokens  int `json:"cacheWriteTokens,omitempty"`
	TotalTokens       int `json:"totalTokens,omitempty"`
}

// ChatPayload represents a chat stream event from the gateway.
type ChatPayload struct {
	RunID      string          `json:"runId"`
	SessionKey string          `json:"sessionKey"`
	State      string          `json:"state"` // "partial", "final"
	RawMessage json.RawMessage `json:"message"`
	Message    string          `json:"-"` // resolved from RawMessage
	Role       string          `json:"role"` // "assistant", "user"
}

// ResolveChatMessage extracts the text from Message which can be a string or an object with a "text" field.
func (p *ChatPayload) ResolveChatMessage() {
	if len(p.RawMessage) == 0 {
		return
	}
	// Try string first
	var s string
	if json.Unmarshal(p.RawMessage, &s) == nil {
		p.Message = s
		return
	}
	// Try object with text field
	var obj struct {
		Text string `json:"text"`
	}
	if json.Unmarshal(p.RawMessage, &obj) == nil {
		p.Message = obj.Text
	}
}
