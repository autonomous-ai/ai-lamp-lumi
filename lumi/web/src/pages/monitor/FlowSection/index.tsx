import { useCallback, useMemo, useState } from "react";
import { S } from "../styles";
import { API, FLOW_EVENTS_MAX } from "../types";
import type { DisplayEvent } from "../types";
import type { FlowStage } from "./types";
import { FLOW_NODES, SOURCE_ICON } from "./types";
import { deriveActiveStage, groupIntoTurns, turnIO, extractTurnTiming, turnBilledTokens, turnDurationMs } from "./helpers";
import { FlowDiagram } from "./FlowDiagram";
import { TurnBadge } from "./TurnBadge";
import { CanvasModal } from "./CanvasModal";

// Category → turn types mapping
const CAT_TYPES: Record<string, string[]> = {
  mic: ["voice", "voice_command", "sound"],
  cam: ["motion", "motion.activity", "presence.enter", "presence.leave", "presence.away", "light.level", "environment", "wellbeing.hydration", "wellbeing.break"],
  telegram: ["telegram"],
  system: ["system", "schedule"],
};
const TYPE_ICON: Record<string, string> = {
  ...SOURCE_ICON,
  voice_command: "🎙",
};
const TYPE_LABEL: Record<string, string> = {
  voice: "voice", voice_command: "cmd", sound: "sound",
  motion: "motion", "motion.activity": "activity", "presence.enter": "enter", "presence.leave": "leave", "presence.away": "away",
  "wellbeing.hydration": "water", "wellbeing.break": "break",
  "light.level": "light", environment: "env", system: "sys",
  telegram: "TG", schedule: "sched",
};

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
  // Opt-out model: store what user has EXCLUDED. Empty = show all.
  const [excludedTypes, setExcludedTypes] = useState<Set<string>>(() => {
    try {
      const saved = localStorage.getItem("lumi-excluded-types-v1");
      if (saved) return new Set(JSON.parse(saved));
    } catch {}
    return new Set();
  });
  const [searchText, setSearchText] = useState("");
  const [fromTime, setFromTime] = useState("");
  const [toTime, setToTime] = useState("");
  const [sortBy, setSortBy] = useState<"newest" | "oldest" | "time_desc" | "time_asc" | "tokens_desc" | "tokens_asc">("newest");
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
      const r = await fetch(`${API}/openclaw/debug-logs?last=500`);
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
    const jsonlOk = await downloadServerJsonlTail();
    if (jsonlOk) await new Promise((resolve) => setTimeout(resolve, 500));
    const debugOk = await downloadOpenClawDebugPayloads();
    if (debugOk) await new Promise((resolve) => setTimeout(resolve, 300));
    downloadUISnapshot();
  }, [downloadServerJsonlTail, downloadOpenClawDebugPayloads, downloadUISnapshot]);

  const saveExcluded = (next: Set<string>) => {
    try { localStorage.setItem("lumi-excluded-types-v1", JSON.stringify([...next])); } catch {}
  };

  const toggleType = (type: string) => {
    setExcludedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type); else next.add(type);
      saveExcluded(next);
      return next;
    });
  };

  const toggleCategory = (cat: string) => {
    const catTypes = CAT_TYPES[cat] ?? [];
    setExcludedTypes((prev) => {
      const allExcluded = catTypes.every((t) => prev.has(t));
      const next = new Set(prev);
      if (allExcluded) { catTypes.forEach((t) => next.delete(t)); }
      else { catTypes.forEach((t) => next.add(t)); }
      saveExcluded(next);
      return next;
    });
  };

  const turns = useMemo(() => groupIntoTurns(events), [events]);

  // Sub-types that actually appear in the current turns list
  const availableTypes = useMemo(() => {
    const seen = new Set<string>();
    for (const t of turns) seen.add(t.type);
    return [...seen];
  }, [turns]);

  const filteredTurns = useMemo(() => {
    const filtered = turns.filter((t) => {
      if (excludedTypes.has(t.type)) return false;
      if (fromTime || toTime) {
        const m = t.startTime.match(/T(\d{2}:\d{2})/);
        const tt = m?.[1] ?? "";
        if (fromTime && tt < fromTime) return false;
        if (toTime && tt > toTime) return false;
      }
      if (searchText.trim()) {
        const q = searchText.toLowerCase().trim();
        const { input, output } = turnIO(t);
        if (!`${input} ${output} ${t.type}`.toLowerCase().includes(q)) return false;
      }
      return true;
    });
    if (sortBy === "oldest") {
      filtered.reverse();
    } else if (sortBy === "time_desc") {
      filtered.sort((a, b) => turnDurationMs(b) - turnDurationMs(a));
    } else if (sortBy === "time_asc") {
      filtered.sort((a, b) => turnDurationMs(a) - turnDurationMs(b));
    } else if (sortBy === "tokens_desc") {
      filtered.sort((a, b) => turnBilledTokens(b) - turnBilledTokens(a));
    } else if (sortBy === "tokens_asc") {
      filtered.sort((a, b) => turnBilledTokens(a) - turnBilledTokens(b));
    }
    // "newest" = default order from groupIntoTurns (newest first)
    return filtered;
  }, [turns, excludedTypes, fromTime, toTime, searchText, sortBy]);
  // When user explicitly selected a turn, keep it even if new events arrive.
  // Only auto-select latest turn when nothing is selected.
  const selectedTurn = selectedTurnId
    ? (turns.find((t) => t.id === selectedTurnId) ?? turns.find((t) => t.runId === selectedTurnId))
    : filteredTurns[0];

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
    // Detect sensing type from sensing_input, chat_send, or agent_call events
    const isSensingInput = ev.type === "sensing_input" ||
      (ev.type === "flow_enter" && ev.detail?.node === "sensing_input") ||
      (ev.type === "flow_event" && ev.detail?.node === "sensing_input");
    const fromSensingChatSend = (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send")) &&
      /^\[sensing:[^\]]+\]/i.test(ev.summary ?? "");
    const d = ev.detail as Record<string, any> | undefined;
    const sensingType = d?.data?.type ?? d?.type;
    const fromSensingAgentCall = (ev.type === "flow_event" && ev.detail?.node === "agent_call") &&
      (sensingType === "voice" || sensingType === "voice_command" || sensingType === "motion" || sensingType === "motion.activity" || sensingType === "sound");
    if (isSensingInput || fromSensingChatSend || fromSensingAgentCall) {
      // Determine mic vs cam from sensing type or summary bracket
      let detectedType = sensingType;
      if (!detectedType && ev.summary) {
        const m = ev.summary.match(/^\[([^\]]+)\]/);
        detectedType = m?.[1]?.replace("sensing:", "") ?? "";
      }
      const isCam = /motion|presence|light/i.test(detectedType ?? "");
      visitedStages.add(isCam ? "cam_input" : "mic_input");
      break;
    }
  }

  // HW nodes: light up when intent_match has hardware actions (local path → LED)
  if (visitedStages.has("local_match")) {
    const hasActions = turnEvents.some((ev) => {
      if (ev.type !== "intent_match" && !(ev.type === "flow_event" && ev.detail?.node === "intent_match")) return false;
      const d = ev.detail as Record<string, any> | undefined;
      const actions: string[] = d?.data?.actions ?? d?.actions ?? [];
      return actions.length > 0;
    });
    if (hasActions) visitedStages.add("hw_led");
  }

  // TTS suppressed: mark TTS as visited so it shows red via nodeColor
  const hasTtsSuppressed = turnEvents.some((ev) =>
    ev.type === "flow_event" && (ev.detail as Record<string, any>)?.node === "tts_suppressed"
  );
  if (hasTtsSuppressed) visitedStages.add("tts_speak");

  // TG OUT: only light up for telegram turns with a real response (not no_reply)
  if (selectedTurn?.type === "telegram" && visitedStages.has("agent_response")) {
    const hasNoReply = turnEvents.some((ev) =>
      (ev.type === "flow_event" && ev.detail?.node === "no_reply") ||
      (ev.type === "chat_response" && ev.summary === "[no reply]")
    );
    if (!hasNoReply) {
      visitedStages.add("tg_out");
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%", overflow: "hidden" }}>
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
      <div style={{ display: "flex", gap: 14, flex: 1, minHeight: 0 }}>

        {/* Turn history list */}
        <div style={{
          ...S.card,
          width: 280,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column" as const,
          minHeight: 0,
          padding: 0,
          overflow: "hidden",
        }}>
          <div style={{ padding: "10px 12px 8px", borderBottom: "1px solid var(--lm-border)" }}>
            {/* Title + count + All button */}
            <div style={{ display: "flex", alignItems: "center", marginBottom: 6 }}>
              <span style={S.cardLabel}>Turns</span>
              <span style={{ fontSize: 10, color: "var(--lm-text-muted)", marginLeft: 6 }}>
                {filteredTurns.length}/{turns.length}
              </span>
              <button
                onClick={() => {
                  const allOn = availableTypes.every((t) => !excludedTypes.has(t));
                  setExcludedTypes((prev) => {
                    const next = new Set(prev);
                    if (allOn) { availableTypes.forEach((t) => next.add(t)); }
                    else { availableTypes.forEach((t) => next.delete(t)); }
                    saveExcluded(next);
                    return next;
                  });
                }}
                style={{
                  marginLeft: "auto", padding: "1px 6px", borderRadius: 4, fontSize: 9,
                  cursor: "pointer", fontWeight: 600,
                  border: `1px solid ${availableTypes.every((t) => !excludedTypes.has(t)) ? "var(--lm-amber)" : "var(--lm-border)"}`,
                  background: availableTypes.every((t) => !excludedTypes.has(t)) ? "rgba(245,158,11,0.15)" : "transparent",
                  color: availableTypes.every((t) => !excludedTypes.has(t)) ? "var(--lm-amber)" : "var(--lm-text-muted)",
                }}
              >All</button>
            </div>

            {/* Sort */}
            <div style={{ display: "flex", gap: 3, marginBottom: 5 }}>
              {([
                { key: "newest", label: "Newest" },
                { key: "oldest", label: "Oldest" },
                { key: "time_desc", label: "Slowest" },
                { key: "time_asc", label: "Fastest" },
                { key: "tokens_desc", label: "Most tokens" },
                { key: "tokens_asc", label: "Least tokens" },
              ] as const).map((s) => (
                <button
                  key={s.key}
                  onClick={() => setSortBy(s.key)}
                  style={{
                    padding: "1px 5px", borderRadius: 3, fontSize: 9, cursor: "pointer",
                    border: `1px solid ${sortBy === s.key ? "var(--lm-amber)" : "var(--lm-border)"}`,
                    background: sortBy === s.key ? "rgba(245,158,11,0.15)" : "transparent",
                    color: sortBy === s.key ? "var(--lm-amber)" : "var(--lm-text-muted)",
                    fontWeight: sortBy === s.key ? 600 : 400,
                  }}
                >{s.label}</button>
              ))}
            </div>

            {/* Search */}
            <input
              type="text"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="search input / output…"
              style={{
                width: "100%", boxSizing: "border-box" as const,
                padding: "4px 8px", borderRadius: 5, fontSize: 10,
                background: "var(--lm-bg)", border: "1px solid var(--lm-border)",
                color: "var(--lm-text)", marginBottom: 6, outline: "none",
              }}
            />

            {/* Category quick-toggle */}
            <div style={{ display: "flex", gap: 4, marginBottom: 5, flexWrap: "wrap" as const }}>
              {([
                { key: "mic", icon: "🎤", label: "Mic" },
                { key: "cam", icon: "👁", label: "Cam" },
                { key: "telegram", icon: "💬", label: "TG" },
                { key: "system", icon: "⚙", label: "Sys" },
              ] as const).map((f) => {
                const catTypes = CAT_TYPES[f.key] ?? [];
                const available = catTypes.filter((t) => availableTypes.includes(t));
                const active = available.length > 0 && available.every((t) => !excludedTypes.has(t));
                const partial = !active && available.some((t) => !excludedTypes.has(t));
                const border = active ? "var(--lm-amber)" : partial ? "var(--lm-teal)" : "var(--lm-border)";
                const color = active ? "var(--lm-amber)" : partial ? "var(--lm-teal)" : "var(--lm-text-muted)";
                return (
                  <button key={f.key} onClick={() => toggleCategory(f.key)} style={{
                    padding: "2px 6px", borderRadius: 4, fontSize: 9, cursor: "pointer",
                    border: `1px solid ${border}`,
                    background: active ? "rgba(245,158,11,0.15)" : partial ? "rgba(45,212,191,0.1)" : "transparent",
                    color, fontWeight: active || partial ? 600 : 400,
                  }}>
                    {f.icon} {f.label}
                  </button>
                );
              })}
            </div>

            {/* Sub-type chips — only for types that actually appear */}
            {availableTypes.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 3, marginBottom: 5 }}>
                {availableTypes.map((type) => {
                  const on = !excludedTypes.has(type);
                  const icon = TYPE_ICON[type] ?? "•";
                  const label = TYPE_LABEL[type] ?? type.replace("ambient:", "~");
                  return (
                    <button key={type} onClick={() => toggleType(type)} title={type} style={{
                      padding: "1px 5px", borderRadius: 3, fontSize: 9, cursor: "pointer",
                      border: `1px solid ${on ? "var(--lm-teal)" : "var(--lm-border)"}`,
                      background: on ? "rgba(45,212,191,0.12)" : "transparent",
                      color: on ? "var(--lm-teal)" : "var(--lm-text-muted)",
                      fontWeight: on ? 600 : 400,
                    }}>
                      {icon} {label}
                    </button>
                  );
                })}
              </div>
            )}

            {/* Time range */}
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ fontSize: 9, color: "var(--lm-text-muted)", flexShrink: 0 }}>from</span>
              <input
                type="time"
                value={fromTime}
                onChange={(e) => setFromTime(e.target.value)}
                style={{
                  flex: 1, padding: "2px 4px", borderRadius: 4, fontSize: 9,
                  background: "var(--lm-bg)", border: "1px solid var(--lm-border)",
                  color: fromTime ? "var(--lm-text)" : "var(--lm-text-muted)", outline: "none",
                }}
              />
              <span style={{ fontSize: 9, color: "var(--lm-text-muted)", flexShrink: 0 }}>to</span>
              <input
                type="time"
                value={toTime}
                onChange={(e) => setToTime(e.target.value)}
                style={{
                  flex: 1, padding: "2px 4px", borderRadius: 4, fontSize: 9,
                  background: "var(--lm-bg)", border: "1px solid var(--lm-border)",
                  color: toTime ? "var(--lm-text)" : "var(--lm-text-muted)", outline: "none",
                }}
              />
              {(fromTime || toTime) && (
                <button onClick={() => { setFromTime(""); setToTime(""); }} style={{
                  padding: "1px 4px", borderRadius: 3, fontSize: 9, cursor: "pointer",
                  border: "1px solid var(--lm-border)", background: "transparent",
                  color: "var(--lm-red)", fontWeight: 700,
                }}>✕</button>
              )}
            </div>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 5 }} className="lm-hide-scroll">
            {filteredTurns.length === 0 ? (
              <div style={{ padding: 12, color: "var(--lm-text-muted)", fontSize: 11 }}>No turns match filter</div>
            ) : (
              filteredTurns.map((turn, i) => (
                <div key={turn.id}>
                  {i > 0 && filteredTurns[i - 1].sessionBreak && (
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
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
          <div style={{ ...S.card, flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <div style={{ marginBottom: 10, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={S.cardLabel}>Turn Pipeline</span>
              {selectedTurn && (
                <span style={{ fontSize: 10, color: "var(--lm-text-muted)" }}>
                  {selectedTurn.type} · {selectedTurn.events.length} events
                  {selectedTurn.endTime ? ` · done` : ` · active`}
                </span>
              )}
            </div>
            {selectedTurn?.endTime && (() => {
              const timing = extractTurnTiming(selectedTurn.events, selectedTurn.startTime, selectedTurn.endTime);
              if (!timing || timing.segments.length === 0) return null;
              const fmtTotal = timing.total >= 60_000 ? `${(timing.total / 60_000).toFixed(1)}m`
                : timing.total >= 1000 ? `${(timing.total / 1000).toFixed(1)}s` : `${timing.total}ms`;
              return (
                <div style={{ marginBottom: 8, fontSize: 10, fontFamily: "monospace" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ color: "var(--lm-text-muted)", whiteSpace: "nowrap" }}>⏱ {fmtTotal}</span>
                    <div style={{ flex: 1, display: "flex", height: 14, borderRadius: 4, overflow: "hidden", background: "var(--lm-surface)" }}>
                      {timing.segments.map((seg, i) => {
                        const pct = Math.max((seg.ms / timing.total) * 100, 2);
                        return (
                          <div key={i} title={seg.label} style={{
                            width: `${pct}%`, background: seg.color, opacity: 0.7,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            fontSize: 8, color: "#fff", fontWeight: 600, whiteSpace: "nowrap",
                            overflow: "hidden", textOverflow: "ellipsis", padding: "0 2px",
                          }}>
                            {pct > 12 ? seg.label : ""}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 5 }}>
                    {timing.segments.map((seg, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: 4, lineHeight: 1.3 }}>
                        <span style={{ width: 6, height: 6, borderRadius: 2, background: seg.color, opacity: 0.7, display: "inline-block", flexShrink: 0 }} />
                        <span style={{ color: "var(--lm-text)", fontSize: 9, fontWeight: 600, whiteSpace: "nowrap" }}>{seg.label}</span>
                        {seg.from && seg.to && (
                          <span style={{ fontSize: 9, color: "var(--lm-green)" }}>
                            <code style={{ background: "var(--lm-surface)", padding: "1px 4px", borderRadius: 3, fontSize: 8 }}>{seg.from}</code>
                            {" → "}
                            <code style={{ background: "var(--lm-surface)", padding: "1px 4px", borderRadius: 3, fontSize: 8 }}>{seg.to}</code>
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
            <FlowDiagram activeStage={activeStage} visitedStages={visitedStages} turnEvents={turnEvents} compact />
          </div>
        </div>

      </div>
    </div>
  );
}
