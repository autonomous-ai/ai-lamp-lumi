import { useCallback, useState } from "react";
import { S } from "../styles";
import { API, FLOW_EVENTS_MAX } from "../types";
import type { DisplayEvent } from "../types";
import type { FlowStage } from "./types";
import { FLOW_NODES } from "./types";
import { deriveActiveStage, groupIntoTurns } from "./helpers";
import { FlowDiagram } from "./FlowDiagram";
import { TurnBadge } from "./TurnBadge";
import { CanvasModal } from "./CanvasModal";

// Preset sensing events for manual testing
const FAKE_EVENTS: { label: string; type: string; message: string; color: string; tag: string }[] = [
  { label: "bật đèn",          type: "voice",       message: "bật đèn",                            color: "var(--lm-green)",  tag: "LOCAL"  },
  { label: "tắt đèn",          type: "voice",       message: "tắt đèn",                            color: "var(--lm-green)",  tag: "LOCAL"  },
  { label: "reading mode",     type: "voice",       message: "reading mode",                       color: "var(--lm-green)",  tag: "LOCAL"  },
  { label: "thời tiết?",       type: "voice",       message: "hôm nay thời tiết thế nào?",         color: "var(--lm-blue)",   tag: "AGENT"  },
  { label: "kể chuyện",        type: "voice",       message: "kể cho tôi nghe một câu chuyện",     color: "var(--lm-blue)",   tag: "AGENT"  },
  { label: "motion",           type: "motion",      message: "motion detected in living room",     color: "var(--lm-amber)",  tag: "SENSE"  },
  { label: "environment",      type: "environment", message: "temperature 28C humidity 65%",       color: "var(--lm-teal)",   tag: "ENV"    },
];

