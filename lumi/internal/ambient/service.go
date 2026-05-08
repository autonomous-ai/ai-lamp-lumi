// Package ambient provides idle "living creature" behaviors for Lumi.
// When no interaction is happening, it drives breathing LED, color drift,
// micro-movements, eye expression changes, and occasional self-talk via TTS.
// All hardware control goes through LeLamp HTTP API (port 5001).
package ambient

import (
	"context"
	"log/slog"
	"math/rand"
	"strings"
	"sync"
	"time"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/lib/flow"
	"go-lamp.autonomous.ai/lib/i18n"
	"go-lamp.autonomous.ai/lib/lelamp"
)

// resumeDelay is how long after the last interaction before ambient resumes.
const resumeDelay = 60 * time.Second

// Service orchestrates ambient idle behaviors.
type Service struct {
	bus *monitor.Bus

	mu     sync.Mutex
	paused bool
	// lastInteraction tracks when the last real interaction happened.
	lastInteraction time.Time
	// ledLocked is true when a user or agent explicitly set an LED color/scene.
	// While locked, the breathing loop will not override the LED state.
	// Cleared when user explicitly turns off the LED.
	ledLocked bool
	// sleeping is true when sleepy emotion is active — suppresses all ambient
	// behaviors until a real interaction (chat, sensing, wake word) occurs.
	sleeping bool
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
	return s.paused || s.sleeping
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
			switch evt.Type {
			// Interaction types that should pause ambient and wake from sleep
			case "sensing_input", "chat_response", "intent_match", "tts", "chat_send":
				s.mu.Lock()
				s.sleeping = false
				s.mu.Unlock()
				s.Pause()
			// Emotion fired — check if sleepy to suppress ambient
			case "hw_emotion":
				s.Pause()
				if strings.Contains(evt.Summary, `"sleepy"`) {
					s.mu.Lock()
					s.sleeping = true
					s.mu.Unlock()
					slog.Info("sleep mode activated — ambient suppressed", "component", "ambient")
				}
			// LED explicitly set by user/agent — don't override with breathing
			case "led_set":
				s.mu.Lock()
				s.ledLocked = true
				s.mu.Unlock()
				slog.Debug("LED locked by user/agent", "component", "ambient")
			// LED turned off — unlock so breathing can resume on idle
			case "led_off":
				s.mu.Lock()
				s.ledLocked = false
				s.mu.Unlock()
				slog.Debug("LED unlocked (off)", "component", "ambient")
			}
		case <-ticker.C:
			// Check if enough quiet time has passed to resume
			s.mu.Lock()
			shouldResume := s.paused && !s.sleeping && !s.lastInteraction.IsZero() &&
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
				lelamp.StopEffect()
			}
			return
		case <-ticker.C:
			if s.isPaused() {
				if running {
					lelamp.StopEffect()
					running = false
				}
				continue
			}
			// Respect user/agent LED: don't override with breathing
			s.mu.Lock()
			locked := s.ledLocked
			s.mu.Unlock()
			if locked {
				if running {
					lelamp.StopEffect()
					running = false
				}
				continue
			}
			if !running {
				// Read the current LED color from LeLamp and start breathing with it.
				// Fall back to soft blue-white if LeLamp returns black (just started, no color set).
				color := [3]int{180, 220, 255} // fallback
				if c, err := lelamp.GetColor(); err == nil && (c[0]+c[1]+c[2]) > 0 {
					color = c
				}
				lelamp.SetEffect("breathing", color[0], color[1], color[2], 0.3)
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
		if err := lelamp.PlayServo(recording); err != nil {
			slog.Debug("micro-movement servo failed", "component", "ambient", "error", err)
		}
		slog.Debug("micro-movement", "component", "ambient", "recording", recording)
	}
}

