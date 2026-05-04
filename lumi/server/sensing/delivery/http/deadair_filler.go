package http

import (
	"log/slog"
	"math/rand"
	"strings"
	"sync"
	"time"

	"go-lamp.autonomous.ai/lib/lelamp"
)

// Dead air filler — plays a short TTS cue via LeLamp after forwarding a voice
// command to OpenClaw, filling the silence while the LLM processes (~5-15s).
//
// Uses tts_service.speak() (locks mic) which is intentional — user is done
// speaking and waiting for the response.
//
// Disabled when Fillers slice is empty.

// Fillers is the list of short phrases to play as dead air cues.
// Empty slice = feature disabled. Override at init or via config.
var Fillers = []string{
	"Hmm, let me think",
	"Ok, got it",
	"Sure, one moment",
	"Right, let me check",
	"Alright, hold on",
	"Oh, interesting",
	"Ok, let me see",
	"Hmm, let me work on that",
	"One sec",
	"Ah, ok ok",
	"Let me figure this out",
	"Hmm, give me a moment",
	"Oh, right",
	"Let me look into that",
	"Sure, hang on",
	"Ok, thinking",
	"Ah, let me see",
	"Hmm, hold on a sec",
	"Got it, one moment",
	"Oh, let me check that",
}

// PlayDeadAirFiller sends a random filler phrase to LeLamp TTS.
// No-op if Fillers is empty. Safe to call from a goroutine.
//
// Deprecated: kept for legacy callers. New code should drive fillers through
// FillerManager so they can be cancelled when the agent reply arrives.
func PlayDeadAirFiller() {
	if len(Fillers) == 0 {
		return
	}
	filler := Fillers[rand.Intn(len(Fillers))]
	slog.Info("dead air filler", "component", "sensing", "filler", filler)
	if err := lelamp.SpeakInterruptible(filler); err != nil {
		slog.Warn("dead air filler failed", "component", "sensing", "error", err)
		return
	}
	slog.Info("dead air filler sent", "component", "sensing", "filler", filler)
}

// Filler tuning. All durations are wall-clock.
const (
	// FillerDelay is how long to wait after the agent starts (or finishes
	// a non-reactive tool) before speaking a filler. If the assistant
	// reply or a hardware reaction arrives first the timer is cancelled
	// and no filler plays.
	FillerDelay = 1500 * time.Millisecond

	// FillerCooldown is the minimum gap between two filler reactions in
	// the same turn — covers both filler-spoken and hardware-reaction
	// events. Keeps the lamp from chattering "one sec... still working"
	// on top of "/emotion thinking" within a fraction of a second.
	FillerCooldown = 4 * time.Second

	// MaxFillersPerTurn caps actual spoken fillers in a single turn.
	// Hardware reactions don't count against this — only TTS plays.
	// Three is enough to cover a long multi-tool turn without overdoing it.
	MaxFillersPerTurn = 3
)

// fillerCancelToolMarkers are URL fragments for tool calls that themselves
// act as audible/visible reactions — when one fires, no filler is needed
// at that moment because the user already perceived the lamp reacting.
var fillerCancelToolMarkers = []string{"/emotion", "/audio/play", "/scene", "/servo"}

// isHWReactionTool reports whether toolArgs invokes a hardware reaction.
func isHWReactionTool(toolArgs string) bool {
	if toolArgs == "" {
		return false
	}
	for _, m := range fillerCancelToolMarkers {
		if strings.Contains(toolArgs, m) {
			return true
		}
	}
	return false
}

// fillerRun is the per-turn state tracked by FillerManager.
type fillerRun struct {
	timer          *time.Timer
	playing        bool
	fired          int       // count of fillers actually spoken this turn
	lastActivityAt time.Time // last time something audible/visible happened (filler or HW tool)
	ended          bool      // turn finalized (assistant delta or lifecycle.end) — no more arms
}

// FillerManager schedules and cancels dead-air fillers driven by OpenClaw
// agent events. Wiring (per turn lifecycle):
//
//   1. Sensing handler calls MarkVoiceRun(runID) before forwarding a
//      voice/voice_command turn — only marked runs are eligible.
//   2. SSE handler calls OnTurnStart(runID) on lifecycle.start — arms the
//      first FillerDelay timer.
//   3. SSE handler calls OnToolStart(runID, toolArgs) on tool.start —
//      hardware tools (/emotion, /audio/play, /scene, /servo) soft-cancel
//      the pending filler since the agent already reacted; non-hardware
//      tools (Bash, Read, etc.) leave the timer alone.
//   4. SSE handler calls OnToolEnd(runID) on tool.end — re-arms a filler
//      timer if the turn is still active and the cap/cooldown allow it.
//      This covers long multi-tool turns where each tool boundary is a
//      potential dead-air pocket.
//   5. SSE handler calls Cancel(runID) on the first assistant delta and
//      again on lifecycle.end — hard cancel: stops any pending timer,
//      interrupts a filler mid-speech via lelamp.StopTTS(), and clears
//      run state so further events are no-ops.
//
// All exported methods are safe for concurrent use and idempotent.
type FillerManager struct {
	mu        sync.Mutex
	runs      map[string]*fillerRun
	voiceRuns map[string]bool
}

// NewFillerManager constructs an empty FillerManager.
func NewFillerManager() *FillerManager {
	return &FillerManager{
		runs:      make(map[string]*fillerRun),
		voiceRuns: make(map[string]bool),
	}
}

// DefaultFillerManager is the process-wide singleton shared by the sensing
// HTTP handler (MarkVoiceRun) and the OpenClaw SSE event handler
// (OnTurnStart/OnToolStart/OnToolEnd/Cancel).
var DefaultFillerManager = NewFillerManager()

