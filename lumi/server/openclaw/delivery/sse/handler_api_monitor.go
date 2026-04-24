package sse

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/lib/lelamp"
	"go-lamp.autonomous.ai/server/serializers"
)

// StopTTS interrupts active TTS playback on LeLamp.
func (h *OpenClawHandler) StopTTS(c *gin.Context) {
	if err := h.agentGateway.StopTTS(); err != nil {
		slog.Warn("StopTTS failed", "component", "openclaw", "error", err)
		c.JSON(http.StatusBadGateway, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(nil))
}

// SetBusy marks the agent as busy from an external signal (e.g. turn-gate hook firing at
// message:preprocessed before lifecycle_start SSE arrives). Closes the timing gap for
// channel-initiated turns (Telegram, Slack, Discord) that bypass Lumi server entirely.
func (h *OpenClawHandler) SetBusy(c *gin.Context) {
	h.agentGateway.SetBusy(true)
	c.JSON(http.StatusOK, serializers.ResponseSuccess(nil))
}

// Status returns the current agent connection status.
func (h *OpenClawHandler) Status(c *gin.Context) {
	// Get real emotion from LeLamp (source of truth) instead of parsed text
	emotion := h.fetchLeLampEmotion()

	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"name":       h.agentGateway.Name(),
		"connected":  h.agentGateway.IsReady(),
		"sessionKey": h.agentGateway.GetSessionKey() != "",
		"emotion":    emotion,
	}))
}

// fetchLeLampEmotion calls LeLamp /emotion/status to get the current emotion.
// Falls back to lastEmotion if LeLamp is unreachable.
func (h *OpenClawHandler) fetchLeLampEmotion() string {
	emotion, err := lelamp.GetEmotion()
	if err != nil {
		h.lastEmotionMu.Lock()
		defer h.lastEmotionMu.Unlock()
		return h.lastEmotion
	}
	return emotion
}

// Events streams monitor bus events over SSE to connected web UI clients.
func (h *OpenClawHandler) Events(c *gin.Context) {
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no") // disable nginx buffering

	sub, unsub := h.monitorBus.Subscribe()
	defer unsub()

	c.Stream(func(w io.Writer) bool {
		select {
		case evt := <-sub:
			data, _ := json.Marshal(evt)
			c.SSEvent("message", string(data))
			return true
		case <-c.Request.Context().Done():
			return false
		}
	})
}

// ConfigJSON returns the raw openclaw.json contents for the gw-config UI.
func (h *OpenClawHandler) ConfigJSON(c *gin.Context) {
	data, err := h.agentGateway.GetConfigJSON()
	if err != nil {
		c.JSON(http.StatusOK, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(data))
}
