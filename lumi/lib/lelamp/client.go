// Package lelamp provides a lightweight HTTP client for the LeLamp hardware API.
// Both lumi-server and bootstrap-server use this to control the lamp on port 5001.
package lelamp

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const BaseURL = "http://127.0.0.1:5001"

var httpClient = &http.Client{Timeout: 5 * time.Second}

// ─── LED ────────────────────────────────────────────────────────────────────

// SetEffect stops any running effect, then starts a new one.
func SetEffect(effect string, r, g, b int, speed float64) {
	postSilent("/led/effect/stop", "{}")
	body := fmt.Sprintf(`{"effect":"%s","color":[%d,%d,%d],"speed":%.2f}`, effect, r, g, b, speed)
	postSilent("/led/effect", body)
}

// StopEffect stops any running LED effect.
func StopEffect() {
	postSilent("/led/effect/stop", "{}")
}

// ─── Voice / TTS ────────────────────────────────────────────────────────────

// Speak sends text to TTS playback (speaker locks mic during playback).
func Speak(text string) error {
	body, _ := json.Marshal(map[string]string{"text": text})
	return post("/voice/speak", body)
}

// SpeakInterruptible sends text to TTS; playback can be cut short by incoming voice.
func SpeakInterruptible(text string) error {
	body, _ := json.Marshal(map[string]any{"text": text, "interruptible": true})
	return post("/voice/speak", body)
}

// StopTTS interrupts active TTS playback.
func StopTTS() error { return post("/tts/stop", nil) }

// StopAudio stops any audio playback (music, etc.).
func StopAudio() error { return post("/audio/stop", nil) }

// SetVolume sets speaker volume (0-100).
func SetVolume(pct int) error {
	body, _ := json.Marshal(map[string]int{"volume": pct})
	return post("/audio/volume", body)
}

// VoiceStartConfig configures the voice pipeline started by StartVoice.
// Empty TTSInstructions and TTSProvider are omitted from the payload.
type VoiceStartConfig struct {
	DeepgramKey     string
	LLMKey          string
	LLMBaseURL      string
	TTSVoice        string
	TTSInstructions string
	TTSProvider     string
}

// StartVoice starts the voice pipeline with the given config.
func StartVoice(cfg VoiceStartConfig) error {
	payload := map[string]string{
		"deepgram_api_key": cfg.DeepgramKey,
		"llm_api_key":      cfg.LLMKey,
		"llm_base_url":     cfg.LLMBaseURL,
		"tts_voice":        cfg.TTSVoice,
	}
	if cfg.TTSInstructions != "" {
		payload["tts_instructions"] = cfg.TTSInstructions
	}
	if cfg.TTSProvider != "" {
		payload["tts_provider"] = cfg.TTSProvider
	}
	body, _ := json.Marshal(payload)
	return post("/voice/start", body)
}

// SetVoiceConfig updates the voice pipeline config at runtime (e.g. wake words after rename).
func SetVoiceConfig(wakeWords []string) {
	b, err := json.Marshal(map[string]any{"wake_words": wakeWords})
	if err != nil {
		return
	}
	postSilent("/voice/config", string(b))
}

// ─── Emotion ────────────────────────────────────────────────────────────────

// SetEmotion triggers an emotion animation on LeLamp.
func SetEmotion(name string, intensity float64) error {
	body, _ := json.Marshal(map[string]any{"emotion": name, "intensity": intensity})
	return post("/emotion", body)
}

// GetEmotion returns the current emotion reported by LeLamp's /emotion/status.
func GetEmotion() (string, error) {
	resp, err := httpClient.Get(BaseURL + "/emotion/status")
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("GET /emotion/status returned %d", resp.StatusCode)
	}
	var r struct {
		CurrentEmotion string `json:"current_emotion"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return "", fmt.Errorf("decode /emotion/status: %w", err)
	}
	return r.CurrentEmotion, nil
}

// ─── Generic passthrough ────────────────────────────────────────────────────

// PostRaw sends a JSON body to the given path. Use when the path is dynamic
// (e.g. HW markers emitted by the agent or local intent rules). Empty body
// sends nil request body.
func PostRaw(path, body string) error {
	if body == "" {
		return post(path, nil)
	}
	return post(path, []byte(body))
}

// ─── Internals ──────────────────────────────────────────────────────────────

// post sends a JSON body and returns an error on transport failure or non-2xx status.
func post(path string, body []byte) error {
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	resp, err := httpClient.Post(BaseURL+path, "application/json", reader)
	if err != nil {
		return fmt.Errorf("POST %s: %w", path, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("POST %s returned %d", path, resp.StatusCode)
	}
	return nil
}

// postSilent is a fire-and-forget variant for LED calls — hardware may be
// unavailable (e.g. during boot) and callers don't care about the outcome.
func postSilent(path, body string) {
	resp, err := httpClient.Post(BaseURL+path, "application/json", strings.NewReader(body))
	if err != nil {
		return
	}
	resp.Body.Close()
}