// MarkVoiceRun marks runID as eligible for fillers. Other turn types
// (Telegram, web chat, passive sensing, cron, guard) must NOT be marked.
func (fm *FillerManager) MarkVoiceRun(runID string) {
	if runID == "" {
		return
	}
	fm.mu.Lock()
	fm.voiceRuns[runID] = true
	fm.mu.Unlock()
}

// OnTurnStart arms the first filler timer if MarkVoiceRun was set for
// runID and Fillers is non-empty.
func (fm *FillerManager) OnTurnStart(runID string) {
	if runID == "" || len(Fillers) == 0 {
		return
	}
	fm.mu.Lock()
	defer fm.mu.Unlock()
	if !fm.voiceRuns[runID] {
		return
	}
	delete(fm.voiceRuns, runID)
	if _, exists := fm.runs[runID]; exists {
		return
	}
	run := &fillerRun{}
	fm.runs[runID] = run
	fm.armLocked(runID, run, FillerDelay)
}

// OnToolStart soft-cancels the pending filler when the agent invokes a
// hardware reaction tool. Non-hardware tools are ignored; the filler
// timer keeps ticking and may fire during a long Bash/Read.
func (fm *FillerManager) OnToolStart(runID, toolArgs string) {
	if runID == "" || !isHWReactionTool(toolArgs) {
		return
	}
	fm.mu.Lock()
	defer fm.mu.Unlock()
	run, ok := fm.runs[runID]
	if !ok || run.ended {
		return
	}
	fm.softCancelLocked(run)
}

// OnToolEnd attempts to re-arm a filler timer after a tool finishes —
// the turn may still have minutes of thinking ahead. No-op when the run
// has ended, the per-turn cap is reached, or a filler is already pending
// or playing.
func (fm *FillerManager) OnToolEnd(runID string) {
	if runID == "" || len(Fillers) == 0 {
		return
	}
	fm.mu.Lock()
	defer fm.mu.Unlock()
	run, ok := fm.runs[runID]
	if !ok || run.ended {
		return
	}
	delay := FillerDelay
	if !run.lastActivityAt.IsZero() {
		// Respect cooldown from the last filler/HW reaction. Add the
		// regular delay on top so we don't immediately re-fire the moment
		// cooldown elapses — give the next thought a chance.
		if elapsed := time.Since(run.lastActivityAt); elapsed < FillerCooldown {
			delay = (FillerCooldown - elapsed) + FillerDelay
		}
	}
	fm.armLocked(runID, run, delay)
}

// Cancel hard-cancels the run: stop pending timer, interrupt any filler
// mid-speech, mark the run ended so future tool events are no-ops, and
// drop the entry from the runs map. Idempotent.
func (fm *FillerManager) Cancel(runID string) {
	if runID == "" {
		return
	}
	fm.mu.Lock()
	delete(fm.voiceRuns, runID)
	run, ok := fm.runs[runID]
	if !ok {
		fm.mu.Unlock()
		return
	}
	run.ended = true
	if run.timer != nil {
		run.timer.Stop()
		run.timer = nil
	}
	wasPlaying := run.playing
	run.playing = false
	delete(fm.runs, runID)
	fm.mu.Unlock()

	if wasPlaying {
		go func() {
			if err := lelamp.StopTTS(); err != nil {
				slog.Warn("filler stop TTS failed", "component", "sensing", "run_id", runID, "error", err)
			}
		}()
	}
}

// armLocked schedules a filler timer for run after delay. Caller holds fm.mu.
// No-op when the run has ended, the cap is reached, or a timer/filler is already active.
func (fm *FillerManager) armLocked(runID string, run *fillerRun, delay time.Duration) {
	if run.ended || run.fired >= MaxFillersPerTurn || run.timer != nil || run.playing {
		return
	}
	run.timer = time.AfterFunc(delay, func() { fm.fire(runID) })
}

// softCancelLocked clears a pending timer and interrupts in-flight TTS,
// but keeps the run alive so OnToolEnd can re-arm later. Counts as an
// activity so the cooldown applies to the next re-arm.
func (fm *FillerManager) softCancelLocked(run *fillerRun) {
	if run.timer != nil {
		run.timer.Stop()
		run.timer = nil
	}
	wasPlaying := run.playing
	run.playing = false
	run.lastActivityAt = time.Now()
	if wasPlaying {
		go func() {
			if err := lelamp.StopTTS(); err != nil {
				slog.Warn("filler stop TTS failed (soft cancel)", "component", "sensing", "error", err)
			}
		}()
	}
}

// fire is the timer callback. Re-checks state under the lock, speaks the
// filler outside the lock, then re-takes the lock to update counters.
func (fm *FillerManager) fire(runID string) {
	fm.mu.Lock()
	run, ok := fm.runs[runID]
	if !ok || run.ended || run.timer == nil {
		// Cancel raced ahead between AfterFunc firing and this callback.
		fm.mu.Unlock()
		return
	}
	run.timer = nil
	run.playing = true
	fm.mu.Unlock()

	filler := Fillers[rand.Intn(len(Fillers))]
	slog.Info("dead air filler firing", "component", "sensing", "run_id", runID, "filler", filler)
	err := lelamp.SpeakInterruptible(filler)
	if err != nil {
		slog.Warn("dead air filler failed", "component", "sensing", "run_id", runID, "error", err)
	}

	fm.mu.Lock()
	// Cancel may have run during SpeakInterruptible — in that case the
	// run was deleted; nothing to update.
	if run, ok := fm.runs[runID]; ok && !run.ended {
		run.playing = false
		run.fired++
		run.lastActivityAt = time.Now()
	}
	fm.mu.Unlock()
}
