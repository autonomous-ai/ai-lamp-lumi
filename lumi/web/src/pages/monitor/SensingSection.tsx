import { useState } from "react";
import { HW } from "./types";
import { usePolling } from "../../hooks/usePolling";
import { S } from "./styles";
import { StatPill } from "./components";

function fmtAgo(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

interface Perception {
  type: string;
  connected?: boolean;
  last_raw_actions?: string[];
  last_user?: string | null;
  last_sent_emotion?: string | null;
  last_sent_user?: string | null;
  last_detected_emotion?: string | null;
  buffered_snapshots?: number;
  buffered_emotions?: number;
  motion_detected?: boolean;
  emotion_detected?: boolean;
  seconds_since_motion?: number | null;
  seconds_since_detection?: number | null;
  face_present?: boolean;
  faces_count?: number;
  visible?: string[];
  last_person?: string | null;
  last_seen_seconds_ago?: number | null;
  enrolled_count?: number;
  stranger_count?: number;
  level?: number;
  seconds_since_check?: number | null;
  occurrence_count?: number;
  echo_suppression?: boolean;
}

interface SensingData {
  running: boolean;
  poll_interval: number;
  last_event_seconds_ago: Record<string, number>;
  perceptions: Perception[];
  presence: {
    state: string;
    enabled: boolean;
    seconds_since_motion: number;
    idle_timeout: number;
    away_timeout: number;
  };
}

// Status pill used in card headers. Color tier carries quick health signal.
function Pill({ text, color }: { text: string; color: string }) {
  return (
    <span style={{
      fontSize: 10, padding: "2px 7px", borderRadius: 4,
      background: `${color}26`,
      color,
      border: `1px solid ${color}55`,
      fontWeight: 700, letterSpacing: "0.05em",
      textTransform: "uppercase",
    }}>{text}</span>
  );
}

// CardHeader is the uppercase title + pill row shared by every Sensing card.
function CardHeader({ label, pill }: { label: string; pill?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
      <div style={S.cardLabel}>{label}</div>
      {pill}
    </div>
  );
}

// Maps a presence state string to a color so users can scan at a glance.
function presenceColor(state: string): string {
  switch (state) {
    case "active":   return "var(--lm-green)";
    case "idle":     return "var(--lm-amber)";
    case "away":     return "var(--lm-red)";
    default:         return "var(--lm-text-muted)";
  }
}

// Light tier heuristic — sensor returns raw 0-1000ish; rough buckets for UX.
function lightTier(level: number): { label: string; color: string } {
  if (level < 30)  return { label: "Dark",   color: "var(--lm-blue)" };
  if (level < 200) return { label: "Dim",    color: "var(--lm-amber)" };
  if (level < 600) return { label: "Bright", color: "var(--lm-teal)" };
  return                  { label: "Sunlit", color: "var(--lm-green)" };
}

export function SensingSection() {
  const [data, setData] = useState<SensingData | null>(null);

  usePolling(async (signal) => {
    const r = await fetch(`${HW}/sensing`, { signal }).then((x) => x.json());
    setData(r);
  }, 3000);

  if (!data) return <div style={{ color: "var(--lm-text-muted)", padding: 20 }}>Loading sensing data…</div>;

  const motion = data.perceptions.find((p) => p.type === "motion");
  const emotion = data.perceptions.find((p) => p.type === "emotion");
  const face = data.perceptions.find((p) => p.type === "face");
  const light = data.perceptions.find((p) => p.type === "light_level");
  const sound = data.perceptions.find((p) => p.type === "sound");
  const ev = data.last_event_seconds_ago;

  const motionFresh = (motion?.seconds_since_motion ?? Infinity) < 30;
  const faceVisible = (face?.visible?.length ?? 0) > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

      {/* Row 1: the four primary perception streams. */}
      <div className="lm-grid-4">

        {/* Motion */}
        <div style={S.card}>
          <CardHeader
            label="Motion"
            pill={<Pill
              text={motionFresh ? "Active" : "Quiet"}
              color={motionFresh ? "var(--lm-green)" : "var(--lm-text-muted)"}
            />}
          />
          {motion ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <StatPill label="Last user"      value={motion.last_user || "unknown"} />
              <StatPill label="Since motion"   value={fmtAgo(motion.seconds_since_motion)} color={motionFresh ? "var(--lm-green)" : undefined} />
              <StatPill label="Buffered snaps" value={motion.buffered_snapshots ?? 0} />
              <StatPill label="Last actions"   value={motion.last_raw_actions?.length ? motion.last_raw_actions.join(", ") : "—"} />
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)", fontSize: 11 }}>No data</span>}
        </div>

        {/* Emotion */}
        <div style={S.card}>
          <CardHeader
            label="Emotion"
            pill={emotion?.last_sent_emotion ? (
              <Pill text={emotion.last_sent_emotion} color="var(--lm-amber)" />
            ) : <Pill text="None" color="var(--lm-text-muted)" />}
          />
          {emotion ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <StatPill label="Sent user"        value={emotion.last_sent_user || "unknown"} />
              <StatPill label="Detecting"        value={emotion.last_detected_emotion ?? "—"} color="var(--lm-amber)" />
              <StatPill label="Since detection"  value={fmtAgo(emotion.seconds_since_detection)} />
              <StatPill label="Buffered"         value={emotion.buffered_emotions ?? 0} />
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)", fontSize: 11 }}>No data</span>}
        </div>

        {/* Face */}
        <div style={S.card}>
          <CardHeader
            label="Face"
            pill={<Pill
              text={faceVisible ? `${face?.visible?.length} visible` : "Empty"}
              color={faceVisible ? "var(--lm-green)" : "var(--lm-text-muted)"}
            />}
          />
          {face ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <StatPill label="Visible now"  value={face.visible?.length ? face.visible.join(", ") : "nobody"} color={faceVisible ? "var(--lm-green)" : undefined} />
              <StatPill label="Last person"  value={face.last_person ?? "—"} />
              <StatPill label="Last seen"    value={fmtAgo(face.last_seen_seconds_ago)} />
              <StatPill label="Enrolled"     value={face.enrolled_count ?? 0} bullet="var(--lm-teal)" />
              <StatPill label="Strangers"    value={face.stranger_count ?? 0} bullet="var(--lm-red)" />
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)", fontSize: 11 }}>No data</span>}
        </div>

        {/* Presence */}
        <div style={S.card}>
          <CardHeader
            label="Presence"
            pill={<Pill text={data.presence.state || "—"} color={presenceColor(data.presence.state)} />}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <StatPill label="Sensing"        value={data.presence.enabled ? "On" : "Off"} color={data.presence.enabled ? "var(--lm-green)" : "var(--lm-red)"} />
            <StatPill label="Since motion"   value={fmtAgo(data.presence.seconds_since_motion)} />
            <StatPill label="Idle timeout"   value={`${data.presence.idle_timeout}s`} />
            <StatPill label="Away timeout"   value={`${data.presence.away_timeout}s`} />
          </div>
        </div>
      </div>

      {/* Row 2: secondary signals + diagnostic cards. */}
      <div className="lm-grid-4">

        {/* Light Level */}
        <div style={S.card}>
          {(() => {
            const tier = lightTier(light?.level ?? 0);
            return (
              <>
                <CardHeader
                  label="Light"
                  pill={<Pill text={tier.label} color={tier.color} />}
                />
                {light ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <StatPill label="Level"   value={Math.round(light.level ?? 0)} color={tier.color} />
                    <StatPill label="Checked" value={fmtAgo(light.seconds_since_check)} />
                  </div>
                ) : <span style={{ color: "var(--lm-text-muted)", fontSize: 11 }}>No data</span>}
              </>
            );
          })()}
        </div>

        {/* Sound */}
        <div style={S.card}>
          <CardHeader
            label="Sound"
            pill={<Pill
              text={sound?.echo_suppression ? "Echo: on" : "Echo: off"}
              color={sound?.echo_suppression ? "var(--lm-teal)" : "var(--lm-text-muted)"}
            />}
          />
          {sound ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <StatPill label="Occurrences"      value={sound.occurrence_count ?? 0} />
              <StatPill label="Echo suppression" value={sound.echo_suppression ? "On" : "Off"} color={sound.echo_suppression ? "var(--lm-teal)" : undefined} />
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)", fontSize: 11 }}>No data</span>}
        </div>

        {/* DL Backend health */}
        <div style={S.card}>
          <CardHeader label="DL Backend" />
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {data.perceptions.filter((p) => p.connected !== undefined).map((p) => (
              <StatPill
                key={p.type}
                label={p.type}
                value={p.connected ? "Connected" : "Down"}
                color={p.connected ? "var(--lm-green)" : "var(--lm-red)"}
                bullet={p.connected ? "var(--lm-green)" : "var(--lm-red)"}
              />
            ))}
          </div>
        </div>

        {/* Last Events */}
        <div style={S.card}>
          <CardHeader
            label="Last Events"
            pill={<Pill text={`${Object.keys(ev).length} types`} color="var(--lm-text-muted)" />}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {Object.entries(ev).length > 0 ? Object.entries(ev).map(([type, sec]) => (
              <StatPill key={type} label={type} value={fmtAgo(sec)} />
            )) : <span style={{ color: "var(--lm-text-muted)", fontSize: 11 }}>No recent events</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