export function FlowSection({
  events,
  onClearEvents,
}: {
  events: DisplayEvent[];
  onClearEvents: () => void;
}) {
  const [showCanvas, setShowCanvas] = useState(false);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [firing, setFiring] = useState<string | null>(null);

  async function fireEvent(ev: typeof FAKE_EVENTS[0]) {
    setFiring(ev.label);
    try {
      await fetch(`${API}/sensing/event`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: ev.type, message: ev.message }),
      });
    } finally {
      setTimeout(() => setFiring(null), 800);
    }
  }

  const clearServerFlowLog = useCallback(async () => {
    const ok = window.confirm("Clear flow log file on server (today)? This cannot be undone.");
    if (!ok) return;
    try {
      const r = await fetch(`${API}/openclaw/flow-logs`, { method: "DELETE" });
      const j = await r.json();
      if (!r.ok || j?.status !== 1) throw new Error(j?.message || "request failed");

      const r2 = await fetch(`${API}/openclaw/debug-logs`, { method: "DELETE" });
      const j2 = await r2.json();
      if (!r2.ok || j2?.status !== 1) throw new Error(j2?.message || "request failed");

      setSelectedTurnId(null);
      onClearEvents();
      window.alert("Server flow log + OpenClaw debug logs cleared.");
    } catch (e) {
      window.alert(`Failed to clear server flow log: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [onClearEvents]);

  const downloadUISnapshot = useCallback(() => {
    const turnsSnapshot = groupIntoTurns(events);
    const payload = {
      exportedAt: new Date().toISOString(),
      format: "lumi-monitor-ui-snapshot-v1",
      flowEventsWindow: FLOW_EVENTS_MAX,
      eventCount: events.length,
      turnCount: turnsSnapshot.length,
      events,
      turns: turnsSnapshot.map((t) => ({
        id: t.id,
        runId: t.runId,
        startTime: t.startTime,
        endTime: t.endTime,
        type: t.type,
        path: t.path,
        status: t.status,
        sessionBreak: t.sessionBreak,
        events: t.events,
      })),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `lumi_flow_ui_snapshot_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [events]);

  const downloadServerJsonlTail = useCallback(async (): Promise<boolean> => {
    try {
      const r = await fetch(`${API}/openclaw/flow-logs?last=${FLOW_EVENTS_MAX}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const day = new Date().toISOString().slice(0, 10);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `lumi_flow_${day}_last${FLOW_EVENTS_MAX}.jsonl`;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      return true;
    } catch (e) {
      console.error(e);
      window.alert(`JSONL download failed: ${e instanceof Error ? e.message : String(e)}`);
      return false;
    }
  }, []);

  const downloadOpenClawDebugPayloads = useCallback(async (): Promise<boolean> => {
    try {
      const r = await fetch(`${API}/openclaw/debug-logs`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `openclaw_debug_payloads_${new Date().toISOString().replace(/[:.]/g, "-")}.jsonl`;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      return true;
    } catch (e) {
      console.error(e);
      window.alert(`OpenClaw debug download failed: ${e instanceof Error ? e.message : String(e)}`);
      return false;
    }
  }, []);

  const downloadFlowBundle = useCallback(async () => {
    await downloadServerJsonlTail();
    await new Promise((resolve) => setTimeout(resolve, 500));
    await downloadOpenClawDebugPayloads();
    await new Promise((resolve) => setTimeout(resolve, 300));
    downloadUISnapshot();
  }, [downloadServerJsonlTail, downloadOpenClawDebugPayloads, downloadUISnapshot]);

  const turns = groupIntoTurns(events);
  const selectedTurn = selectedTurnId ? turns.find((t) => t.id === selectedTurnId) : turns[0];

  const turnEvents = selectedTurn?.events ?? events.slice(-30);
  const activeStage = deriveActiveStage(turnEvents);

  const visitedStages = new Set<FlowStage>();
  for (const ev of turnEvents) {
    const node = ev.detail?.node as string | undefined;
    const key = (ev.type === "flow_event" || ev.type === "flow_enter" || ev.type === "flow_exit") && node
      ? `${ev.type}:${node}`
      : ev.type;
    for (const flowNode of FLOW_NODES) {
      if (flowNode.triggers.includes(key)) visitedStages.add(flowNode.id);
    }
  }
  for (const ev of turnEvents) {
    const fromSensingChatSend = (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send")) &&
      /^\[sensing:[^\]]+\]/i.test(ev.summary ?? "");
    const d = ev.detail as Record<string, any> | undefined;
    const sensingType = d?.data?.type;
    const fromSensingAgentCall = (ev.type === "flow_event" && ev.detail?.node === "agent_call") &&
      (sensingType === "voice" || sensingType === "voice_command" || sensingType === "motion" || sensingType === "sound");
    if (fromSensingChatSend || fromSensingAgentCall) {
      visitedStages.add("sensing");
      break;
    }
  }

  const activeNode = FLOW_NODES.find((n) => n.id === activeStage);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      {showCanvas && (
        <CanvasModal
          activeStage={activeStage}
          visitedStages={visitedStages}
          turnEvents={turnEvents}
          onClose={() => setShowCanvas(false)}
        />
      )}

      {/* Header card */}
      <div style={{ ...S.card, padding: "12px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={S.cardLabel}>Flow Panel</span>
            {activeNode && (
              <span style={{
                fontSize: 10, padding: "2px 8px", borderRadius: 4,
                background: `${activeNode.color}20`, color: activeNode.color,
                border: `1px solid ${activeNode.color}50`, fontWeight: 700,
              }}>
                ● {activeNode.label.toUpperCase()}
              </span>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 8, alignItems: "center" }}>
            <button
              type="button"
              onClick={() => void downloadFlowBundle()}
              title={`Downloads 3 files: (1) server JSONL last ${FLOW_EVENTS_MAX} lines — same tail as this panel; (2) UI snapshot JSON (events + turns); (3) OpenClaw debug payload JSONL.`}
              style={{
                fontSize: 11, padding: "4px 12px", borderRadius: 6,
                background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                color: "var(--lm-text-dim)", cursor: "pointer", fontWeight: 600,
              }}
            >
              ↓ Bundle
            </button>
            <a
              href={`${API}/openclaw/flow-logs`}
              download
              title="Full day JSONL on server (all lines today — wider than the panel window)"
              style={{
                fontSize: 10, padding: "4px 8px", borderRadius: 6,
                color: "var(--lm-text-muted)", cursor: "pointer", fontWeight: 600,
                textDecoration: "underline", display: "inline-flex", alignItems: "center",
              }}
            >
              full day
            </a>
            <button
              onClick={clearServerFlowLog}
              style={{
                fontSize: 11, padding: "4px 12px", borderRadius: 6,
                background: "rgba(248,113,113,0.12)", border: "1px solid rgba(248,113,113,0.35)",
                color: "var(--lm-red)", cursor: "pointer", fontWeight: 700,
              }}
              title="Clear server flow log + OpenClaw debug logs"
            >
              🗑 Log
            </button>
            <button
              onClick={() => setShowCanvas(true)}
              style={{
                fontSize: 11, padding: "4px 12px", borderRadius: 6,
                background: "var(--lm-amber-dim)", border: "1px solid var(--lm-amber)",
                color: "var(--lm-amber)", cursor: "pointer", fontWeight: 600,
              }}
            >
              ⬢ Canvas
            </button>
          </div>
        </div>
      </div>

      {/* Simulate card — hidden for now */}
      {false && window.location.hostname === "localhost" && (
        <div style={{ ...S.card, padding: "10px 14px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <span style={S.cardLabel}>Simulate Event</span>
            <span style={{ fontSize: 10, color: "var(--lm-text-muted)" }}>dev only · fires POST /sensing/event on device</span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 6 }}>
            {FAKE_EVENTS.map((ev) => (
              <button
                key={ev.label}
                onClick={() => fireEvent(ev)}
                disabled={firing !== null}
                style={{
                  fontSize: 11, padding: "4px 11px", borderRadius: 6, cursor: "pointer",
                  background: firing === ev.label ? `${ev.color}25` : "var(--lm-surface)",
                  border: `1px solid ${firing === ev.label ? ev.color : "var(--lm-border)"}`,
                  color: firing === ev.label ? ev.color : "var(--lm-text-dim)",
                  fontWeight: 600, transition: "all 0.15s",
                  display: "flex", alignItems: "center", gap: 5,
                }}
              >
                <span style={{
                  fontSize: 9, padding: "1px 4px", borderRadius: 3,
                  background: `${ev.color}20`, color: ev.color, fontWeight: 700,
                }}>{ev.tag}</span>
                {firing === ev.label ? "…" : ev.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Flow diagram + turn list */}
      <div style={{ display: "flex", gap: 14, minHeight: 0 }}>

        {/* Turn history list */}
        <div style={{
          ...S.card,
          width: 210,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column" as const,
          minHeight: 0,
          padding: 0,
          overflow: "hidden",
        }}>
          <div style={{ padding: "10px 12px 8px", borderBottom: "1px solid var(--lm-border)" }}>
            <span style={S.cardLabel}>Turns</span>
            <span style={{ fontSize: 10, color: "var(--lm-text-muted)", marginLeft: 6 }}>{turns.length}</span>
            <div style={{ fontSize: 9, color: "var(--lm-text-muted)", marginTop: 4, lineHeight: 1.3 }}>
              From last {FLOW_EVENTS_MAX} flow events (max 100 turns)
            </div>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 5 }} className="lm-hide-scroll">
            {turns.length === 0 ? (
              <div style={{ padding: 12, color: "var(--lm-text-muted)", fontSize: 11 }}>No turns yet</div>
            ) : (
              turns.map((turn, i) => (
                <div key={turn.id}>
                  {i > 0 && turns[i - 1].sessionBreak && (
                    <div style={{
                      display: "flex", alignItems: "center", gap: 8, padding: "4px 0", margin: "2px 0",
                    }}>
                      <div style={{ flex: 1, borderTop: "1px dashed var(--lm-text-muted)", opacity: 0.4 }} />
                      <span style={{ fontSize: 8, color: "var(--lm-text-muted)", whiteSpace: "nowrap" }}>session</span>
                      <div style={{ flex: 1, borderTop: "1px dashed var(--lm-text-muted)", opacity: 0.4 }} />
                    </div>
                  )}
                  <div
                    onClick={() => setSelectedTurnId(turn.id === selectedTurn?.id ? null : turn.id)}
                    style={{
                      borderRadius: 8,
                      outline: turn.id === selectedTurn?.id ? `2px solid var(--lm-amber)` : "none",
                      cursor: "pointer",
                    }}
                  >
                    <TurnBadge turn={turn} />
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Center: flow diagram */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ ...S.card }}>
            <div style={{ marginBottom: 10, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={S.cardLabel}>Turn Pipeline</span>
              {selectedTurn && (
                <span style={{ fontSize: 10, color: "var(--lm-text-muted)" }}>
                  {selectedTurn.type} · {selectedTurn.events.length} events
                  {selectedTurn.endTime ? ` · done` : ` · active`}
                </span>
              )}
            </div>
            <FlowDiagram activeStage={activeStage} visitedStages={visitedStages} turnEvents={turnEvents} compact />
          </div>
        </div>

        {/* Right: event timeline for selected turn */}
        <div style={{
          ...S.card,
          width: 260,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column" as const,
          minHeight: 0,
          maxHeight: 420,
          padding: 0,
          overflow: "hidden",
        }}>
          <div style={{ padding: "10px 12px 8px", borderBottom: "1px solid var(--lm-border)" }}>
            <span style={S.cardLabel}>
              {selectedTurn ? `Turn Events` : "Latest Events"}
            </span>
            <span style={{ fontSize: 10, color: "var(--lm-text-muted)", marginLeft: 6 }}>
              {turnEvents.length}
            </span>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "6px 0" }} className="lm-hide-scroll">
            {turnEvents.length === 0 ? (
              <div style={{ padding: "12px 14px", color: "var(--lm-text-muted)", fontSize: 11 }}>No events</div>
            ) : (
              [...turnEvents].reverse().map((ev) => {
                const key = ev.type === "flow_event" && ev.detail?.node ? `flow_event:${ev.detail.node}` : ev.type;
                const matchNode = FLOW_NODES.find((n) => n.triggers.includes(key));
                const dotColor = matchNode?.color ?? "var(--lm-text-muted)";
                return (
                  <div key={ev._seq} style={{
                    padding: "5px 12px",
                    borderLeft: `2px solid ${dotColor}`,
                    marginLeft: 8, marginRight: 8, marginBottom: 2,
                    borderRadius: "0 5px 5px 0",
                    background: "var(--lm-surface)",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 2 }}>
                      <span style={{ fontSize: 9, fontWeight: 700, color: dotColor, textTransform: "uppercase" as const }}>
                        {matchNode?.short ?? ev.type.replace("flow_", "").replace("_", " ")}
                      </span>
                      <span style={{ fontSize: 9, color: "var(--lm-text-muted)", marginLeft: "auto" }}>{ev.time}</span>
                    </div>
                    <div style={{ fontSize: 10.5, color: "var(--lm-text-dim)", wordBreak: "break-word" as const, lineHeight: 1.4 }}>
                      {ev.summary}
                    </div>
                    {ev.detail?.dur_ms && Number(ev.detail.dur_ms) > 0 && (
                      <div style={{ fontSize: 9, color: "var(--lm-text-muted)", marginTop: 1 }}>
                        {ev.detail.dur_ms}ms
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
