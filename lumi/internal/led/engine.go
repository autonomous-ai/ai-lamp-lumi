package led

import (
	"context"
	"log"
	"sync"
	"time"
)

// Auto-rollback: Error → Working; Working → Idle after no user interaction for IdleAfterInactivityDuration.
const (
	OtherModeDisplayDuration    = 10 * time.Second // Error → Working after 10s
	IdleAfterInactivityDuration = 15 * time.Minute // Working → Idle when no Thinking (interaction) for this long
)

// StateOption configures SetState behavior.
type StateOption func(*stateOpts)

type stateOpts struct {
	transition Transition
	inhibit    bool
}

// WithTransition sets the transition type (default: TransitionCrossfade).
func WithTransition(tr Transition) StateOption {
	return func(o *stateOpts) { o.transition = tr }
}

// WithInhibit blocks future SetState calls until UninhibitSetState.
// Uses instant transition automatically.
func WithInhibit() StateOption {
	return func(o *stateOpts) {
		o.inhibit = true
		o.transition = TransitionInstant
	}
}

// Engine drives the LED ring with per-state animations.
// Error rolls back to Working after 10s; Working rolls back to Idle when no user interaction (Thinking) for IdleAfterInactivityDuration.
type Engine struct {
	driver *Driver

	ctx    context.Context
	cancel context.CancelFunc
	done   chan struct{} // closed when loop exits

	mu                  sync.Mutex
	state               State
	prio                int
	stateSince          time.Time // when we entered current state (for effect phase + rollback)
	inhibit             bool      // when true, SetState is ignored (used during long-press to avoid network monitor overwriting)
	lastInteractionTime time.Time // updated when entering Thinking; used for idle-after-inactivity
	stateToRestore      State     // state to show when internet returns (set on enter, overwritten by held SetState)
	hasStateToRestore   bool

	// Transition fields
	transition         Transition
	transitionDuration time.Duration
	transitionStart    time.Time        // when the transition began
	transitionFrom     [WS2812Num]Color // snapshot of LED colors at moment of transition
	transitioning      bool             // true while a transition is in progress
}

// ProvideEngine builds an engine with the given driver and starts a loop that applies the current state color.
func ProvideEngine(d *Driver) *Engine {
	ctx, cancel := context.WithCancel(context.Background())
	now := time.Now()
	e := &Engine{
		driver:              d,
		ctx:                 ctx,
		cancel:              cancel,
		done:                make(chan struct{}),
		lastInteractionTime: now,
	}
	go e.loop()
	return e
}

// SetState sets the display state. Default transition is crossfade.
// Use WithTransition() to override, WithInhibit() to block future calls.
// When inhibited (e.g. during long-press), SetState is ignored.
// When in WorkingNoInternet, incoming state is held until internet returns.
func (e *Engine) SetState(s State, caller string, opts ...StateOption) {
	o := stateOpts{transition: TransitionCrossfade}
	for _, fn := range opts {
		fn(&o)
	}

	e.mu.Lock()
	if e.inhibit {
		log.Printf("[led] BLOCKED %s → %s (inhibited) caller=%s", e.state, s, caller)
		e.mu.Unlock()
		return
	}

	now := time.Now()
	old := e.state

	// Hold: when in WorkingNoInternet, save incoming state and do not change display.
	if e.state == WorkingNoInternet && s != WorkingNoInternet {
		e.stateToRestore = s
		e.hasStateToRestore = true
		if s == Thinking {
			e.lastInteractionTime = now
		}
		log.Printf("[led] HOLD %s (during workingnointernet, saved for restore) caller=%s", s, caller)
		e.mu.Unlock()
		return
	}

	// Set up transition blending.
	if o.transition != TransitionInstant && e.driver != nil {
		e.transitionFrom = e.driver.colors
		e.transition = o.transition
		e.transitionDuration = DefaultTransitionDuration
		e.transitionStart = now
		e.transitioning = true
	} else if o.inhibit {
		e.transitioning = false // cancel any in-progress transition
	}

	if s == WorkingNoInternet && e.state != WorkingNoInternet {
		e.stateToRestore = e.state
		e.hasStateToRestore = true
	}
	e.state = s
	e.prio = priority(s)
	e.stateSince = now
	if o.inhibit {
		e.inhibit = true
	}
	if s == Thinking {
		e.lastInteractionTime = now
	}
	cur := e.state
	e.mu.Unlock()

	if old != s {
		if o.inhibit {
			log.Printf("[led] %s → %s +INHIBIT caller=%s", old, s, caller)
		} else {
			log.Printf("[led] %s → %s caller=%s", old, s, caller)
		}
	}

	// When transitioning, let the loop handle blending (~33ms).
	// Only write immediately for instant transitions (e.g. inhibit/long-press).
	if e.driver != nil && o.transition == TransitionInstant {
		t := time.Since(now).Seconds()
		e.driver.SetColors(effectRun(cur, t))
	}
}

