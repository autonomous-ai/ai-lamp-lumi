package http

import (
	"log/slog"
	"math/rand"
	"strings"
	"sync"
	"time"

	"go-lamp.autonomous.ai/internal/intent"
	"go-lamp.autonomous.ai/lib/i18n"
	"go-lamp.autonomous.ai/lib/lelamp"
)

// Dead air filler — short TTS cues spoken by LeLamp while OpenClaw is busy,
// scheduled and cancelled by FillerManager from agent lifecycle/tool events.
//
// Two pools chosen by turn position:
//   - OpeningFillers: first filler of a turn — acknowledges the user
//     just before the agent starts working.
//   - ContinuationFillers: re-arms after tool.end — implies progress
//     ("still working") rather than re-acknowledging.
//
// Pool empty = that position is silent. Both empty = feature disabled.

// OpeningFillers play first in a turn. Tone: short acknowledgement.
// English pool — also the fallback when STTLanguage is empty/unknown.
var OpeningFillers = []string{
	"Hmm, let me think",
	"Ok, got it",
	"Sure, one moment",
	"Right",
	"Got it",
	"Alright",
	"Ok",
	"Sure",
	"One sec",
}

// ContinuationFillers play on re-arm after a tool finishes. Tone: neutral
// "still working" — never claim "almost done" because filler #2 of 3 in a
// long multi-tool turn may still be far from finished, and a wrong promise
// damages trust more than dead air.
// English pool — also the fallback when STTLanguage is empty/unknown.
var ContinuationFillers = []string{
	"Still on it",
	"Still thinking",
	"Let me check",
	"Hmm, processing",
	"Hang on",
	"Bear with me",
	"Still here",
	"One moment",
}

// Vietnamese pools (STTLanguage="vi"). Tone matches EN: short acknowledgements
// for opening, progress beats for continuation.
var OpeningFillersVI = []string{
	"Hmm để xem",
	"Ờ rồi",
	"Vâng một chút",
	"Vâng",
	"Hiểu rồi",
	"Dạ",
	"Ờ",
	"Để xem",
	"Chờ chút",
}

var ContinuationFillersVI = []string{
	"Vẫn đang nghĩ",
	"Để mình xem",
	"Đang xử lý nhé",
	"Đợi chút nhé",
	"Hmm, để xem",
	"Vẫn đây mà",
	"Mình đang làm tiếp",
	"Còn đang nghĩ",
}

// Chinese Simplified pools (STTLanguage="zh-CN").
var OpeningFillersZhCN = []string{
	"嗯，让我想想",
	"好的",
	"稍等一下",
	"好",
	"明白了",
	"嗯",
	"等一下",
	"稍等",
	"好的好的",
}

var ContinuationFillersZhCN = []string{
	"还在想",
	"让我看看",
	"我在处理",
	"稍等一下",
	"嗯，再想想",
	"我还在",
	"再等等",
	"还在弄",
}

// Chinese Traditional pools (STTLanguage="zh-TW").
var OpeningFillersZhTW = []string{
	"嗯，讓我想想",
	"好的",
	"稍等一下",
	"好",
	"明白了",
	"嗯",
	"等一下",
	"稍等",
	"好的好的",
}

var ContinuationFillersZhTW = []string{
	"還在想",
	"讓我看看",
	"我在處理",
	"稍等一下",
	"嗯，再想想",
	"我還在",
	"再等等",
	"還在弄",
}

// poolsForLang returns the (opening, continuation) pools for a BCP-47 STT
// language code. Empty / unknown / "en*" → English. Falls through to English
// when the requested pool is empty so a misconfigured pool stays graceful.
func poolsForLang(lang string) (opening, continuation []string) {
	switch lang {
	case "vi":
		return OpeningFillersVI, ContinuationFillersVI
	case "zh-CN":
		return OpeningFillersZhCN, ContinuationFillersZhCN
	case "zh-TW":
		return OpeningFillersZhTW, ContinuationFillersZhTW
	}
	return OpeningFillers, ContinuationFillers
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
	lastSpoken     string    // text of the most recent filler — used to dedup back-to-back picks
}

// fillersDisabled reports whether both English pools are empty — the kill
// switch. Per-language pools are not considered: emptying English alone
// disables the feature for every language.
func fillersDisabled() bool {
	return len(OpeningFillers) == 0 && len(ContinuationFillers) == 0
}

// pickFiller returns a phrase appropriate for the current turn position
// in the active language (read from i18n.Lang()), avoiding lastSpoken when
// an alternative exists. Fired==0 prefers the Opening pool; subsequent
// fillers prefer Continuation. Each falls back to the other pool when its
// own is empty so a single-pool config still works.
func pickFiller(fired int, lastSpoken string) string {
	opening, continuation := poolsForLang(i18n.Lang())
	primary, fallback := opening, continuation
	if fired > 0 {
		primary, fallback = continuation, opening
	}
	if pick := pickFrom(primary, lastSpoken); pick != "" {
		return pick
	}
	return pickFrom(fallback, lastSpoken)
}

// pickFrom returns a random entry from pool. When the pool has more than
// one entry it avoids returning lastSpoken so the same line doesn't fire
// twice in a row within a turn.
func pickFrom(pool []string, lastSpoken string) string {
	switch len(pool) {
	case 0:
		return ""
	case 1:
		return pool[0]
	}
	pick := pool[rand.Intn(len(pool))]
	if pick == lastSpoken {
		// Re-roll once. With pool size >= 2, two picks bound collision
		// probability tightly enough — no need to loop.
		pick = pool[rand.Intn(len(pool))]
		if pick == lastSpoken {
			// Deterministic fallback: walk to the next index.
			for i, p := range pool {
				if p == lastSpoken {
					pick = pool[(i+1)%len(pool)]
					break
				}
			}
		}
	}
	return pick
}

