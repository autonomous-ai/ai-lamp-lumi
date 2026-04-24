package sse

import (
	"bufio"
	"bytes"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/server/serializers"
)

const (
	openclawSessionsIndex = "/root/.openclaw/agents/main/sessions/sessions.json"
	defaultMainSessionKey = "agent:main:main"

	// Compaction records embed the full summary text plus read-file lists in one JSONL line.
	// The observed max summary is ~16000 chars; raw line headroom is 4 MiB.
	compactionLineBufMax = 4 * 1024 * 1024
)

type compactionRecord struct {
	Type             string         `json:"type"`
	ID               any            `json:"id"`
	ParentID         any            `json:"parentId"`
	Timestamp        string         `json:"timestamp"`
	Summary          string         `json:"summary"`
	TokensBefore     int            `json:"tokensBefore"`
	Details          map[string]any `json:"details"`
	FromHook         bool           `json:"fromHook"`
	FirstKeptEntryID any            `json:"firstKeptEntryId"`
}

// CompactionLatest returns the most recent compaction summary for an OpenClaw agent session.
// This summary is injected at the top of every subsequent turn's prompt until the next compaction,
// so rules accidentally copied into it can override SKILL.md. Exposing it lets the UI surface what's
// actually driving agent behavior vs what the SKILLs claim.
//
// Query: ?session=<key> (default: agent:main:main).
func (h *OpenClawHandler) CompactionLatest(c *gin.Context) {
	raw, err := os.ReadFile(openclawSessionsIndex)
	if err != nil {
		c.JSON(http.StatusNotFound, serializers.ResponseError("sessions index not found: "+err.Error()))
		return
	}
	var sessions map[string]map[string]any
	if err := json.Unmarshal(raw, &sessions); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError("parse sessions.json: "+err.Error()))
		return
	}
	sessionKey := c.DefaultQuery("session", defaultMainSessionKey)
	entry, ok := sessions[sessionKey]
	if !ok {
		c.JSON(http.StatusNotFound, serializers.ResponseError("session key not found: "+sessionKey))
		return
	}
	sessionFile, _ := entry["sessionFile"].(string)
	if sessionFile == "" {
		sid, _ := entry["sessionId"].(string)
		if sid == "" {
			c.JSON(http.StatusInternalServerError, serializers.ResponseError("session has no sessionFile or sessionId"))
			return
		}
		sessionFile = filepath.Join(filepath.Dir(openclawSessionsIndex), sid+".jsonl")
	}

	latest, err := scanLatestCompaction(sessionFile)
	if err != nil {
		c.JSON(http.StatusNotFound, serializers.ResponseError("session file scan failed: "+err.Error()))
		return
	}
	if latest == nil {
		c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
			"found":       false,
			"sessionKey":  sessionKey,
			"sessionFile": sessionFile,
		}))
		return
	}

	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"found":            true,
		"sessionKey":       sessionKey,
		"sessionFile":      sessionFile,
		"compactionCount":  entry["compactionCount"],
		"id":               latest.ID,
		"parentId":         latest.ParentID,
		"timestamp":        latest.Timestamp,
		"tokensBefore":     latest.TokensBefore,
		"summaryChars":     len(latest.Summary),
		"summary":          latest.Summary,
		"details":          latest.Details,
		"fromHook":         latest.FromHook,
		"firstKeptEntryId": latest.FirstKeptEntryID,
	}))
}

func scanLatestCompaction(path string) (*compactionRecord, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	needle := []byte(`"type":"compaction"`)
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), compactionLineBufMax)

	var latest *compactionRecord
	for scanner.Scan() {
		line := scanner.Bytes()
		if !bytes.Contains(line, needle) {
			continue
		}
		var rec compactionRecord
		if err := json.Unmarshal(line, &rec); err != nil {
			continue
		}
		if rec.Type != "compaction" {
			continue
		}
		cp := rec
		latest = &cp
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return latest, nil
}
