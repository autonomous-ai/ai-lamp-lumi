package openclaw

import (
	"log/slog"
	"time"

	"go-lamp.autonomous.ai/lib/flow"
)

// SetSessionKey stores the session key for outgoing chat messages.
func (s *Service) SetSessionKey(key string) {
	s.lastSessionKey.Store(key)
	slog.Info("session key stored", "component", "openclaw", "key", key)
	flow.Log("session_key_acquired", map[string]any{"key_len": len(key)})
}

// GetSessionKey returns the last observed session key, or empty string if none.
func (s *Service) GetSessionKey() string {
	v, _ := s.lastSessionKey.Load().(string)
	return v
}

// MarkGuardRun marks a runID as guard-active so the SSE handler broadcasts the response.
func (s *Service) MarkGuardRun(runID string, snapshotPath string) {
	s.guardRunsMu.Lock()
	s.guardRuns[runID] = snapshotPath
	s.guardRunsMu.Unlock()
	slog.Info("guard run marked", "component", "openclaw", "runID", runID, "snapshot", snapshotPath)
}

// ConsumeGuardRun checks and removes a guard-active runID. Returns snapshot path and true if found.
func (s *Service) ConsumeGuardRun(runID string) (string, bool) {
	s.guardRunsMu.Lock()
	snap, ok := s.guardRuns[runID]
	if ok {
		delete(s.guardRuns, runID)
	}
	s.guardRunsMu.Unlock()
	return snap, ok
}

// MarkBroadcastRun marks a runID so the agent's response is broadcast to all channels.
func (s *Service) MarkBroadcastRun(runID string) {
	s.broadcastRunsMu.Lock()
	s.broadcastRuns[runID] = true
	s.broadcastRunsMu.Unlock()
	slog.Info("broadcast run marked", "component", "openclaw", "runID", runID)
}

// ConsumeBroadcastRun checks and removes a broadcast-marked runID. One-shot.
func (s *Service) ConsumeBroadcastRun(runID string) bool {
	s.broadcastRunsMu.Lock()
	ok := s.broadcastRuns[runID]
	if ok {
		delete(s.broadcastRuns, runID)
	}
	s.broadcastRunsMu.Unlock()
	return ok
}

// MarkWebChatRun marks a runID as originating from the web monitor chat.
func (s *Service) MarkWebChatRun(runID string) {
	s.webChatRunsMu.Lock()
	s.webChatRuns[runID] = true
	s.webChatRunsMu.Unlock()
	slog.Info("web chat run marked — TTS will be suppressed", "component", "openclaw", "runID", runID)
}

// IsWebChatRun checks if a runID is a web chat run (non-consuming).
func (s *Service) IsWebChatRun(runID string) bool {
	s.webChatRunsMu.Lock()
	ok := s.webChatRuns[runID]
	s.webChatRunsMu.Unlock()
	return ok
}

// ConsumeWebChatRun checks and removes a web-chat-marked runID. One-shot.
func (s *Service) ConsumeWebChatRun(runID string) bool {
	s.webChatRunsMu.Lock()
	ok := s.webChatRuns[runID]
	if ok {
		delete(s.webChatRuns, runID)
	}
	s.webChatRunsMu.Unlock()
	return ok
}

// pendingChatTTL bounds how long an unclaimed pending trace stays in the queue.
// Longer than any realistic chat.send → lifecycle_start gap; short enough to
// recover automatically if OpenClaw drops a lifecycle event.
const pendingChatTTL = 2 * time.Minute

// SetPendingChatTrace appends an idempotencyKey to the FIFO queue after a
// successful chat.send. Paired one-to-one with lifecycle_start via
// ConsumePendingChatTrace so OpenClaw's UUID maps back to the correct
// device runId even under burst sends on the same session lane.
func (s *Service) SetPendingChatTrace(runID string) {
	s.pendingChatMu.Lock()
	s.pendingChatQueue = append(s.pendingChatQueue, pendingTrace{
		runID:  runID,
		sentAt: time.Now(),
	})
	s.pendingChatMu.Unlock()
}

// ConsumePendingChatTrace pops the head of the pending queue, dropping any
// stale entries (> pendingChatTTL) from the head first. Returns "" when the
// queue is empty.
func (s *Service) ConsumePendingChatTrace() string {
	s.pendingChatMu.Lock()
	defer s.pendingChatMu.Unlock()
	for len(s.pendingChatQueue) > 0 && time.Since(s.pendingChatQueue[0].sentAt) > pendingChatTTL {
		s.pendingChatQueue = s.pendingChatQueue[1:]
	}
	if len(s.pendingChatQueue) == 0 {
		return ""
	}
	head := s.pendingChatQueue[0]
	s.pendingChatQueue = s.pendingChatQueue[1:]
	return head.runID
}

// RemovePendingChatTraceByRunID removes the entry whose runID matches target.
// Used on lifecycle_start when payload.RunID is already a Lumi-format
// idempotencyKey (OpenClaw 5.4 echo path) — the runId IS the device trace,
// no mapping is needed, but the entry must be cleared from the queue so the
// next UUID lifecycle pop targets the correct successor instead of an
// orphan that would shift every subsequent mapping by one.
// Returns true if found+removed, false otherwise. Stale entries (> TTL) are
// pruned from the head opportunistically while scanning.
func (s *Service) RemovePendingChatTraceByRunID(target string) bool {
	if target == "" {
		return false
	}
	s.pendingChatMu.Lock()
	defer s.pendingChatMu.Unlock()
	for len(s.pendingChatQueue) > 0 && time.Since(s.pendingChatQueue[0].sentAt) > pendingChatTTL {
		s.pendingChatQueue = s.pendingChatQueue[1:]
	}
	for i, p := range s.pendingChatQueue {
		if p.runID == target {
			s.pendingChatQueue = append(s.pendingChatQueue[:i], s.pendingChatQueue[i+1:]...)
			return true
		}
	}
	return false
}
