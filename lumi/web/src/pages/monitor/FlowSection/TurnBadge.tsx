import type { Turn } from "./types";
import { SOURCE_ICON, TURN_INPUT_FALLBACK } from "./types";
import { turnIO, turnTokenStats } from "./helpers";

export function TurnBadge({ turn }: { turn: Turn }) {
  const formatTurnTime = (iso: string): string => {
    const m = iso.match(/T(\d{2}:\d{2}:\d{2})/);
    return (m?.[1] ?? iso).trim();
  };

  const pathColor = turn.path === "local" ? "var(--lm-green)"
    : turn.path === "agent" ? "var(--lm-blue)"
    : "var(--lm-text-muted)";
  const statusColor = turn.status === "done" ? "var(--lm-green)"
    : turn.status === "error" ? "var(--lm-red)"
    : "var(--lm-amber)";
  const icon = SOURCE_ICON[turn.type] ?? SOURCE_ICON.unknown;
  const { input, output, hwOutput } = turnIO(turn);
  const tokenStats = turnTokenStats(turn);
  const fmtToken = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);
  const statusLabel = turn.status === "done"
    ? "DONE"
    : turn.status === "error"
      ? "ERROR"
      : "ACTIVE";
  const pathLabel = turn.path === "agent" ? "OpenClaw" : turn.path;

  return (
    <div style={{
      padding: "8px 10px",
      borderRadius: 8,
      background: "var(--lm-surface)",
      border: "1px solid var(--lm-border)",
      fontSize: 11,
      cursor: "default",
    }}>
      {/* Row 1: source icon + type + path + status tag */}
      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 4 }}>
        <span style={{ fontSize: 14, lineHeight: 1 }}>{icon}</span>
        <span style={{
          fontSize: 10, fontWeight: 700, color: "var(--lm-text)",
          textTransform: "uppercase" as const,
        }}>{turn.type}</span>
        <span style={{
          fontSize: 8, padding: "1px 5px", borderRadius: 3,
          background: `${pathColor}18`, color: pathColor, fontWeight: 700,
        }}>{pathLabel}</span>
        <span style={{
          fontSize: 8, padding: "1px 5px", borderRadius: 3,
          background: `${statusColor}18`, color: statusColor, fontWeight: 700,
          textTransform: "uppercase" as const,
        }}>{statusLabel}</span>
      </div>

      {/* Row 2: time only (HH:mm) */}
      <div style={{
        fontSize: 8,
        color: "var(--lm-text)",
        fontFamily: "monospace",
        marginBottom: 3,
        opacity: 0.95,
      }}>
        {formatTurnTime(turn.startTime)}
      </div>
      {/* Turn ID for tracing */}
      <div style={{ fontSize: 8, color: "var(--lm-text-muted)", fontFamily: "monospace", marginBottom: 3, opacity: 0.7 }}>
        id: {turn.id}
      </div>
      {/* Row 2: input */}
      <div style={{
        fontSize: 10, color: "var(--lm-text-dim)", marginBottom: 3,
        wordBreak: "break-word" as const, lineHeight: 1.4,
      }}>
        <span style={{ color: "var(--lm-teal)", fontWeight: 600, marginRight: 4 }}>IN</span>
        {input || TURN_INPUT_FALLBACK}
      </div>
      {/* Row 3: output — TTS or no reply */}
      {output === "[no reply]" ? (
        <div style={{
          fontSize: 10, color: "var(--lm-text-muted)", marginBottom: 2,
          wordBreak: "break-word" as const, lineHeight: 1.4, fontStyle: "italic",
        }}>
          🚫 no reply — agent decided to do nothing
        </div>
      ) : output ? (
        <div style={{
          fontSize: 10, color: "var(--lm-text-dim)", marginBottom: 2,
          wordBreak: "break-word" as const, lineHeight: 1.4,
        }}>
          <span style={{ color: "var(--lm-purple)", fontWeight: 600, marginRight: 4 }}>TTS 🔊</span>
          {output}
        </div>
      ) : turn.status === "done" ? (
        <div style={{
          fontSize: 10, color: "var(--lm-text-muted)", marginBottom: 2,
          wordBreak: "break-word" as const, lineHeight: 1.4, fontStyle: "italic",
        }}>
          💤 no output — agent processed silently
        </div>
      ) : null}
      {/* Row 3b: output — Hardware actions */}
      {hwOutput && (
        <div style={{
          fontSize: 10, color: "var(--lm-text-dim)",
          wordBreak: "break-word" as const, lineHeight: 1.4,
        }}>
          <span style={{ color: "var(--lm-amber)", fontWeight: 600, marginRight: 4 }}>HW 💡</span>
          {hwOutput}
        </div>
      )}
      {tokenStats && (
        <div style={{
          marginTop: 6,
          padding: "5px 7px",
          borderRadius: 6,
          border: "1px solid rgba(248,113,113,0.55)",
          background: "rgba(248,113,113,0.14)",
          fontSize: 9,
          fontFamily: "monospace",
          lineHeight: 1.6,
        }}>
          <div>
            <span style={{ color: "var(--lm-text)" }}>Tokens </span>
            <span style={{ color: "var(--lm-teal)" }}>in </span>
            <span style={{ color: "var(--lm-text-dim)", fontWeight: 600 }}>{fmtToken(tokenStats.inTok)}</span>
            <span style={{ color: "var(--lm-text)" }}> / </span>
            <span style={{ color: "var(--lm-amber)" }}>out </span>
            <span style={{ color: "var(--lm-text-dim)", fontWeight: 600 }}>{fmtToken(tokenStats.outTok)}</span>
          </div>
          <div>
            <span style={{ color: "var(--lm-text)" }}>Total </span>
            <span style={{ color: "var(--lm-text-dim)", fontWeight: 600 }}>{fmtToken(tokenStats.total)}</span>
          </div>
          {(tokenStats.cacheRead || tokenStats.cacheWrite) ? (
            <div>
              <span style={{ color: "var(--lm-text)" }}>Cache read </span>
              <span style={{ color: "var(--lm-teal)", fontWeight: 600 }}>{fmtToken(tokenStats.cacheRead)}</span>
              <span style={{ color: "var(--lm-text)" }}> / write </span>
              <span style={{ color: "var(--lm-amber)", fontWeight: 600 }}>{fmtToken(tokenStats.cacheWrite)}</span>
            </div>
          ) : null}
        </div>
      )}
      {/* Row 4: event count */}
      <div style={{ fontSize: 9, color: "var(--lm-text-muted)", marginTop: 3, display: "flex", gap: 8, alignItems: "center" }}>
        <span>{turn.events.length} events</span>
      </div>
    </div>
  );
}
