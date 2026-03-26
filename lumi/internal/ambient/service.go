// Package ambient provides idle "living creature" behaviors for Lumi.
// When no interaction is happening, it drives breathing LED, color drift,
// micro-movements, eye expression changes, and occasional self-talk via TTS.
// All hardware control goes through LeLamp HTTP API (port 5001).
package ambient

import (
	"context"
	"fmt"
	"log"
	"math"
	"math/rand"
	"net/http"
	"strings"
	"sync"
	"time"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
)

const lelampBase = "http://127.0.0.1:5001"

// resumeDelay is how long after the last interaction before ambient resumes.
const resumeDelay = 10 * time.Second

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
	log.Println("[ambient] starting ambient life service")

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

	wg.Add(4)
	go func() { defer wg.Done(); s.breathingLoop(ctx) }()
	go func() { defer wg.Done(); s.colorDriftLoop(ctx) }()
	go func() { defer wg.Done(); s.microMovementLoop(ctx) }()
	go func() { defer wg.Done(); s.mumbleLoop(ctx) }()

	<-ctx.Done()
	wg.Wait()
	log.Println("[ambient] stopped")
}

// Pause stops ambient behaviors (called when real interaction begins).
func (s *Service) Pause() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.paused {
		s.paused = true
		log.Println("[ambient] paused for interaction")
	}
	s.lastInteraction = time.Now()
}

func (s *Service) resume() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.paused {
		s.paused = false
		log.Println("[ambient] resumed idle behaviors")
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

// breathingLoop creates a gentle sine-wave brightness pulsing effect.
// Uses /emotion endpoint with idle emotion at varying intensity.
func (s *Service) breathingLoop(ctx context.Context) {
	ticker := time.NewTicker(200 * time.Millisecond) // 5 FPS for smooth sine
	defer ticker.Stop()

	cycleDuration := 4.0 // seconds per full breath cycle
	start := time.Now()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if s.isPaused() {
				start = time.Now() // reset phase on resume
				continue
			}

			elapsed := time.Since(start).Seconds()
			// Sine wave: 0.25 → 0.65 (gentle, not harsh)
			intensity := 0.45 + 0.20*math.Sin(2*math.Pi*elapsed/cycleDuration)

			// Map to warm idle color with varying brightness
			r := int(float64(180) * intensity)
			g := int(float64(220) * intensity)
			b := int(float64(255) * intensity)

			postLeLamp("/led/solid", fmt.Sprintf(`{"color":[%d,%d,%d]}`, r, g, b))
		}
	}
}

// colorDriftLoop slowly transitions the base color palette every 30-90s.
func (s *Service) colorDriftLoop(ctx context.Context) {
	// Warm, cozy color palettes for idle state
	palettes := [][3]int{
		{180, 220, 255}, // soft blue-white
		{255, 200, 150}, // warm amber
		{200, 255, 200}, // soft green
		{220, 180, 255}, // lavender
		{255, 220, 180}, // golden
		{180, 240, 220}, // mint
		{255, 180, 200}, // soft pink
	}

	currentIdx := 0

	for {
		delay := 30 + rand.Intn(60) // 30-90 seconds
		if !sleepCtx(ctx, time.Duration(delay)*time.Second) {
			return
		}
		if s.isPaused() {
			continue
		}

		currentIdx = (currentIdx + 1) % len(palettes)
		// The breathing loop will pick up the base color from the emotion
		// We change the emotion expression to vary the feel
		expressions := []string{"neutral", "curious", "sleepy", "neutral"}
		expr := expressions[currentIdx%len(expressions)]
		postLeLamp("/emotion", fmt.Sprintf(`{"emotion":"%s","intensity":0.3}`, expr))

		log.Printf("[ambient] color drift → %s", expr)
	}
}

// microMovementLoop plays safe, small servo recordings periodically.
func (s *Service) microMovementLoop(ctx context.Context) {
	// Only use recordings known to be safe (small amplitude)
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
		postLeLamp("/emotion", fmt.Sprintf(`{"emotion":"%s","intensity":0.3}`, recording))
		log.Printf("[ambient] micro-movement → %s", recording)
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
		log.Printf("[ambient] mumble → %s", mumble)

		// Play a small expression with the mumble
		postLeLamp("/emotion", `{"emotion":"curious","intensity":0.4}`)
	}
}

// --- Helpers ---

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
