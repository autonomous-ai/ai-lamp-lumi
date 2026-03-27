// Package ambient provides idle "living creature" behaviors for Lumi.
// When no interaction is happening, it drives breathing LED, color drift,
// micro-movements, eye expression changes, and occasional self-talk via TTS.
// All hardware control goes through LeLamp HTTP API (port 5001).
package ambient

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"math/rand"
	"net/http"
	"strings"
	"sync"
	"time"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/lib/flow"
)

const lelampBase = "http://127.0.0.1:5001"

// resumeDelay is how long after the last interaction before ambient resumes.
const resumeDelay = 60 * time.Second

// Service orchestrates ambient idle behaviors.
type Service struct {
	bus *monitor.Bus

	mu     sync.Mutex
	paused bool
	// lastInteraction tracks when the last real interaction happened.
	lastInteraction time.Time
}

// ProvideService constructs an AmbientLifeService.
func ProvideService(bus *monitor.Bus) *Service {
	return &Service{
		bus:    bus,
		paused: true, // start paused until explicitly started
	}
}

// Start begins the ambient behavior loop. Blocks until ctx is cancelled.
func (s *Service) Start(ctx context.Context) {
	slog.Info("starting ambient life service", "component", "ambient")

	// Subscribe to monitor bus to detect real interactions
	eventCh, unsub := s.bus.Subscribe()
	defer unsub()

	// Watch for interactions in a separate goroutine
	go s.watchInteractions(ctx, eventCh)

	// Initial resume after startup delay
	time.Sleep(5 * time.Second)
	s.resume()

	// Run behavior loops concurrently
	var wg sync.WaitGroup

	wg.Add(3)
	go func() { defer wg.Done(); s.breathingLoop(ctx) }()
	go func() { defer wg.Done(); s.microMovementLoop(ctx) }()
	go func() { defer wg.Done(); s.mumbleLoop(ctx) }()

	<-ctx.Done()
	wg.Wait()
	slog.Info("stopped", "component", "ambient")
}

// Pause stops ambient behaviors (called when real interaction begins).
func (s *Service) Pause() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.paused {
		s.paused = true
		// Stop any running LeLamp breathing effect so the agent's LED changes are visible
		stopLeLampEffect()
		flow.Log("ambient_pause", nil)
	}
	s.lastInteraction = time.Now()
}

func (s *Service) resume() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.paused {
		s.paused = false
		flow.Log("ambient_resume", nil)
	}
}

func (s *Service) isPaused() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.paused
}

// watchInteractions monitors the event bus and pauses/resumes accordingly.
func (s *Service) watchInteractions(ctx context.Context, eventCh <-chan domain.MonitorEvent) {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case evt := <-eventCh:
			// Interaction types that should pause ambient
			switch evt.Type {
			case "sensing_input", "chat_response", "intent_match", "tts", "chat_send":
				s.Pause()
			}
		case <-ticker.C:
			// Check if enough quiet time has passed to resume
			s.mu.Lock()
			shouldResume := s.paused && !s.lastInteraction.IsZero() &&
				time.Since(s.lastInteraction) > resumeDelay
			s.mu.Unlock()
			if shouldResume {
				s.resume()
			}
		}
	}
}

// --- Behavior Loops ---

// breathingLoop delegates the breathing LED effect to LeLamp's built-in
// /led/effect endpoint instead of overriding /led/solid at 5 FPS.
// This way the agent's emotion/scene colors are never trampled by ambient.
func (s *Service) breathingLoop(ctx context.Context) {
	// Track whether we already started the LeLamp breathing effect
	running := false

	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			if running {
				stopLeLampEffect()
			}
			return
		case <-ticker.C:
			if s.isPaused() {
				if running {
					stopLeLampEffect()
					running = false
				}
				continue
			}
			if !running {
				// Read the current LED color from LeLamp and start breathing with it
				color := [3]int{180, 220, 255} // fallback
				if c, err := fetchLeLampColor(); err == nil {
					color = c
				}
				startLeLampBreathing(color)
				running = true
			}
		}
	}
}

// microMovementLoop plays safe, small servo recordings periodically.
// Only triggers servo — does NOT change LED color.
func (s *Service) microMovementLoop(ctx context.Context) {
	safeRecordings := []string{"idle", "curious", "nod"}

	for {
		delay := 45 + rand.Intn(75) // 45-120 seconds
		if !sleepCtx(ctx, time.Duration(delay)*time.Second) {
			return
		}
		if s.isPaused() {
			continue
		}

		recording := safeRecordings[rand.Intn(len(safeRecordings))]
		postLeLamp("/servo/play", fmt.Sprintf(`{"name":"%s"}`, recording))
		slog.Debug("micro-movement", "component", "ambient", "recording", recording)
	}
}

// mumbleLoop occasionally makes Lumi "talk to itself" via TTS.
func (s *Service) mumbleLoop(ctx context.Context) {
	mumbles := []string{
		"Hmm, I wonder what time it is...",
		"*yawns* Still here, still glowing.",
		"La la la... being a lamp is fun.",
		"I should really learn to knit.",
		"Is it just me or is it dark in here? Oh wait, I'm the light.",
		"*hums softly*",
		"Wonder what my human is up to...",
		"I could go for a nap... if lamps could nap.",
		"Do I look good in this color? I think I do.",
		"*stretches* Oh right, I don't have arms.",
		"Note to self: practice my surprised face.",
		"Sometimes I just like to vibe, you know?",
	}

	for {
		delay := 5*60 + rand.Intn(10*60) // 5-15 minutes
		if !sleepCtx(ctx, time.Duration(delay)*time.Second) {
			return
		}
		if s.isPaused() {
			continue
		}

		mumble := mumbles[rand.Intn(len(mumbles))]
		postLeLamp("/voice/speak", fmt.Sprintf(`{"text":"%s"}`, mumble))
		slog.Debug("mumble", "component", "ambient", "text", mumble)
	}
}

// --- Helpers ---

// fetchLeLampColor reads the current LED color from LeLamp.
func fetchLeLampColor() ([3]int, error) {
	resp, err := http.Get(lelampBase + "/led/color")
	if err != nil {
		return [3]int{}, err
	}
	defer resp.Body.Close()
	var result struct {
		Color [3]int `json:"color"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return [3]int{}, err
	}
	return result.Color, nil
}

// startLeLampBreathing starts the built-in breathing effect on LeLamp with the given color.
func startLeLampBreathing(color [3]int) {
	body := fmt.Sprintf(`{"effect":"breathing","color":[%d,%d,%d],"speed":0.3}`, color[0], color[1], color[2])
	postLeLamp("/led/effect", body)
}

// stopLeLampEffect stops any running LED effect on LeLamp.
func stopLeLampEffect() {
	resp, err := http.Post(lelampBase+"/led/effect/stop", "application/json", strings.NewReader("{}"))
	if err != nil {
		return
	}
	resp.Body.Close()
}

// postLeLamp sends a fire-and-forget POST to LeLamp API.
func postLeLamp(path, body string) {
	url := lelampBase + path
	resp, err := http.Post(url, "application/json", strings.NewReader(body))
	if err != nil {
		return // silent fail — hardware may not be available
	}
	resp.Body.Close()
}

// sleepCtx sleeps for the given duration but returns early if ctx is cancelled.
// Returns false if ctx was cancelled.
func sleepCtx(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}
