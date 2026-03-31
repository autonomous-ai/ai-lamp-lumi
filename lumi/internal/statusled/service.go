// Package statusled manages LED feedback states so users can see what Lumi is doing.
// States have priority: error > ota > booting > connectivity > processing > idle.
// When a state clears, the LED is turned off — ambient service will resume breathing.
package statusled

import (
	"log/slog"
	"sync"
	"time"

	"go-lamp.autonomous.ai/lib/lelamp"
)

// State represents a named LED status.
type State string

const (
	StateProcessing  State = "processing"  // Agent is thinking — blue pulse
	StateOTA         State = "ota"         // Firmware updating — orange breathing (used by bootstrap binary)
	StateError       State = "error"       // Something went wrong — red pulse
	StateBooting     State = "booting"     // Starting up — slow blue pulse
	StateConnectivity State = "connectivity" // Poor internet connection — yellow pulse
)

// stateConfig defines the LED effect for each state.
type stateConfig struct {
	Effect string
	R, G, B int
	Speed  float64
}

var configs = map[State]stateConfig{
	StateProcessing:  {Effect: "pulse", R: 80, G: 140, B: 255, Speed: 1.0},
	StateOTA:         {Effect: "breathing", R: 255, G: 140, B: 0, Speed: 0.4},
	StateError:       {Effect: "pulse", R: 255, G: 30, B: 30, Speed: 1.5},
	StateBooting:     {Effect: "pulse", R: 0, G: 80, B: 255, Speed: 0.5},
	StateConnectivity: {Effect: "pulse", R: 255, G: 200, B: 0, Speed: 0.8},
}

// priority determines which state wins when multiple are active.
var priority = map[State]int{
	StateProcessing:  1,
	StateConnectivity: 2,
	StateBooting:     3,
	StateOTA:         4,
	StateError:       5,
}

// Service manages status LED states.
type Service struct {
	mu     sync.Mutex
	active map[State]bool
}

// ProvideService creates a StatusLED service.
func ProvideService() *Service {
	return &Service{
		active: make(map[State]bool),
	}
}

// Set activates a status LED state.
func (s *Service) Set(state State) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.active[state] = true
	s.applyHighest()
	slog.Info("status LED set", "component", "statusled", "state", state)
}

// Clear deactivates a status LED state.
func (s *Service) Clear(state State) {
	s.mu.Lock()
	defer s.mu.Unlock()

	delete(s.active, state)

	if len(s.active) == 0 {
		lelamp.StopEffect()
		slog.Info("status LED cleared", "component", "statusled", "state", state)
		return
	}
	// Another state still active — show it
	s.applyHighest()
	slog.Info("status LED cleared, showing next", "component", "statusled", "cleared", state)
}

// applyHighest applies the LED effect for the highest-priority active state.
// Must be called with s.mu held.
func (s *Service) applyHighest() {
	var best State
	bestPri := 0
	for st := range s.active {
		if p := priority[st]; p > bestPri {
			bestPri = p
			best = st
		}
	}
	if cfg, ok := configs[best]; ok {
		lelamp.SetEffect(cfg.Effect, cfg.R, cfg.G, cfg.B, cfg.Speed)
	}
}

// FlashReady fires a brief white flash to indicate the agent is ready/listening.
// No-ops if a status state is already active (avoids interrupting error/processing indicators).
// After 1s the flash stops and ambient resumes.
func (s *Service) FlashReady() {
	s.mu.Lock()
	if len(s.active) > 0 {
		s.mu.Unlock()
		return
	}
	lelamp.SetEffect("notification_flash", 255, 255, 255, 1.0)
	s.mu.Unlock()
	slog.Info("status LED ready flash", "component", "statusled")
	go func() {
		time.Sleep(time.Second)
		s.mu.Lock()
		defer s.mu.Unlock()
		if len(s.active) == 0 {
			lelamp.StopEffect()
		}
	}()
}
