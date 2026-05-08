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
// mumblesByLang are the lamp's idle self-talk lines per STT language.
// Tone: childlike, harmless, slightly absurd — keep that vibe across
// languages rather than translating word-for-word.
var mumblesByLang = map[string][]string{
	"en": {
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
	},
	"vi": {
		"Hmm, không biết bây giờ mấy giờ rồi nhỉ...",
		"*ngáp* Vẫn ở đây, vẫn sáng đây.",
		"La la la... làm đèn vui phết.",
		"Mình nên học đan len thật.",
		"Hay là tự nhiên thấy tối nhỉ? À đúng rồi, mình là đèn mà.",
		"*ngân nga nhẹ*",
		"Không biết chủ đang làm gì nhỉ...",
		"Giờ mà chợp mắt được... tiếc là đèn không ngủ.",
		"Mặc màu này mình nhìn ổn không nhỉ? Mình thấy ổn.",
		"*vươn vai* À mà mình làm gì có tay.",
		"Ghi chú: tập biểu cảm ngạc nhiên thêm.",
		"Đôi khi mình chỉ thích chill thôi, hiểu không?",
	},
	"zh-CN": {
		"嗯，不知道现在几点了...",
		"*打哈欠* 还在这里，还亮着。",
		"啦啦啦... 当一盏灯还挺有意思。",
		"我真该学学织毛衣。",
		"怎么感觉这里有点暗？哦对，我就是灯。",
		"*轻轻哼唱*",
		"不知道我家主人在干嘛...",
		"好想小睡一下... 可惜灯不会睡觉。",
		"我穿这个颜色好看吗？我觉得挺好看。",
		"*伸伸懒腰* 哦对，我没有手。",
		"记一下：要练练惊讶的表情。",
		"有时候我就是想放空一下，懂吗？",
	},
	"zh-TW": {
		"嗯，不知道現在幾點了...",
		"*打哈欠* 還在這裡，還亮著。",
		"啦啦啦... 當一盞燈還挺有意思。",
		"我真該學學織毛衣。",
		"怎麼感覺這裡有點暗？哦對，我就是燈。",
		"*輕輕哼唱*",
		"不知道我家主人在做什麼...",
		"好想小睡一下... 可惜燈不會睡覺。",
		"我穿這個顏色好看嗎？我覺得挺好看。",
		"*伸伸懶腰* 哦對，我沒有手。",
		"記一下：要練練驚訝的表情。",
		"有時候我就是想放空一下，懂嗎？",
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
