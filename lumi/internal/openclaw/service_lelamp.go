package openclaw

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"regexp"
	"strings"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/lib/flow"
	"go-lamp.autonomous.ai/lib/lelamp"
)

// StartLeLampVoice starts the voice pipeline on LeLamp with API keys from config.
func (s *Service) StartLeLampVoice(deepgramKey, llmKey, llmBaseURL, ttsVoice, ttsInstructions, ttsProvider string) error {
	if deepgramKey == "" {
		return nil
	}
	url := lelamp.BaseURL + "/voice/start"
	payload := map[string]string{
		"deepgram_api_key": deepgramKey,
		"llm_api_key":      llmKey,
		"llm_base_url":     llmBaseURL,
		"tts_voice":        ttsVoice,
	}
	if ttsInstructions != "" {
		payload["tts_instructions"] = ttsInstructions
	}
	if ttsProvider != "" {
		payload["tts_provider"] = ttsProvider
	}
	body, _ := json.Marshal(payload)
	resp, err := http.Post(url, "application/json", strings.NewReader(string(body)))
	if err != nil {
		return fmt.Errorf("POST /voice/start: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusOK {
		slog.Info("LeLamp voice pipeline started", "component", "openclaw")
		flow.Log("voice_pipeline_start", nil)
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

// SetVolume sets speaker volume on LeLamp (0-100).
func (s *Service) SetVolume(pct int) error {
	body, _ := json.Marshal(map[string]int{"volume": pct})
	resp, err := http.Post(lelamp.BaseURL+"/audio/volume", "application/json", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("POST /audio/volume: %w", err)
	}
	defer resp.Body.Close()
	slog.Info("speaker volume set", "component", "openclaw", "pct", pct)
	return nil
}

// StopTTS interrupts active TTS playback and music on LeLamp immediately,
// freeing the speaker so the voice mic can receive new commands.
func (s *Service) StopTTS() error {
	ttsResp, err := http.Post(lelamp.BaseURL+"/tts/stop", "application/json", nil)
	if err != nil {
		return fmt.Errorf("POST /tts/stop: %w", err)
	}
	defer ttsResp.Body.Close()

	// Also stop any music playing — speaker is shared, mic is locked while either runs.
	musicResp, err := http.Post(lelamp.BaseURL+"/audio/stop", "application/json", nil)
	if err != nil {
		slog.Warn("POST /audio/stop failed", "component", "openclaw", "error", err)
	} else {
		defer musicResp.Body.Close()
	}

	slog.Info("speaker stopped (TTS + music)", "component", "openclaw")
	return nil
}

// SendToLeLampTTS posts response text to LeLamp for TTS playback.
// Text must already be stripped of HW markers by the caller (SSE handler).
func (s *Service) SendToLeLampTTS(text string) error {
	text = stripForTTS(text)
	if text == "" {
		return nil
	}
	url := lelamp.BaseURL + "/voice/speak"
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