// UninhibitSetState re-enables SetState. Call when long-press action completes.
func (e *Engine) UninhibitSetState(caller string) {
	e.mu.Lock()
	e.inhibit = false
	e.mu.Unlock()
	log.Printf("[led] INHIBIT off caller=%s", caller)
}

// RestoreFromNoInternet restores the LED state when internet returns.
// Uses stateToRestore (set on enter, overwritten by held SetState during no-internet).
// If no state was saved, sets Working. Bypasses hold logic.
func (e *Engine) RestoreFromNoInternet(setUpCompleted bool, caller string) {
	e.mu.Lock()
	if e.inhibit {
		log.Printf("[led] BLOCKED RestoreFromNoInternet (inhibited) caller=%s", caller)
		e.mu.Unlock()
		return
	}
	old := e.state
	restore := Working
	if !setUpCompleted {
		restore = ConnectionMode
	}
	if e.hasStateToRestore {
		restore = e.stateToRestore
		e.hasStateToRestore = false
	}
	now := time.Now()

	// Crossfade from current colors.
	if e.driver != nil {
		e.transitionFrom = e.driver.colors
		e.transition = TransitionCrossfade
		e.transitionDuration = DefaultTransitionDuration
		e.transitionStart = now
		e.transitioning = true
	}

	e.state = restore
	e.prio = priority(restore)
	e.stateSince = now
	if restore == Thinking {
		e.lastInteractionTime = now
	}
	e.mu.Unlock()

	log.Printf("[led] %s → %s (restore from no-internet) caller=%s", old, restore, caller)
	// Crossfade is set above — let the loop handle blending.
}

// GetState returns the current LED state.
func (e *Engine) GetState() State {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.state
}

// Close stops the loop and closes the driver.
func (e *Engine) Close() {
	e.cancel()
	<-e.done
	if e.driver != nil {
		var off [WS2812Num]Color
		e.driver.SetColors(off)
		time.Sleep(1 * time.Second)
		_ = e.driver.Close()
	}
}

func (e *Engine) loop() {
	ticker := time.NewTicker(33 * time.Millisecond) // ~30 fps for smooth animation
	defer ticker.Stop()
	defer close(e.done)

	for {
		select {
		case <-e.ctx.Done():
			return
		case <-ticker.C:
			e.mu.Lock()
			s := e.state
			stateSince := e.stateSince
			lastInteraction := e.lastInteractionTime
			e.mu.Unlock()

			elapsed := time.Since(stateSince)
			// Auto rollback: Error → Working after 10s; Working → Idle when no interaction for IdleAfterInactivityDuration.
			if s == Error && elapsed >= OtherModeDisplayDuration {
				e.mu.Lock()
				now := time.Now()
				if e.driver != nil {
					e.transitionFrom = e.driver.colors
					e.transition = TransitionCrossfade
					e.transitionDuration = DefaultTransitionDuration
					e.transitionStart = now
					e.transitioning = true
				}
				e.state = Working
				e.prio = priority(Working)
				e.stateSince = now
				s, stateSince = Working, e.stateSince
				e.mu.Unlock()
				log.Printf("[led] error → working (auto-rollback after %s)", elapsed.Round(time.Second))
			} else if s == Working {
				var idleElapsed time.Duration
				if lastInteraction.IsZero() {
					idleElapsed = time.Since(stateSince)
				} else {
					idleElapsed = time.Since(lastInteraction)
				}
				if idleElapsed >= IdleAfterInactivityDuration {
					e.mu.Lock()
					now := time.Now()
					if e.driver != nil {
						e.transitionFrom = e.driver.colors
						e.transition = TransitionCrossfade
						e.transitionDuration = DefaultTransitionDuration
						e.transitionStart = now
						e.transitioning = true
					}
					e.state = Idle
					e.prio = priority(Idle)
					e.stateSince = now
					s, stateSince = Idle, e.stateSince
					e.mu.Unlock()
					log.Printf("[led] working → idle (no interaction for %s)", idleElapsed.Round(time.Second))
				}
			}

			if e.driver != nil {
				t := 0.0
				if !stateSince.IsZero() {
					t = time.Since(stateSince).Seconds()
				}
				target := effectRun(s, t)

				e.mu.Lock()
				tr := e.transition
				trDur := e.transitionDuration
				trStart := e.transitionStart
				trFrom := e.transitionFrom
				isTransitioning := e.transitioning
				e.mu.Unlock()

				if isTransitioning && trDur > 0 {
					elapsed := time.Since(trStart)
					progress := float64(elapsed) / float64(trDur)
					if progress >= 1.0 {
						// Transition complete.
						e.mu.Lock()
						e.transitioning = false
						e.mu.Unlock()
					} else {
						switch tr {
						case TransitionCrossfade:
							target = blendFrames(trFrom, target, progress)
						case TransitionFadeThroughBlack:
							var black [WS2812Num]Color
							if progress < 0.5 {
								// First half: fade from old to black.
								target = blendFrames(trFrom, black, progress*2)
							} else {
								// Second half: fade from black to new.
								target = blendFrames(black, target, (progress-0.5)*2)
							}
						}
					}
				}

				e.driver.SetColors(target)
			}
		}
	}
}
