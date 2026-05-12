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
// "still working" — never claim "almost done" because filler #2 of 6 in a
// long multi-tool turn may still be far from finished, and a wrong promise
// damages trust more than dead air.
// Pool size kept ≥ 12 so MaxFillersPerTurn=6 turns don't repeat heavily
// (pickFrom dedups only against the immediately previous line).
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
	"Working on it",
	"Just a sec",
	"Hmm, working",
	"Still digging",
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
	"Đang làm đây",
	"Chờ chút nha",
	"Để xem tí nữa",
	"Còn xử lý nhé",
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
	"我在搜",
	"再稍候",
	"继续找",
	"搜索中",
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
	"我在搜",
	"再稍候",
	"繼續找",
	"搜尋中",
}

// Tool-specific filler pools. When run.lastToolName matches a key, fire()
// prefers these action-oriented phrases over the generic Continuation pool
// so the spoken filler matches what the agent is actually doing ("Đang tra
// mạng" while web_search runs, "Đang đọc tài liệu" while read runs, etc.).
// Unmapped tool names fall through to ContinuationFillers.
//
// Tool name list sourced from OpenClaw runtime (openclaw-tools, bash-tools,
// pi-tools, memory-core, x-search). Only the high-frequency / user-visible
// tools have entries — others (cron, gateway, sessions_send, …) fall back.
var ToolFillersEN = map[string][]string{
	"web_search":     {"Searching", "Looking it up", "Checking online", "Hunting for info"},
	"x_search":       {"Searching X", "Checking X posts", "Looking on X"},
	"web_fetch":      {"Opening the page", "Fetching content", "Loading the page", "Reading the page"},
	"read":           {"Reading", "Checking the file", "Looking at the doc", "Reading content"},
	"memory_search":  {"Searching memory", "Checking history", "Looking up notes"},
	"memory_get":     {"Reading memory", "Checking notes"},
	"exec":           {"Running it", "Executing", "Processing", "Working through it"},
	"process":        {"Running it", "Processing in background"},
	"image_generate": {"Creating image", "Generating art", "Making something visual"},
	"video_generate": {"Generating video", "Rendering frames", "Making the video"},
	"music_generate": {"Composing music", "Generating audio", "Making the track"},
	"update_plan":    {"Updating the plan", "Adjusting the plan", "Reordering todos"},
	"session_status": {"Checking session", "Looking at status"},
	"apply_patch":    {"Editing the file", "Applying changes"},
	"pdf":            {"Reading PDF", "Scanning the document"},
	"canvas":         {"Drawing", "Sketching it out"},
	"nodes":          {"Calling a skill", "Triggering action"},
	"subagents":      {"Asking a sub-agent", "Delegating"},
	"image":          {"Looking at the image", "Inspecting picture"},
}

var ToolFillersVI = map[string][]string{
	"web_search":     {"Đang tra mạng", "Tra cứu chút", "Lên mạng tìm", "Tìm thông tin"},
	"x_search":       {"Tra trên X", "Xem X chút", "Lục X"},
	"web_fetch":      {"Đang mở trang", "Xem trang web", "Tải trang nhé", "Đọc trang"},
	"read":           {"Đang đọc tài liệu", "Mở file xem", "Đọc nội dung", "Kiểm tra tài liệu"},
	"memory_search":  {"Tra trí nhớ", "Tìm trong ghi chú", "Lục lại ghi nhớ"},
	"memory_get":     {"Đang đọc trí nhớ", "Lấy ghi chú ra"},
	"exec":           {"Đang chạy lệnh", "Xử lý lệnh", "Chạy lệnh nhé", "Thực thi"},
	"process":        {"Đang chạy", "Xử lý ngầm"},
	"image_generate": {"Đang vẽ", "Tạo hình ảnh", "Sáng tác hình"},
	"video_generate": {"Đang dựng video", "Tạo video"},
	"music_generate": {"Đang sáng tác nhạc", "Soạn nhạc"},
	"update_plan":    {"Đang lên kế hoạch", "Cập nhật plan", "Sắp xếp lại"},
	"session_status": {"Kiểm tra trạng thái", "Xem session"},
	"apply_patch":    {"Đang sửa file", "Áp dụng thay đổi"},
	"pdf":            {"Đang đọc PDF", "Xem tài liệu PDF"},
	"canvas":         {"Đang vẽ", "Phác chút"},
	"nodes":          {"Đang gọi skill", "Kích hoạt"},
	"subagents":      {"Gọi sub-agent giúp", "Nhờ phụ tá"},
	"image":          {"Đang xem ảnh", "Ngắm ảnh chút"},
}

