package openclaw

import (
	"log/slog"
	"sort"
	"strings"
	"time"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/lib/flow"
	"go-lamp.autonomous.ai/lib/mood"
)

// pendingEvent is a sensing event buffered while the agent was busy.
type pendingEvent struct {
	eventType   string
	msg         string
	image       string
	queuedAt    time.Time
	currentUser string // snapshot at queue time — may differ from replay time
}

// IsBusy returns true while the agent is processing a turn (between lifecycle start and end).
func (s *Service) IsBusy() bool {
	return s.activeTurn.Load()
}

// SetBusy marks the agent as busy or idle. Called by the SSE handler on lifecycle start/end.
// When transitioning to idle, any buffered sensing events are replayed.
func (s *Service) SetBusy(busy bool) {
	s.activeTurn.Store(busy)
	if !busy {
		s.drainPendingEvents()
	}
}

// QueuePendingEvent buffers a sensing event to replay when the agent becomes idle.
// All events are appended — motion/presence must not be missed.
func (s *Service) QueuePendingEvent(eventType, msg, image string) {
	now := time.Now()
	curUser := mood.CurrentUser()
	if curUser == "" {
		curUser = "unknown"
	}
	s.pendingEventsMu.Lock()
	s.pendingEvents = append(s.pendingEvents, pendingEvent{eventType: eventType, msg: msg, image: image, queuedAt: now, currentUser: curUser})
	s.pendingEventsMu.Unlock()
	slog.Info("sensing event queued — agent busy", "component", "sensing", "type", eventType)

	// Surface the queued event in the monitor immediately so the UI doesn't
	// look idle while the agent is busy. The original sensing_input flow
	// entry will fire later at drain time with queued_for_ms attached.
	s.monitorBus.Push(domain.MonitorEvent{
		Type:    "sensing_queued",
		Summary: "[" + eventType + "] " + msg,
		Detail:  map[string]any{"type": eventType, "reason": "agent_busy"},
	})
}

// drainPendingEvents replays all buffered sensing events in order and clears the buffer.
func (s *Service) drainPendingEvents() {
	s.pendingEventsMu.Lock()
	events := s.pendingEvents
	s.pendingEvents = nil
	s.pendingEventsMu.Unlock()

	if len(events) == 0 {
		return
	}

	// Prioritize voice events so user replies are processed before queued sensing events.
	sort.SliceStable(events, func(i, j int) bool {
		iv := events[i].eventType == "voice" || events[i].eventType == "voice_command"
		jv := events[j].eventType == "voice" || events[j].eventType == "voice_command"
		return iv && !jv
	})
	// Expire stale motion/emotion events — they're high-frequency and stale
	// data is worse than no data (e.g. after compaction). Voice and presence
	// events are never expired because they carry user intent or session state.
	const expireAfter = 60 * time.Second
	filtered := events[:0]
	for _, ev := range events {
		if (ev.eventType == "motion.activity" || ev.eventType == "emotion.detected") &&
			time.Since(ev.queuedAt) > expireAfter {
			slog.Info("sensing event expired from queue", "component", "sensing", "type", ev.eventType, "age_s", int(time.Since(ev.queuedAt).Seconds()))
			continue
		}
		filtered = append(filtered, ev)
	}
	events = filtered

	if len(events) == 0 {
		slog.Info("all pending sensing events expired, nothing to drain", "component", "sensing")
		return
	}

	slog.Info("draining pending sensing events", "component", "sensing", "count", len(events))
	for _, ev := range events {
		// Allocate a dedicated run ID so each replayed event gets its own
		// sensing_input flow entry — required for the UI to render the turn.
		reqID, runID := s.NextChatRunID()
		flow.SetTrace(runID)
		startPayload := map[string]any{"type": ev.eventType, "message": ev.msg}
		if !ev.queuedAt.IsZero() {
			startPayload["queued_for_ms"] = time.Since(ev.queuedAt).Milliseconds()
			startPayload["queued_at"] = ev.queuedAt.Unix()
		}
		turnStart := flow.Start("sensing_input", startPayload, runID)

		var msg string
		if ev.eventType == "voice" || ev.eventType == "voice_command" {
			prefix := ""
			if ev.eventType == "voice" {
				prefix = "[ambient] "
			}
			msg = domain.AppendEnrollNudge(prefix + ev.msg)
		} else {
			// motion.activity / emotion.detected use domain-specific prefixes
			// to avoid triggering SOUL.md's "[sensing:*] → load sensing/SKILL.md"
			// rule (those events have dedicated handler skills).
			switch ev.eventType {
			case "motion.activity":
				msg = "[activity] " + ev.msg
			case "emotion.detected":
				msg = "[emotion] " + ev.msg
			default:
				msg = "[sensing:" + ev.eventType + "] " + ev.msg
			}
			// Reply-hygiene rules live inside the respective SKILL.md files.
			switch ev.eventType {
			case "presence.leave", "presence.away":
				msg += "\n[No crons to cancel. NO_REPLY unless worth saying.]"
			case "motion.activity":
				msg += "\n[context: current_user=" + ev.currentUser + "]"
			case "emotion.detected":
				msg += "\n[context: current_user=" + ev.currentUser + "]"
				msg += "\n[REQUIRED — complete ALL steps before replying:]"
				msg += "\n[Step 1: user-emotion-detection/SKILL.md — log mood signal + decision]"
				msg += "\n[Step 2: music-suggestion/SKILL.md — run AFTER mood decision is logged]"
			}
		}
		// Strip [snapshot: ...] markers from the outgoing LLM message — matches the
		// behaviour of the direct PostEvent path (sensing handler). The full text with
		// snapshot paths still reaches the sensing_input JSONL via startPayload above,
		// so Monitor UI thumbnails keep working.
		msg = reSnapshotPath.ReplaceAllString(msg, "")
		msg = strings.ReplaceAll(msg, "\n\n\n", "\n\n")
		msg = strings.TrimSpace(msg)

		var err error
		if ev.image != "" {
			_, err = s.SendChatMessageWithImageAndRun(msg, ev.image, reqID, runID)
		} else {
			_, err = s.SendChatMessageWithRun(msg, reqID, runID)
		}
		if err != nil {
			slog.Error("failed to replay pending event", "component", "sensing", "type", ev.eventType, "error", err)
			flow.End("sensing_input", turnStart, map[string]any{"error": err.Error()}, runID)
		} else {
			flow.End("sensing_input", turnStart, map[string]any{"path": "agent", "run_id": runID}, runID)
			flow.Log("agent_call", map[string]any{"type": ev.eventType, "run_id": runID}, runID)
			slog.Info("pending event replayed", "component", "sensing", "type", ev.eventType, "runId", runID)
		}
	}
}
