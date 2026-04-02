// Package healthwatch monitors LeLamp component health and auto-recovers
// from ALSA microphone failures that can cause SIGABRT crashes.
//
// Root cause context: When the ALSA mic stream (PaAlsaStreamComponent_Initialize)
// fails continuously, starting a heavy servo animation like happy_wiggle can
// trigger a double fault → SIGABRT in the LeLamp Python process.
// This watcher detects sensing degradation early and restarts the voice
// pipeline before that happens.
package healthwatch

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/lib/lelamp"
	"go-lamp.autonomous.ai/server/config"
)

const (
	pollInterval      = 5 * time.Second
	failThreshold     = 2  // consecutive failures before acting
	restartCooldown   = 30 * time.Second
)

// lelampHealth mirrors the /health response from LeLamp.
type lelampHealth struct {
	Servo   bool `json:"servo"`
	LED     bool `json:"led"`
	Camera  bool `json:"camera"`
	Audio   bool `json:"audio"`
	Sensing bool `json:"sensing"`
	Voice   bool `json:"voice"`
	TTS     bool `json:"tts"`
}

// Service polls LeLamp /health and auto-restarts the voice pipeline
// when ALSA/sensing failures are detected.
type Service struct {
	bus *monitor.Bus
	cfg *config.Config

	httpClient *http.Client
}

// ProvideService constructs a HealthWatchService.
func ProvideService(bus *monitor.Bus, cfg *config.Config) *Service {
	return &Service{
		bus: bus,
		cfg: cfg,
		httpClient: &http.Client{Timeout: 3 * time.Second},
	}
}

// Start begins the health polling loop. Blocks until ctx is cancelled.
func (s *Service) Start(ctx context.Context) {
	slog.Info("starting health watcher", "component", "healthwatch")

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	consecutiveFails := 0
	var lastRestart time.Time

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			h, err := s.fetchHealth()
			if err != nil {
				// LeLamp not reachable yet — not an ALSA issue, skip
				consecutiveFails = 0
				continue
			}

			if h.Sensing {
				// Sensing is healthy
				if consecutiveFails >= failThreshold {
					slog.Info("ALSA/sensing recovered", "component", "healthwatch")
					s.bus.Push(domain.MonitorEvent{
						Type:    "hw_alsa_recover",
						Summary: "ALSA mic stream recovered",
					})
				}
				consecutiveFails = 0
				continue
			}

			// Sensing is degraded
			consecutiveFails++
			slog.Warn("ALSA/sensing degraded",
				"component", "healthwatch",
				"consecutiveFails", consecutiveFails,
				"sensing", h.Sensing,
				"audio", h.Audio,
			)

			if consecutiveFails < failThreshold {
				continue
			}

			// Threshold reached — emit event
			s.bus.Push(domain.MonitorEvent{
				Type:    "hw_alsa_error",
				Summary: fmt.Sprintf("ALSA mic stream failing (%d consecutive)", consecutiveFails),
				Detail: map[string]any{
					"sensing": h.Sensing,
					"audio":   h.Audio,
					"voice":   h.Voice,
				},
			})

			// Restart cooldown to avoid restart storms
			if time.Since(lastRestart) < restartCooldown {
				slog.Debug("skipping voice restart — within cooldown", "component", "healthwatch")
				continue
			}

			s.restartVoice()
			lastRestart = time.Now()
		}
	}
}

// fetchHealth calls LeLamp GET /health and returns the parsed response.
// LeLamp returns the health object directly (FastAPI response_model, not wrapped).
func (s *Service) fetchHealth() (*lelampHealth, error) {
	resp, err := s.httpClient.Get(lelamp.BaseURL + "/health")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var h lelampHealth
	if err := json.NewDecoder(resp.Body).Decode(&h); err != nil {
		return nil, err
	}
	return &h, nil
}

// restartVoice stops the LeLamp voice pipeline and restarts it.
// This clears the stuck ALSA stream state before it can cause a SIGABRT.
//
// LeLamp picks its STT provider at start time:
//   - Deepgram if deepgram_api_key is set
//   - AutonomousSTT (llm_api_key + llm_base_url) as fallback
//
// We always send all three keys so LeLamp can choose.
func (s *Service) restartVoice() {
	slog.Info("restarting LeLamp voice pipeline to recover ALSA", "component", "healthwatch")

	// Stop first — ignore errors (pipeline may already be stopped)
	stopResp, err := s.httpClient.Post(lelamp.BaseURL+"/voice/stop", "application/json", strings.NewReader("{}"))
	if err == nil {
		stopResp.Body.Close()
	}

	time.Sleep(2 * time.Second)

	// Always attempt restart — LeLamp falls back to AutonomousSTT if no Deepgram key
	body, _ := json.Marshal(map[string]string{
		"deepgram_api_key": s.cfg.DeepgramAPIKey,
		"llm_api_key":      s.cfg.LLMAPIKey,
		"llm_base_url":     s.cfg.LLMBaseURL,
	})
	startResp, err := s.httpClient.Post(
		lelamp.BaseURL+"/voice/start",
		"application/json",
		strings.NewReader(string(body)),
	)
	if err != nil {
		slog.Error("voice restart failed", "component", "healthwatch", "error", err)
		s.bus.Push(domain.MonitorEvent{
			Type:    "hw_alsa_restart_failed",
			Summary: "voice pipeline restart failed: " + err.Error(),
		})
		return
	}
	defer startResp.Body.Close()

	slog.Info("LeLamp voice pipeline restarted", "component", "healthwatch")
	s.bus.Push(domain.MonitorEvent{
		Type:    "hw_alsa_restarted",
		Summary: "voice pipeline restarted to clear ALSA failure",
	})
}