var ToolFillersZhCN = map[string][]string{
	"web_search":     {"正在搜索", "查一下", "上网搜", "找信息"},
	"x_search":       {"在搜X", "查X", "看X上的"},
	"web_fetch":      {"打开网页", "拿取内容", "加载页面", "查看页面"},
	"read":           {"在读文件", "查看文档", "读取内容", "看一下文件"},
	"memory_search":  {"在查记忆", "翻一翻笔记", "查历史"},
	"memory_get":     {"在读记忆", "取笔记"},
	"exec":           {"执行中", "运行命令", "在跑命令", "处理中"},
	"process":        {"在跑", "后台处理"},
	"image_generate": {"正在画", "生成图片", "做一张图"},
	"video_generate": {"生成视频", "渲染中"},
	"music_generate": {"作曲中", "生成音乐"},
	"update_plan":    {"更新计划", "调整任务", "排一下"},
	"session_status": {"查会话状态", "看一下状态"},
	"apply_patch":    {"在改文件", "应用修改"},
	"pdf":            {"在读PDF", "扫一遍文档"},
	"canvas":         {"在画", "草图中"},
	"nodes":          {"调用技能", "触发动作"},
	"subagents":      {"请副手帮忙", "派一个子代理"},
	"image":          {"在看图", "观察图片"},
}

