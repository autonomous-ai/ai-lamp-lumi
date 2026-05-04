package sse

import (
	"strings"
	"time"
)

// accumulateAssistantDelta appends a delta to the buffer for the given runId.
func (h *OpenClawHandler) accumulateAssistantDelta(runID, delta string) {
	if delta == "" {
		return
	}
	h.assistantMu.Lock()
	defer h.assistantMu.Unlock()
	buf, ok := h.assistantBuf[runID]
	if !ok {
		buf = &strings.Builder{}
		h.assistantBuf[runID] = buf
	}
	buf.WriteString(delta)
}

// flushAssistantText returns the accumulated text for runId and clears the buffer.
// HW markers are stripped here so they never appear in Telegram or other channel replies.
// The caller is responsible for extracting and firing HW calls before flushing.
func (h *OpenClawHandler) flushAssistantText(runID string) (string, []hwCall) {
	h.assistantMu.Lock()
	defer h.assistantMu.Unlock()
	buf, ok := h.assistantBuf[runID]
	if !ok || buf.Len() == 0 {
		return "", nil
	}
	raw := buf.String()
	raw = prunedImageMarkerRe.ReplaceAllString(raw, "")
	calls, text := extractHWCalls(raw)
	text = strings.TrimSpace(text)
	delete(h.assistantBuf, runID)
	return text, calls
}

// suppressTTS flags a runID to skip TTS on lifecycle end with the given reason.
func (h *OpenClawHandler) suppressTTS(runID, reason string) {
	h.ttsSuppressMu.Lock()
	defer h.ttsSuppressMu.Unlock()
	// "music_playing" takes priority over "already_spoken" (speaker conflict is more important).
	if existing := h.ttsSuppressReasons[runID]; existing == "music_playing" && reason != "music_playing" {
		return
	}
	h.ttsSuppressReasons[runID] = reason
}

// clearTTSSuppress removes the suppress flag for a runID and returns the reason (empty if none).
func (h *OpenClawHandler) clearTTSSuppress(runID string) string {
	h.ttsSuppressMu.Lock()
	defer h.ttsSuppressMu.Unlock()
	reason := h.ttsSuppressReasons[runID]
	delete(h.ttsSuppressReasons, runID)
	return reason
}

// seenMessageTTL is the dedup window for OpenClaw session.message broadcasts.
// Long enough to span run-absorption (queued chat.send re-broadcast when an
// in-flight embedded run picks it up), short enough that the map stays small.
const seenMessageTTL = 2 * time.Minute

// shouldDedupeMessageID reports whether messageId has been seen recently. It
// also records the current observation, evicting stale entries lazily so the
// map can't grow unbounded.
func (h *OpenClawHandler) shouldDedupeMessageID(messageID string) bool {
	if messageID == "" {
		return false
	}
	now := time.Now()
	h.seenMessageMu.Lock()
	defer h.seenMessageMu.Unlock()
	if seenAt, ok := h.seenMessageIDs[messageID]; ok && now.Sub(seenAt) < seenMessageTTL {
		return true
	}
	// Lazy GC: drop a handful of stale entries on each insert so the map
	// doesn't grow unbounded under burst sessions.
	if len(h.seenMessageIDs) > 256 {
		dropped := 0
		for k, v := range h.seenMessageIDs {
			if now.Sub(v) >= seenMessageTTL {
				delete(h.seenMessageIDs, k)
				dropped++
				if dropped >= 32 {
					break
				}
			}
		}
	}
	h.seenMessageIDs[messageID] = now
	return false
}

// resolveRunID maps an OpenClaw-assigned UUID back to the device idempotencyKey if known.
// If no mapping exists, returns the original runID unchanged.
func (h *OpenClawHandler) resolveRunID(runID string) string {
	h.runIDMapMu.Lock()
	defer h.runIDMapMu.Unlock()
	if mapped, ok := h.runIDMap[runID]; ok {
		return mapped
	}
	return runID
}

// mapRunID records that OpenClaw UUID corresponds to the given device trace (idempotencyKey).
func (h *OpenClawHandler) mapRunID(openclawID, deviceID string) {
	h.runIDMapMu.Lock()
	defer h.runIDMapMu.Unlock()
	h.runIDMap[openclawID] = deviceID
	// Limit map size to prevent unbounded growth
	if len(h.runIDMap) > 200 {
		for k := range h.runIDMap {
			delete(h.runIDMap, k)
			break
		}
	}
}
