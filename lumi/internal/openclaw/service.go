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

	// outboundEchoQueue tracks the timestamps of recent Lumi chat.send calls.
	// OpenClaw rebroadcasts the user-role message back to all session
	// subscribers as a session.message event, so without this queue the SSE
	// handler treats Lumi's own outbound (web chat / sensing) as a phantom
	// inbound channel turn on the shared `agent:main:main` session. The
	// session.message handler consumes one entry per matching arrival.
	outboundEchoMu    sync.Mutex
	outboundEchoQueue []time.Time
}

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

// IsReady returns true when the gateway WebSocket is connected and OpenClaw is ready to receive messages.
func (s *Service) IsReady() bool {
	return s.wsConnected.Load()
}