var ToolFillersZhTW = map[string][]string{
	"web_search":     {"正在搜尋", "查一下", "上網搜", "找資訊"},
	"x_search":       {"在搜X", "查X", "看X上的"},
	"web_fetch":      {"打開網頁", "讀取內容", "載入頁面", "查看頁面"},
	"read":           {"在讀文件", "查看文檔", "讀取內容", "看一下檔案"},
	"memory_search":  {"在查記憶", "翻一翻筆記", "查歷史"},
	"memory_get":     {"在讀記憶", "取筆記"},
	"exec":           {"執行中", "運行命令", "在跑命令", "處理中"},
	"process":        {"在跑", "背景處理"},
	"image_generate": {"正在畫", "生成圖片", "做一張圖"},
	"video_generate": {"生成影片", "渲染中"},
	"music_generate": {"作曲中", "生成音樂"},
	"update_plan":    {"更新計畫", "調整任務", "排一下"},
	"session_status": {"查會話狀態", "看一下狀態"},
	"apply_patch":    {"在改檔案", "套用修改"},
	"pdf":            {"在讀PDF", "掃一遍文件"},
	"canvas":         {"在畫", "草圖中"},
	"nodes":          {"呼叫技能", "觸發動作"},
	"subagents":      {"請副手幫忙", "派一個子代理"},
	"image":          {"在看圖", "觀察圖片"},
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

// toolPoolForLang returns the tool-specific filler pool for (lang, toolName).
// Returns nil when there's no pool for that combination — caller falls back
// to the regular Continuation pool. Unknown lang → English pool.
func toolPoolForLang(lang, toolName string) []string {
	if toolName == "" {
		return nil
	}
	var pools map[string][]string
	switch lang {
	case "vi":
		pools = ToolFillersVI
	case "zh-CN":
		pools = ToolFillersZhCN
	case "zh-TW":
		pools = ToolFillersZhTW
	default:
		pools = ToolFillersEN
	}
	return pools[toolName]
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
	// Tuned 2026-05-12 from 4s → 2.5s so short ~3s tool gaps still get a
	// filler instead of going silent — cached audio plays in ~1s so a
	// 2.5s cooldown leaves ~1.5s of dead air between fillers, enough to
	// not feel chattery while still covering more gaps.
	FillerCooldown = 2500 * time.Millisecond

	// MaxFillersPerTurn caps actual spoken fillers in a single turn.
	// Hardware reactions don't count against this — only TTS plays.
	// Bumped 2026-05-12 from 3 → 6 to cover multi-tool turns (4+ tool
	// boundaries observed on web_search + web_fetch chains) where every
	// gap should get a filler for best perceived progress UX. With pool
	// sizes ≥ 12 (post-2026-05-12), 5 Continuations + 1 synthetic Opening
	// stays varied enough to avoid feeling robotic.
	MaxFillersPerTurn = 6
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
	rearmPending   bool      // tool.end arrived while playing=true; fire() re-arms after speak (otherwise the event would be silently dropped by armLocked's playing guard)
	lastToolName   string    // name of the most recently started tool — drives tool-aware filler pool ("Đang tra mạng" for web_search, "Đang đọc tài liệu" for read, etc.). Empty when no tool has started yet (e.g. first filler before any tool call)
}

// fillersDisabled reports whether both English pools are empty — the kill
// switch. Per-language pools are not considered: emptying English alone
// disables the feature for every language.
func fillersDisabled() bool {
	return len(OpeningFillers) == 0 && len(ContinuationFillers) == 0
}

// pickFiller returns a phrase appropriate for the current turn position
// in the active language (read from i18n.Lang()), avoiding lastSpoken when
// an alternative exists.
//
// Lookup chain (first non-empty wins):
//  1. Tool-specific pool keyed by lastToolName ("web_search" → "Đang tra mạng")
//  2. Opening pool when fired==0, else Continuation pool
//  3. The opposite (Continuation/Opening) pool as fallback
//
// fired==0 prefers Opening so the very first filler stays an
// acknowledgement; once a tool has fired the tool pool drives accuracy.
func pickFiller(fired int, lastSpoken, lastToolName string) string {
	lang := i18n.Lang()
	if pool := toolPoolForLang(lang, lastToolName); len(pool) > 0 {
		if pick := pickFrom(pool, lastSpoken); pick != "" {
			return pick
		}
	}
	opening, continuation := poolsForLang(lang)
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

// OnToolStart records the most recently started tool name so the next
// filler picks a tool-aware phrase (see ToolFillers*), and soft-cancels
// the pending filler when the tool is a hardware reaction (the user
// already perceives the lamp reacting — no filler needed at that moment).
// Non-hardware tools leave the filler timer ticking so it can still fire
// during a long Bash/Read/web_search.
func (fm *FillerManager) OnToolStart(runID, toolArgs, toolName string) {
	if runID == "" {
		return
	}
	fm.mu.Lock()
	defer fm.mu.Unlock()
	run, ok := fm.runs[runID]
	if !ok || run.ended {
		return
	}
	if toolName != "" {
		run.lastToolName = toolName
	}
	if !isHWReactionTool(toolArgs) {
		return
	}
	fm.softCancelLocked(run)
}

// OnToolEnd attempts to re-arm a filler timer after a tool finishes —
// the turn may still have minutes of thinking ahead. No-op when the run
// has ended or the per-turn cap is reached. When a filler is currently
// speaking, the arm is deferred via run.rearmPending so fire() can
// schedule the next timer once speech completes — without this defer
// the tool.end is silently dropped (armLocked refuses while playing)
// and the next dead-air gap goes unfilled.
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
	if run.playing {
		run.rearmPending = true
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
	filler := pickFiller(run.fired, run.lastSpoken, run.lastToolName)
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
		// Pick up tool.end events that landed during speech (run.playing
		// was true so OnToolEnd deferred them via rearmPending). Use the
		// plain FillerDelay — cooldown is implicit since speech already
		// took ~1s of wall-clock, so total gap to next fire is ~speak +
		// FillerDelay ≈ FillerCooldown.
		if run.rearmPending {
			run.rearmPending = false
			fm.armLocked(runID, run, FillerDelay)
		}
	}
	fm.mu.Unlock()
}
