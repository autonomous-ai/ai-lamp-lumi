import { useState } from "react";
import { HW } from "./types";
import { usePolling } from "../../hooks/usePolling";

const S = {
  card: { background: "var(--lm-card)", borderRadius: 10, padding: 14, marginBottom: 10 } as const,
  label: { fontSize: 10, color: "var(--lm-text-muted)", marginBottom: 3 } as const,
  value: { fontSize: 13, fontWeight: 600 } as const,
  row: { display: "flex", gap: 14, flexWrap: "wrap" as const, marginBottom: 8 },
  badge: (ok: boolean) => ({
    display: "inline-block",
    fontSize: 10,
    fontWeight: 700,
    padding: "2px 8px",
    borderRadius: 6,
    background: ok ? "rgba(52,211,153,0.15)" : "rgba(239,68,68,0.15)",
    color: ok ? "var(--lm-green)" : "var(--lm-red)",
    border: `1px solid ${ok ? "rgba(52,211,153,0.3)" : "rgba(239,68,68,0.3)"}`,
  }) as const,
};

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

export function SensingSection() {
  const [data, setData] = useState<SensingData | null>(null);

  usePolling(async (signal) => {
    const r = await fetch(`${HW}/sensing`, { signal }).then((x) => x.json());
    setData(r);
  }, 3000);

  if (!data) return <div style={{ padding: 20, color: "var(--lm-text-muted)" }}>Loading sensing data…</div>;

  const motion = data.perceptions.find((p) => p.type === "motion");
  const emotion = data.perceptions.find((p) => p.type === "emotion");
  const face = data.perceptions.find((p) => p.type === "face");
  const light = data.perceptions.find((p) => p.type === "light_level");
  const sound = data.perceptions.find((p) => p.type === "sound");
  const ev = data.last_event_seconds_ago;

  return (
    <div style={{ padding: "12px 16px" }}>
      <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>Sensing</h3>

      {/* DL Backend connections */}
      <div style={S.card}>
        <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>DL Backend</div>
        <div style={S.row}>
          {data.perceptions.filter((p) => p.connected !== undefined).map((p) => (
            <div key={p.type}>
              <span style={S.badge(p.connected ?? false)}>{p.type}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Last events */}
      <div style={S.card}>
        <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>Last Events</div>
        <div style={S.row}>
          {Object.entries(ev).map(([type, sec]) => (
            <div key={type} style={{ minWidth: 100 }}>
              <div style={S.label}>{type}</div>
              <div style={S.value}>{fmtAgo(sec)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Motion */}
      {motion && (
        <div style={S.card}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>Motion</div>
          <div style={S.row}>
            <div>
              <div style={S.label}>Last Actions</div>
              <div style={S.value}>{motion.last_raw_actions?.length ? motion.last_raw_actions.join(", ") : "—"}</div>
            </div>
            <div>
              <div style={S.label}>User</div>
              <div style={S.value}>{motion.last_user || "unknown"}</div>
            </div>
            <div>
              <div style={S.label}>Since Motion</div>
              <div style={S.value}>{fmtAgo(motion.seconds_since_motion)}</div>
            </div>
            <div>
              <div style={S.label}>Buffered Snapshots</div>
              <div style={S.value}>{motion.buffered_snapshots ?? 0}</div>
            </div>
          </div>
        </div>
      )}

      {/* Emotion */}
      {emotion && (
        <div style={S.card}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>Emotion</div>
          <div style={S.row}>
            <div>
              <div style={S.label}>Last Sent</div>
              <div style={{ ...S.value, fontSize: 16 }}>{emotion.last_sent_emotion ?? "—"}</div>
            </div>
            <div>
              <div style={S.label}>User</div>
              <div style={S.value}>{emotion.last_sent_user || "unknown"}</div>
            </div>
            <div>
              <div style={S.label}>Detecting</div>
              <div style={S.value}>{emotion.last_detected_emotion ?? "—"}</div>
            </div>
            <div>
              <div style={S.label}>Since Detection</div>
              <div style={S.value}>{fmtAgo(emotion.seconds_since_detection)}</div>
            </div>
            <div>
              <div style={S.label}>Buffered</div>
              <div style={S.value}>{emotion.buffered_emotions ?? 0}</div>
            </div>
          </div>
        </div>
      )}

      {/* Face */}
      {face && (
        <div style={S.card}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>Face Recognition</div>
          <div style={S.row}>
            <div>
              <div style={S.label}>Visible Now</div>
              <div style={S.value}>{face.visible?.length ? face.visible.join(", ") : "nobody"}</div>
            </div>
            <div>
              <div style={S.label}>Last Person</div>
              <div style={S.value}>{face.last_person ?? "—"}</div>
            </div>
            <div>
              <div style={S.label}>Last Seen</div>
              <div style={S.value}>{fmtAgo(face.last_seen_seconds_ago)}</div>
            </div>
            <div>
              <div style={S.label}>Enrolled</div>
              <div style={S.value}>{face.enrolled_count ?? 0}</div>
            </div>
            <div>
              <div style={S.label}>Strangers</div>
              <div style={S.value}>{face.stranger_count ?? 0}</div>
            </div>
          </div>
        </div>
      )}

      {/* Presence + Light + Sound */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <div style={S.card}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>Presence</div>
          <div style={{ ...S.value, fontSize: 16, textTransform: "uppercase" as const }}>{data.presence.state}</div>
          <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginTop: 4 }}>
            idle: {data.presence.idle_timeout}s · away: {data.presence.away_timeout}s
          </div>
        </div>

        {light && (
          <div style={S.card}>
            <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>Light Level</div>
            <div style={S.value}>{Math.round(light.level ?? 0)}</div>
            <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginTop: 4 }}>
              checked {fmtAgo(light.seconds_since_check)}
            </div>
          </div>
        )}

        {sound && (
          <div style={S.card}>
            <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>Sound</div>
            <div style={S.value}>occurrences: {sound.occurrence_count ?? 0}</div>
            <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginTop: 4 }}>
              echo suppression: {sound.echo_suppression ? "on" : "off"}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