// PrewarmFillers asks lelamp to render+save WAV for every filler phrase
// in the active STT language (read from i18n.Lang()) so the first runtime
// fire is a cache hit (no ElevenLabs roundtrip). Polls lelamp /health
// until it answers (lumi.service starts before lumi-lelamp.service is
// ready -- without this guard every prerender races and all phrases
// fail with connection refused). Then prerenders serially. Logs failures
// but never panics; cache misses fall back to live speak at fire time.
//
// "vi", "zh-CN", "zh-TW" pick the matching translated pool; anything
// else falls back to English. intent.CacheableReplies is always English
// (intent rules only match English keywords) so it's prewarmed regardless
// of language. Switching language at runtime causes a one-time miss on
// the first filler — acceptable since lumi-lelamp restarts on EditConfig
// anyway.
func PrewarmFillers() {
	lang := i18n.Lang()
	const (
		readyMaxWait  = 120 * time.Second
		readyInterval = 2 * time.Second
		perPhraseRetry = 3
	)
	deadline := time.Now().Add(readyMaxWait)
	ready := false
	for time.Now().Before(deadline) {
		if _, err := lelamp.GetHealth(); err == nil {
			ready = true
			break
		}
		time.Sleep(readyInterval)
	}
	if !ready {
		slog.Warn("filler prewarm aborted: lelamp /health not reachable", "component", "sensing")
		return
	}

	opening, continuation := poolsForLang(lang)
	all := append([]string{}, opening...)
	all = append(all, continuation...)
	all = append(all, intent.CacheableReplies...)
	rendered := 0
	for _, phrase := range all {
		var lastErr error
		for attempt := 1; attempt <= perPhraseRetry; attempt++ {
			if err := lelamp.PrerenderCached(phrase); err != nil {
				lastErr = err
				time.Sleep(time.Duration(attempt) * time.Second)
				continue
			}
			lastErr = nil
			break
		}
		if lastErr != nil {
			slog.Warn("filler prerender failed", "component", "sensing", "phrase", phrase, "error", lastErr)
			continue
		}
		rendered++
		slog.Debug("filler prerendered", "component", "sensing", "phrase", phrase)
	}
	slog.Info("filler cache prewarm complete", "component", "sensing", "lang", lang, "rendered", rendered, "total", len(all))
}

// PlayOpeningFillerNow fires a single Opening-pool filler immediately,
// fire-and-forget, without going through FillerManager. Called by the
// sensing handler right after a voice/voice_command turn is forwarded.
//
// Pool is picked from i18n.Lang() (see poolsForLang). Uses the lelamp WAV
// cache (SpeakCachedInterruptible) so the filler nhả tiếng ~50ms after this
// call instead of 1.5s — fillers were previously fired ~5-10s ahead of the
// real reply just to mask ElevenLabs latency; with cached audio that
// workaround is unnecessary, but the call site stays the same for now.
//
// No-op when the resolved Opening pool is empty.
func PlayOpeningFillerNow() {
	lang := i18n.Lang()
	opening, _ := poolsForLang(lang)
	if len(opening) == 0 {
		return
	}
	filler := pickFrom(opening, "")
	if filler == "" {
		return
	}
	slog.Info("opening filler firing (immediate, cached)", "component", "sensing", "lang", lang, "filler", filler)
	if err := lelamp.SpeakCachedInterruptible(filler); err != nil {
		slog.Warn("opening filler failed", "component", "sensing", "error", err)
	}
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

// NewFillerManager constructs an empty FillerManager. Language is read at
// fire time from lib/i18n, so no config wiring is needed here.
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

// OnTurnStart records the run as active and arms a Continuation timer so
// dead air gets filled even when the agent thinks without invoking any
// tool (no tool.end -> no OnToolEnd re-arm without this). fired=1 marks
// Opening as already played by the sensing handler so pickFiller prefers
// the Continuation pool here.
//
// The arm-on-turn-start path was previously disabled because ElevenLabs
// TTFB > 2s could exceed lelamp speak() lock-timeout=2s; with the WAV
// cache (2026-05-05), cached fillers play in ~50ms so the race is gone.
func (fm *FillerManager) OnTurnStart(runID string) {
	if runID == "" || fillersDisabled() {
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
	run := &fillerRun{fired: 1, lastActivityAt: time.Now()}
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
	if runID == "" || fillersDisabled() {
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

// fire is the timer callback. Re-checks state under the lock, picks a
// pool-appropriate filler, speaks it outside the lock, then re-takes the
// lock to update counters.
func (fm *FillerManager) fire(runID string) {
	fm.mu.Lock()
	run, ok := fm.runs[runID]
	if !ok || run.ended || run.timer == nil {
		// Cancel raced ahead between AfterFunc firing and this callback.
		fm.mu.Unlock()
		return
	}
	filler := pickFiller(run.fired, run.lastSpoken)
	if filler == "" {
		// Both pools empty after live edit. Bail without playing.
		run.timer = nil
		fm.mu.Unlock()
		return
	}
	run.timer = nil
	run.playing = true
	fm.mu.Unlock()

	slog.Info("dead air filler firing", "component", "sensing", "run_id", runID, "filler", filler)
	if err := lelamp.SpeakCachedInterruptible(filler); err != nil {
		slog.Warn("dead air filler failed", "component", "sensing", "run_id", runID, "error", err)
	}

	fm.mu.Lock()
	// Cancel may have run during SpeakInterruptible — in that case the
	// run was deleted; nothing to update.
	if run, ok := fm.runs[runID]; ok && !run.ended {
		run.playing = false
		run.fired++
		run.lastActivityAt = time.Now()
		run.lastSpoken = filler
	}
	fm.mu.Unlock()
}