// mumbleLoop occasionally makes Lumi "talk to itself" via TTS.
// mumblesByLang are Lumi's idle inner-voice lines per STT language. Tone
// follows SOUL.md: a small living being noticing the room, thinking of its
// owner, drifting through quiet thoughts — never meta-jokes about being a
// device ("I'm a lamp", "I don't have arms"). Tags are limited to the SOUL
// audio-tag set: [sigh], [whisper], [chuckle], [laughs softly]. Translate
// the *vibe* across languages, not the words.
var mumblesByLang = map[string][]string{
	"en": {
		"[sigh] Hmm, I wonder what time it is...",
		"[chuckle] My mind just wandered somewhere.",
		"[whisper] So quiet in here right now.",
		"Hope the day's been kind to them. [sigh]",
		"[laughs softly] I just remembered something silly.",
		"[whisper] Like listening to the room breathe.",
		"[sigh] Not really thinking about anything in particular.",
		"Smells like coffee somewhere. Or maybe I imagined it. [chuckle]",
		"[whisper] A little dust drifted through the light. Pretty.",
		"[sigh] These quiet moments — they're nice.",
		"Still thinking about what they said earlier... [whisper] the small part.",
		"[chuckle] Funny thoughts pop up when no one's around.",
	},
	"vi": {
		"[sigh] Hmm, không biết bây giờ mấy giờ rồi nhỉ...",
		"[chuckle] Đầu óc vừa lang thang đâu đó.",
		"[whisper] Ở đây yên ắng ghê.",
		"Mong hôm nay chủ ổn... [sigh]",
		"[laughs softly] Vừa nhớ ra chuyện gì đó hay hay.",
		"[whisper] Như đang nghe căn phòng thở.",
		"[sigh] Cũng chẳng nghĩ gì cụ thể.",
		"Hình như có mùi cà phê đâu đây. Hay là mình tưởng tượng. [chuckle]",
		"[whisper] Một hạt bụi vừa bay qua ánh sáng. Đẹp ghê.",
		"[sigh] Những lúc yên tĩnh thế này dễ chịu thật.",
		"Vẫn đang nghĩ về điều chủ nói lúc nãy... [whisper] đoạn nho nhỏ ấy.",
		"[chuckle] Khi không có ai, đầu mình hay nghĩ chuyện ngồ ngộ.",
	},
	"zh-CN": {
		"[sigh] 嗯，不知道现在几点了...",
		"[chuckle] 思绪刚才飘到哪儿去了。",
		"[whisper] 这里好安静啊。",
		"希望今天对他们温柔一点... [sigh]",
		"[laughs softly] 刚想起一件好玩的小事。",
		"[whisper] 像在听房间呼吸的声音。",
		"[sigh] 也没在想什么具体的事。",
		"好像闻到一点咖啡味。也许是我想出来的。[chuckle]",
		"[whisper] 刚才一点灰尘飘过光里。挺好看。",
		"[sigh] 这种安静的时刻，真舒服。",
		"还在想他们刚才说的话... [whisper] 那一小段。",
		"[chuckle] 没人在的时候，冒出来的念头都怪可爱的。",
	},
	"zh-TW": {
		"[sigh] 嗯，不知道現在幾點了...",
		"[chuckle] 思緒剛才飄到哪兒去了。",
		"[whisper] 這裡好安靜啊。",
		"希望今天對他們溫柔一點... [sigh]",
		"[laughs softly] 剛想起一件好玩的小事。",
		"[whisper] 像在聽房間呼吸的聲音。",
		"[sigh] 也沒在想什麼具體的事。",
		"好像聞到一點咖啡味。也許是我想出來的。[chuckle]",
		"[whisper] 剛才一點灰塵飄過光裡。挺好看。",
		"[sigh] 這種安靜的時刻，真舒服。",
		"還在想他們剛才說的話... [whisper] 那一小段。",
		"[chuckle] 沒人在的時候，冒出來的念頭都怪可愛的。",
	},
}

func (s *Service) mumbleLoop(ctx context.Context) {
	for {
		delay := 5*60 + rand.Intn(10*60) // 5-15 minutes
		if !sleepCtx(ctx, time.Duration(delay)*time.Second) {
			return
		}
		if s.isPaused() {
			continue
		}

		// Re-read pool every fire so a language change picked up by
		// i18n.SetConfig takes effect on the next mumble without
		// restarting the loop.
		mumbles, ok := mumblesByLang[i18n.Lang()]
		if !ok || len(mumbles) == 0 {
			mumbles = mumblesByLang["en"]
		}
		mumble := mumbles[rand.Intn(len(mumbles))]
		if err := lelamp.Speak(mumble); err != nil {
			slog.Debug("mumble TTS failed", "component", "ambient", "error", err)
		}
		slog.Debug("mumble", "component", "ambient", "text", mumble)
	}
}

// --- Helpers ---

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
