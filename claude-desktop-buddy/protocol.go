package main

import (
	"encoding/json"
	"fmt"
	"time"
)

// Heartbeat is sent by Claude Desktop every 10s or on state change.
type Heartbeat struct {
	Total      int      `json:"total"`
	Running    int      `json:"running"`
	Waiting    int      `json:"waiting"`
	Msg        string   `json:"msg"`
	Entries    []string `json:"entries"`
	Tokens     int      `json:"tokens"`
	TokensToday int    `json:"tokens_today"`
	Prompt     *Prompt  `json:"prompt"`
}

// Prompt is present in Heartbeat only when permission is required.
type Prompt struct {
	ID   string `json:"id"`
	Tool string `json:"tool"`
	Hint string `json:"hint"`
}

// TimeSync is sent by Desktop on connect.
type TimeSync struct {
	Time [2]int64 `json:"time"`
}

// Command is sent by Desktop for status/name/unpair.
type Command struct {
	Cmd  string `json:"cmd"`
	Name string `json:"name,omitempty"`
}

// PermissionDecision is sent from device to Desktop.
type PermissionDecision struct {
	Cmd      string `json:"cmd"`
	ID       string `json:"id"`
	Decision string `json:"decision"`
}

// Ack is sent from device to Desktop for any received command.
type Ack struct {
	AckCmd string      `json:"ack"`
	OK     bool        `json:"ok"`
	N      int         `json:"n"`
	Data   interface{} `json:"data,omitempty"`
	Error  string      `json:"error,omitempty"`
}

// StatusData is the payload for status ack.
type StatusData struct {
	Name string     `json:"name"`
	Sec  bool       `json:"sec"`
	Bat  BatInfo    `json:"bat"`
	Sys  SysInfo    `json:"sys"`
	Stats StatsInfo `json:"stats"`
}

type BatInfo struct {
	Pct int  `json:"pct"`
	MV  int  `json:"mV"`
	MA  int  `json:"mA"`
	USB bool `json:"usb"`
}

type SysInfo struct {
	Up   int `json:"up"`
	Heap int `json:"heap"`
}

type StatsInfo struct {
	Appr int     `json:"appr"`
	Deny int     `json:"deny"`
	Vel  float64 `json:"vel"`
	Nap  int     `json:"nap"`
	Lvl  int     `json:"lvl"`
}

// ParseMessage tries to parse a JSON line from Desktop.
// Returns one of: *Heartbeat, *TimeSync, *Command, or error.
func ParseMessage(data []byte) (interface{}, error) {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("parse json: %w", err)
	}

	// Command messages have "cmd" field
	if _, ok := raw["cmd"]; ok {
		var cmd Command
		if err := json.Unmarshal(data, &cmd); err != nil {
			return nil, fmt.Errorf("parse command: %w", err)
		}
		return &cmd, nil
	}

	// TimeSync messages have "time" field
	if _, ok := raw["time"]; ok {
		var ts TimeSync
		if err := json.Unmarshal(data, &ts); err != nil {
			return nil, fmt.Errorf("parse timesync: %w", err)
		}
		return &ts, nil
	}

	// Otherwise treat as heartbeat (has total, running, etc.)
	if _, ok := raw["total"]; ok {
		var hb Heartbeat
		if err := json.Unmarshal(data, &hb); err != nil {
			return nil, fmt.Errorf("parse heartbeat: %w", err)
		}
		return &hb, nil
	}

	return nil, fmt.Errorf("unknown message type")
}

// MakePermission creates a permission decision JSON line.
func MakePermission(id, decision string) []byte {
	msg := PermissionDecision{Cmd: "permission", ID: id, Decision: decision}
	data, _ := json.Marshal(msg)
	return append(data, '\n')
}

// MakeAck creates an ack JSON line.
func MakeAck(cmd string, ok bool) []byte {
	ack := Ack{AckCmd: cmd, OK: ok, N: 0}
	data, _ := json.Marshal(ack)
	return append(data, '\n')
}

// MakeStatusAck creates a status ack with device info.
func MakeStatusAck(name string, uptime time.Duration, approvedCount, deniedCount int) []byte {
	ack := Ack{
		AckCmd: "status",
		OK:     true,
		Data: StatusData{
			Name: name,
			Sec:  false, // TODO: set true when BLE link is encrypted
			Bat:  BatInfo{Pct: 100, MV: 5000, MA: 0, USB: true}, // Pi is always on USB
			Sys:  SysInfo{Up: int(uptime.Seconds()), Heap: 0},
			Stats: StatsInfo{
				Appr: approvedCount,
				Deny: deniedCount,
			},
		},
	}
	data, _ := json.Marshal(ack)
	return append(data, '\n')
}
