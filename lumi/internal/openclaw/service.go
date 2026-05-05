package openclaw

import (
	"encoding/json"
	"regexp"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/internal/statusled"
	"go-lamp.autonomous.ai/server/config"
)

const (
	defaultGatewayWSURL = "ws://127.0.0.1:18789"
	customProviderName  = "autonomous"
	defaultGatewayMode  = "local"
	defaultGatewayBind  = "loopback"
	defaultGatewayPort  = 18789
	openclawRuntimeUser = "root"
	defaultModelKey     = "claude-haiku-4-5"
)

// Compile-time check: *Service implements domain.AgentGateway.
var _ domain.AgentGateway = (*Service)(nil)

// reSnapshotPath matches [snapshot: /path/to/file.jpg] markers in sensing messages.
var reSnapshotPath = regexp.MustCompile(`\[snapshot:\s*[^\]]+\]`)

// Service provides setup, reset, restart of openclaw config/gateway and StartWS.
type Service struct {
	config         *config.Config
	monitorBus     *monitor.Bus
	statusLED      *statusled.Service
	wsConnected    atomic.Bool // true when gateway WebSocket is connected and ready to receive messages
	activeTurn     atomic.Bool // true while agent is processing a turn (lifecycle start → end)
	busySince      atomic.Int64 // unix milli when activeTurn was last set to true; used to expire stuck busy state
	wsHasConnected atomic.Bool // true after first successful WS connect (skip reconnect TTS on boot)

	// wsConn is the active WebSocket connection; guarded by wsMu.
	wsConn *websocket.Conn
	wsMu   sync.Mutex
	// lastSessionKey is the most recent session key observed from agent lifecycle events.
	lastSessionKey atomic.Value // string
	// reqCounter is used to generate unique request IDs for outgoing RPC calls.
	reqCounter atomic.Int64

	// pendingRPC tracks in-flight RPC requests waiting for a response.
	pendingRPCMu sync.Mutex
	pendingRPC   map[string]chan json.RawMessage // reqID → response channel

	// pendingEvents buffers sensing events received while agent is busy.
	// All events are kept (no dedup) — motion/presence must not be missed. Drained on SetBusy(false).
	pendingEventsMu sync.Mutex
	pendingEvents   []pendingEvent

	// guardRuns tracks runIDs that are guard-active sensing turns.
	// When the agent responds, the SSE handler broadcasts the response via Telegram Bot API.
	guardRunsMu sync.Mutex
	guardRuns   map[string]string // runID → snapshot path

	// channels is the list of registered messaging channel senders (Telegram, Discord, Slack, etc.).
	channels []domain.ChannelSender

	// broadcastRuns tracks runIDs whose agent response should be broadcast
	// to all messaging channels alongside TTS (e.g. music.mood confirmations).
	broadcastRunsMu sync.Mutex
	broadcastRuns   map[string]bool

	// webChatRuns tracks runIDs originating from the web monitor chat.
	// TTS is suppressed for these runs — response is displayed in the web UI only.
	webChatRunsMu sync.Mutex
	webChatRuns   map[string]bool

	// pendingChatQueue is a FIFO of idempotencyKeys from outbound chat.sends
	// that have not yet been paired with an OpenClaw lifecycle_start. Using a
	// queue (not a single slot) prevents later sends from overwriting earlier
	// ones when chat.send bursts arrive faster than the agent processes them —
	// otherwise lifecycle_start pops the wrong key and every subsequent turn
	// response gets attributed to the wrong runId.
	pendingChatMu    sync.Mutex
	pendingChatQueue []pendingTrace

	// recentOutboundTexts is a small ring buffer of message texts Lumi sent
	// via chat.send (wake greeting, ambient guard, sensing events). Used by
	// the session.message SSE handler to skip echoes — OpenClaw rebroadcasts
	// every chat.send-injected message as session.message role=user, which
	// is indistinguishable from real channel input on shape alone.
	recentOutboundMu    sync.Mutex
	recentOutboundTexts []recentOutbound
}

type recentOutbound struct {
	text string
	ts   int64 // unix ms
}

const recentOutboundWindowMs int64 = 30_000
const recentOutboundMaxEntries = 32

// pendingTrace pairs a chat.send idempotencyKey with its send time.
// Entries live in SetPendingChatTrace / ConsumePendingChatTrace in FIFO order.
type pendingTrace struct {
	runID  string
	sentAt time.Time
}

// ProvideService constructs the openclaw service.
func ProvideService(cfg *config.Config, bus *monitor.Bus, sled *statusled.Service) *Service {
	s := &Service{
		config:        cfg,
		monitorBus:    bus,
		statusLED:     sled,
		pendingRPC:    make(map[string]chan json.RawMessage),
		guardRuns:     make(map[string]string),
		broadcastRuns: make(map[string]bool),
		webChatRuns:   make(map[string]bool),
	}
	// Register channel senders.
	s.channels = []domain.ChannelSender{
		&TelegramSender{svc: s},
	}
	return s
}

// Name returns the display name of this agent gateway.
func (s *Service) Name() string {
	return "OpenClaw"
}

// markOutboundChat records a Lumi-sent chat.send message text so the SSE
// session.message handler can skip its echo. Trims expired + over-cap.
func (s *Service) markOutboundChat(text string) {
	if text == "" {
		return
	}
	now := time.Now().UnixMilli()
	s.recentOutboundMu.Lock()
	defer s.recentOutboundMu.Unlock()
	cutoff := now - recentOutboundWindowMs
	pruned := s.recentOutboundTexts[:0]
	for _, r := range s.recentOutboundTexts {
		if r.ts >= cutoff {
			pruned = append(pruned, r)
		}
	}
	pruned = append(pruned, recentOutbound{text: text, ts: now})
	if len(pruned) > recentOutboundMaxEntries {
		pruned = pruned[len(pruned)-recentOutboundMaxEntries:]
	}
	s.recentOutboundTexts = pruned
}

// IsRecentOutboundChat reports whether Lumi sent this text recently. Match
// is exact on the message string Lumi passes to chat.send (after sensing
// snapshot path stripping — caller needs to compare against the same form).
func (s *Service) IsRecentOutboundChat(text string) bool {
	if text == "" {
		return false
	}
	now := time.Now().UnixMilli()
	cutoff := now - recentOutboundWindowMs
	s.recentOutboundMu.Lock()
	defer s.recentOutboundMu.Unlock()
	for _, r := range s.recentOutboundTexts {
		if r.ts >= cutoff && r.text == text {
			return true
		}
	}
	return false
}

// IsReady returns true when the gateway WebSocket is connected and OpenClaw is ready to receive messages.
func (s *Service) IsReady() bool {
	return s.wsConnected.Load()
}
