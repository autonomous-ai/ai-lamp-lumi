package domain

import "encoding/json"

// WSEvent represents a gateway WebSocket event frame.
type WSEvent struct {
	Type    string          `json:"type"`
	Event   string          `json:"event"`
	Payload json.RawMessage `json:"payload"`
}

// AgentPayload represents an agent lifecycle/stream event from the gateway.
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
	} `json:"data"`
}

// ChatPayload represents a chat stream event from the gateway.
type ChatPayload struct {
	RunID      string `json:"runId"`
	SessionKey string `json:"sessionKey"`
	State      string `json:"state"`   // "partial", "final"
	Message    string `json:"message"` // the response text
	Role       string `json:"role"`    // "assistant", "user"
}
