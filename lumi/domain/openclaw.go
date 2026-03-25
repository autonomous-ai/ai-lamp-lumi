package domain

import "encoding/json"

// WSEvent represents a gateway WebSocket event frame.
type WSEvent struct {
	Type    string          `json:"type"`
	Event   string          `json:"event"`
	Payload json.RawMessage `json:"payload"`
}

// AgentPayload
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
