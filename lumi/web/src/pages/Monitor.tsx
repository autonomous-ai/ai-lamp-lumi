import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from "chart.js";
import { Bar, Line } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, BarElement, PointElement, LineElement, Title, Tooltip, Legend, Filler);

const API = "/api";
const HW  = "/hw";
const HISTORY_LEN = 60;
const FLOW_EVENTS_MAX = 500;

// ─── Types ──────────────────────────────────────────────────────────────────

interface SystemInfo {
  cpuLoad: number;
  memTotal: number;
  memUsed: number;
  memPercent: number;
  cpuTemp: number;
  uptime: number;
  goRoutines: number;
  version: string;
  deviceId: string;
  diskTotal: number;
  diskUsed: number;
  diskPercent: number;
}
interface NetworkInfo {
  ssid: string;
  ip: string;
  signal: number;
  internet: boolean;
}
interface HWHealth {
  status: string;
  servo: boolean;
  led: boolean;
  camera: boolean;
  audio: boolean;
  sensing: boolean;
  voice: boolean;
  tts: boolean;
  display: boolean;
}
interface OCStatus {
  name: string;
  connected: boolean;
  sessionKey: boolean;
}
interface PresenceInfo {
  state: string;
  enabled: boolean;
  seconds_since_motion: number;
}
interface VoiceStatus {
  voice_available: boolean;
  voice_listening: boolean;
  tts_available: boolean;
  tts_speaking: boolean;
}
interface ServoState {
  available_recordings: string[];
  current: string | null;
  bus_connected?: boolean;
  robot_connected?: boolean;
}
interface DisplayState {
  mode: string;
  hardware: boolean;
  available_expressions: string[];
}
interface AudioVolume {
  control: string;
  volume: number;
}
interface LEDColor {
  led_count: number;
  color: [number, number, number];
  hex: string;
}
interface SceneInfo {
  scenes: string[];
  active?: string;
}
interface MonitorEvent {
  id: string;
  time: string;
  type: string;
  summary: string;
  detail?: Record<string, string> | null;
  runId?: string;
  phase?: string;
  state?: string;
  error?: string;
}
// UI-augmented version with local seq id
interface DisplayEvent extends MonitorEvent {
  _seq: number;
}

type Section = "overview" | "system" | "flow" | "camera" | "analytics" | "logs";

const NAV: { id: Section; label: string; icon: string }[] = [
  { id: "overview",   label: "Overview",   icon: "◈" },
  { id: "system",     label: "System",     icon: "⬡" },
  { id: "flow",       label: "Flow",       icon: "⬢" },
  { id: "camera",     label: "Camera",     icon: "⬟" },
  { id: "analytics",  label: "Analytics",  icon: "◉" },
  { id: "logs",       label: "Logs",       icon: "☰" },
];

// ─── CSS-in-JS helpers ───────────────────────────────────────────────────────

const S = {
  root: {
    display: "flex",
    height: "100vh",
    background: "var(--lm-bg)",
    color: "var(--lm-text)",
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
    fontSize: 13,
  } as React.CSSProperties,
  sidebar: {
    width: 192,
    flexShrink: 0,
    background: "var(--lm-sidebar)",
    borderRight: "1px solid var(--lm-border)",
    display: "flex",
    flexDirection: "column" as const,
  },
  sidebarLogo: {
    padding: "18px 16px 14px",
    borderBottom: "1px solid var(--lm-border)",
  },
  sidebarLogoName: {
    fontSize: 15,
    fontWeight: 700,
    color: "var(--lm-amber)",
    letterSpacing: "-0.3px",
  },
  sidebarLogoSub: {
    fontSize: 10,
    color: "var(--lm-text-muted)",
    marginTop: 2,
  },
  navItem: (active: boolean): React.CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: 9,
    padding: "8px 14px",
    borderRadius: 8,
    margin: "2px 8px",
    fontSize: 12.5,
    fontWeight: active ? 600 : 400,
    color: active ? "var(--lm-amber)" : "var(--lm-text-dim)",
    background: active ? "var(--lm-amber-dim)" : "transparent",
    cursor: "pointer",
    transition: "all 0.15s",
    border: "none",
    width: "calc(100% - 16px)",
    textAlign: "left" as const,
  }),
  main: {
    flex: 1,
    minWidth: 0,
    display: "flex",
    flexDirection: "column" as const,
    overflow: "hidden",
  },
  topbar: {
    padding: "10px 20px",
    borderBottom: "1px solid var(--lm-border)",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexShrink: 0,
  },
  content: {
    flex: 1,
    minHeight: 0,
    overflowY: "auto" as const,
    padding: "20px",
  },
  grid2: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 14,
  },
  grid3: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr 1fr",
    gap: 14,
  },
  card: {
    background: "var(--lm-card)",
    border: "1px solid var(--lm-border)",
    borderRadius: 12,
    padding: 16,
  },
  cardLabel: {
    fontSize: 10,
    fontWeight: 600,
    color: "var(--lm-text-muted)",
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
    marginBottom: 12,
  },
};

// ─── Utility components ──────────────────────────────────────────────────────

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: 7,
        height: 7,
        borderRadius: "50%",
        background: ok ? "var(--lm-green)" : "var(--lm-red)",
        boxShadow: ok ? "0 0 6px var(--lm-green)" : "none",
        flexShrink: 0,
      }}
    />
  );
}

function HWBadge({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 10px",
        borderRadius: 8,
        background: ok ? "rgba(52,211,153,0.08)" : "rgba(248,113,113,0.08)",
        border: `1px solid ${ok ? "rgba(52,211,153,0.25)" : "rgba(248,113,113,0.2)"}`,
        fontSize: 11.5,
        fontWeight: 500,
        color: ok ? "var(--lm-green)" : "var(--lm-red)",
      }}
    >
      <StatusDot ok={ok} />
      {label}
    </div>
  );
}

function GaugeRing({
  value,
  label,
  detail,
  color = "var(--lm-amber)",
  size = 110,
}: {
  value: number;
  label: string;
  detail?: string;
  color?: string;
  size?: number;
}) {
  const r = (size - 18) / 2;
  const circ = 2 * Math.PI * r;
  const filled = (Math.min(100, Math.max(0, value)) / 100) * circ;
  const glowId = `glow-${label.replace(/\s/g, "")}`;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
      <svg width={size} height={size} style={{ overflow: "visible" }}>
        <defs>
          <filter id={glowId} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {/* Track */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke="var(--lm-border)"
          strokeWidth={8}
        />
        {/* Filled arc */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke={color}
          strokeWidth={8}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circ}`}
          strokeDashoffset={0}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ filter: `url(#${glowId})`, transition: "stroke-dasharray 0.7s ease" }}
        />
        {/* Center value */}
        <text
          x={size / 2} y={size / 2 - 4}
          textAnchor="middle"
          dominantBaseline="middle"
          fill={color}
          fontSize={size * 0.18}
          fontWeight={700}
        >
          {Math.round(value)}%
        </text>
        {detail && (
          <text
            x={size / 2} y={size / 2 + size * 0.15}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="var(--lm-text-muted)"
            fontSize={size * 0.1}
          >
            {detail}
          </text>
        )}
      </svg>
      <span style={{ fontSize: 11, color: "var(--lm-text-dim)", fontWeight: 500 }}>{label}</span>
    </div>
  );
}

function Sparkline({
  data,
  color = "var(--lm-amber)",
  height = 44,
}: {
  data: number[];
  color?: string;
  height?: number;
}) {
  if (data.length < 2) return <div style={{ height }} />;
  const w = 280;
  const h = height;
  const max = Math.max(...data, 1);
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (v / max) * (h - 4) - 2;
    return `${x},${y}`;
  });
  const areaPath =
    `M 0,${h} ` +
    pts.join(" L ") +
    ` L ${w},${h} Z`;

  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id={`sg-${color.replace(/[^a-z]/gi, "")}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.25} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#sg-${color.replace(/[^a-z]/gi, "")})`} />
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SignalBars({ value }: { value: number }) {
  const bars = 4;
  const active = value >= -50 ? 4 : value >= -65 ? 3 : value >= -75 ? 2 : value >= -85 ? 1 : 0;
  return (
    <div style={{ display: "flex", gap: 2, alignItems: "flex-end" }}>
      {Array.from({ length: bars }).map((_, i) => (
        <div
          key={i}
          style={{
            width: 4,
            height: 6 + i * 3,
            borderRadius: 1,
            background: i < active ? "var(--lm-amber)" : "var(--lm-border-hi)",
          }}
        />
      ))}
    </div>
  );
}

function StatPill({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "6px 12px",
      background: "var(--lm-surface)",
      borderRadius: 8,
      border: "1px solid var(--lm-border)",
    }}>
      <span style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color: color || "var(--lm-text)" }}>{value}</span>
    </div>
  );
}

function formatUptime(s: number) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

// ─── Sections ────────────────────────────────────────────────────────────────

function OverviewSection({
  sys,
  net,
  hw,
  oc,
  presence,
  voice,
  servo,
  displayState,
  audio,
  ledColor,
  sceneInfo,
  onSceneActivate,
}: {
  sys: SystemInfo | null;
  net: NetworkInfo | null;
  hw: HWHealth | null;
  oc: OCStatus | null;
  presence: PresenceInfo | null;
  voice: VoiceStatus | null;
  servo: ServoState | null;
  displayState: DisplayState | null;
  audio: AudioVolume | null;
  ledColor: LEDColor | null;
  sceneInfo: SceneInfo | null;
  onSceneActivate: (scene: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Top row: 4 status cards */}
      <div style={S.grid2}>
        {/* OpenClaw */}
        <div style={S.card}>
          <div style={S.cardLabel}>OpenClaw AI</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <StatusDot ok={oc?.connected ?? false} />
            <span style={{ fontSize: 13, fontWeight: 600, color: oc?.connected ? "var(--lm-green)" : "var(--lm-red)" }}>
              {oc?.connected ? "Connected" : "Disconnected"}
            </span>
          </div>
          {oc && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Agent: <span style={{ color: "var(--lm-text)" }}>{oc.name}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Session key:
                <span style={{
                  fontSize: 10, padding: "1px 6px", borderRadius: 4,
                  background: oc.sessionKey ? "rgba(52,211,153,0.1)" : "rgba(80,74,60,0.4)",
                  color: oc.sessionKey ? "var(--lm-green)" : "var(--lm-text-muted)",
                  border: `1px solid ${oc.sessionKey ? "rgba(52,211,153,0.3)" : "var(--lm-border)"}`,
                  fontWeight: 600,
                }}>
                  {oc.sessionKey ? "Acquired" : "Pending"}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Network */}
        <div style={S.card}>
          <div style={S.cardLabel}>Network</div>
          {net ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <StatusDot ok={net.internet} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--lm-text)" }}>{net.ssid || "—"}</span>
                </div>
                <SignalBars value={net.signal} />
              </div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>IP: <span style={{ color: "var(--lm-teal)" }}>{net.ip}</span></div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>Signal: <span style={{ color: "var(--lm-text)" }}>{net.signal} dBm</span></div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Internet: <span style={{ color: net.internet ? "var(--lm-green)" : "var(--lm-red)" }}>{net.internet ? "OK" : "No"}</span>
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        {/* Presence */}
        <div style={S.card}>
          <div style={S.cardLabel}>Presence</div>
          {presence ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <StatusDot ok={presence.state === "active"} />
                <span style={{ fontSize: 14, fontWeight: 700, color: presence.state === "active" ? "var(--lm-amber)" : "var(--lm-text-dim)" }}>
                  {presence.state}
                </span>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Sensing: <span style={{ color: presence.enabled ? "var(--lm-green)" : "var(--lm-red)" }}>{presence.enabled ? "Enabled" : "Disabled"}</span>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Last motion: <span style={{ color: "var(--lm-text)" }}>{presence.seconds_since_motion}s ago</span>
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        {/* Voice */}
        <div style={S.card}>
          <div style={S.cardLabel}>Voice & TTS</div>
          {voice ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={voice.voice_available} />
                <span style={{ fontSize: 12, fontWeight: 600 }}>Mic</span>
                {voice.voice_listening && (
                  <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--lm-amber-dim)", color: "var(--lm-amber)" }}>LIVE</span>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={voice.tts_available} />
                <span style={{ fontSize: 12, fontWeight: 600 }}>TTS</span>
                {voice.tts_speaking && (
                  <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "rgba(167,139,250,0.15)", color: "var(--lm-purple)" }}>SPEAKING</span>
                )}
              </div>
              <div style={{ marginTop: 4, fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Volume: <span style={{ color: "var(--lm-amber)" }}>{audio?.volume ?? "—"}%</span>
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>
      </div>

      {/* Hardware status */}
      <div style={S.card}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <div style={S.cardLabel}>Hardware</div>
          {/* LED color swatch */}
          {ledColor && (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>LED color</span>
              <div style={{
                width: 22, height: 22, borderRadius: 6,
                background: ledColor.hex,
                boxShadow: `0 0 8px ${ledColor.hex}99`,
                border: "1px solid rgba(255,255,255,0.1)",
                flexShrink: 0,
              }} title={`RGB(${ledColor.color.join(", ")})`} />
              <span style={{
                fontSize: 11, fontFamily: "monospace",
                color: "var(--lm-text-dim)",
              }}>{ledColor.hex}</span>
            </div>
          )}
        </div>
        {hw ? (
          <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 8 }}>
            <HWBadge label="Servo" ok={hw.servo} />
            <HWBadge label="LED" ok={hw.led} />
            <HWBadge label="Camera" ok={hw.camera} />
            <HWBadge label="Audio" ok={hw.audio} />
            <HWBadge label="Sensing" ok={hw.sensing} />
            <HWBadge label="Voice" ok={hw.voice} />
            <HWBadge label="TTS" ok={hw.tts} />
            <HWBadge label="Display" ok={hw.display} />
          </div>
        ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
      </div>

      {/* Scene presets */}
      <div style={S.card}>
        <div style={S.cardLabel}>Scene</div>
        {sceneInfo ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
              {sceneInfo.scenes.length} presets available
            </div>
            <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 6, marginTop: 2 }}>
              {sceneInfo.scenes.map((s) => (
                <span key={s} role="button" onClick={() => onSceneActivate(s)} style={{
                  fontSize: 11,
                  padding: "4px 10px",
                  borderRadius: 6,
                  background: s === sceneInfo.active ? "var(--lm-amber-dim)" : "var(--lm-surface)",
                  border: `1px solid ${s === sceneInfo.active ? "var(--lm-amber)" : "var(--lm-border)"}`,
                  color: s === sceneInfo.active ? "var(--lm-amber)" : "var(--lm-text-dim)",
                  cursor: "pointer",
                  fontWeight: s === sceneInfo.active ? 600 : 400,
                  textTransform: "capitalize",
                }}>{s}</span>
              ))}
            </div>
          </div>
        ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
      </div>

      {/* Servo + Display row */}
      <div style={S.grid2}>
        <div style={S.card}>
          <div style={S.cardLabel}>Servo Pose</div>
          {servo ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--lm-amber)" }}>
                {servo.current || "idle"}
              </div>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                {servo.available_recordings?.length ?? 0} poses available
                {servo.bus_connected === false || servo.robot_connected === false ? (
                  <span style={{ color: "var(--lm-danger, #c44)", marginLeft: 6 }}>
                    (bus {servo.bus_connected === false ? "down" : "ok"}
                    {servo.robot_connected === false ? ", robot disconnected" : ""})
                  </span>
                ) : null}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4, marginTop: 4 }}>
                {(servo.available_recordings ?? []).map((p) => (
                  <span key={p} role="button" onClick={() => {
                    fetch(`${HW}/servo/play`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ recording: p }),
                    }).catch(() => {});
                  }} style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: p === servo.current ? "var(--lm-amber-dim)" : "var(--lm-surface)",
                    border: `1px solid ${p === servo.current ? "var(--lm-amber)" : "var(--lm-border)"}`,
                    color: p === servo.current ? "var(--lm-amber)" : "var(--lm-text-dim)",
                    cursor: "pointer",
                  }}>{p}</span>
                ))}
              </div>
              <button onClick={() => {
                fetch(`${HW}/servo/release`, {
                  method: "POST",
                  headers: { accept: "application/json" },
                }).catch(() => {});
              }} style={{
                marginTop: 4,
                fontSize: 10,
                padding: "3px 10px",
                borderRadius: 4,
                background: "var(--lm-surface)",
                border: "1px solid var(--lm-border)",
                color: "var(--lm-text-dim)",
                cursor: "pointer",
              }}>Release</button>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        <div style={S.card}>
          <div style={S.cardLabel}>Display Eyes</div>
          {displayState ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={displayState.hardware} />
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--lm-teal)" }}>
                  {displayState.mode}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                {displayState.available_expressions?.length ?? 0} expressions
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4, marginTop: 4 }}>
                {(displayState.available_expressions ?? []).map((e) => (
                  <span key={e} style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: e === displayState.mode ? "rgba(45,212,191,0.12)" : "var(--lm-surface)",
                    border: `1px solid ${e === displayState.mode ? "rgba(45,212,191,0.4)" : "var(--lm-border)"}`,
                    color: e === displayState.mode ? "var(--lm-teal)" : "var(--lm-text-dim)",
                  }}>{e}</span>
                ))}
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>
      </div>

      {/* System quick stats */}
      {sys && (
        <div style={S.card}>
          <div style={S.cardLabel}>System</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
            <StatPill label="CPU" value={`${sys.cpuLoad.toFixed(1)}%`} color="var(--lm-amber)" />
            <StatPill label="RAM" value={`${sys.memPercent.toFixed(0)}%`} color="var(--lm-blue)" />
            <StatPill label="Disk" value={`${(sys.diskPercent ?? 0).toFixed(0)}%`} color={(sys.diskPercent ?? 0) > 90 ? "var(--lm-red)" : "var(--lm-teal)"} />
            <StatPill label="Temp" value={`${sys.cpuTemp.toFixed(1)}°C`} color={sys.cpuTemp > 70 ? "var(--lm-red)" : "var(--lm-teal)"} />
            <StatPill label="Uptime" value={formatUptime(sys.uptime)} />
          </div>
        </div>
      )}
    </div>
  );
}

function SystemSection({
  sys,
  net,
  cpuHistory,
  ramHistory,
}: {
  sys: SystemInfo | null;
  net: NetworkInfo | null;
  cpuHistory: number[];
  ramHistory: number[];
}) {
  if (!sys) return <div style={{ color: "var(--lm-text-muted)", padding: 20 }}>Loading system data…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* 3 Gauge rings */}
      <div style={S.card}>
        <div style={S.cardLabel}>Performance</div>
        <div style={{ display: "flex", justifyContent: "space-around", paddingTop: 8 }}>
          <GaugeRing value={sys.cpuLoad} label="CPU" detail={`${sys.cpuLoad.toFixed(1)}%`} color="var(--lm-amber)" size={110} />
          <GaugeRing value={sys.memPercent} label="Memory" detail={`${Math.round(sys.memUsed/1024)}/${Math.round(sys.memTotal/1024)} MB`} color="var(--lm-blue)" size={110} />
          <GaugeRing value={sys.diskPercent ?? 0} label="Disk" detail={`${Math.round((sys.diskUsed ?? 0)/1024)}/${Math.round((sys.diskTotal ?? 0)/1024)} GB`} color={(sys.diskPercent ?? 0) > 90 ? "var(--lm-red)" : "var(--lm-teal)"} size={110} />
          <GaugeRing
            value={sys.cpuTemp > 0 ? Math.min(100, (sys.cpuTemp / 85) * 100) : 0}
            label="Temp"
            detail={`${sys.cpuTemp.toFixed(1)}°C`}
            color={sys.cpuTemp > 70 ? "var(--lm-red)" : "var(--lm-teal)"}
            size={110}
          />
        </div>
      </div>

      {/* Sparklines */}
      <div style={S.grid2}>
        <div style={S.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <div style={S.cardLabel}>CPU History</div>
            <span style={{ fontSize: 11, color: "var(--lm-amber)", fontWeight: 600 }}>{sys.cpuLoad.toFixed(1)}%</span>
          </div>
          <Sparkline data={cpuHistory} color="var(--lm-amber)" height={52} />
        </div>
        <div style={S.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <div style={S.cardLabel}>RAM History</div>
            <span style={{ fontSize: 11, color: "var(--lm-blue)", fontWeight: 600 }}>{sys.memPercent.toFixed(0)}%</span>
          </div>
          <Sparkline data={ramHistory} color="var(--lm-blue)" height={52} />
        </div>
      </div>

      {/* Detail stats */}
      <div style={S.grid2}>
        <div style={S.card}>
          <div style={S.cardLabel}>Process</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <StatPill label="Go Routines" value={sys.goRoutines} color="var(--lm-teal)" />
            <StatPill label="Uptime" value={formatUptime(sys.uptime)} />
            <StatPill label="Version" value={sys.version || "—"} />
            <StatPill label="Device ID" value={sys.deviceId ? sys.deviceId.slice(0, 12) + "…" : "—"} />
          </div>
        </div>

        <div style={S.card}>
          <div style={S.cardLabel}>Network Detail</div>
          {net ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <StatPill label="SSID" value={net.ssid || "—"} color="var(--lm-amber)" />
              <StatPill label="IP" value={net.ip} color="var(--lm-teal)" />
              <StatPill label="Signal" value={`${net.signal} dBm`} />
              <StatPill label="Internet" value={net.internet ? "OK" : "No"} color={net.internet ? "var(--lm-green)" : "var(--lm-red)"} />
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>No network data</span>}
        </div>
      </div>
    </div>
  );
}

// ─── Flow Panel ──────────────────────────────────────────────────────────────

// Maps a MonitorEvent type/node to a flow stage ID
type FlowStage =
  | "sensing" | "telegram_input" | "intent_check" | "local_match"
  | "agent_call" | "agent_thinking" | "tool_exec" | "agent_response" | "tts_speak"
  | "schedule_trigger";

/** No pipeline node highlighted — e.g. no matching triggers in recent events */
type ActiveFlowStage = FlowStage | "idle";

interface FlowNodeDef {
  id: FlowStage;
  label: string;
  short: string;
  icon: string;
  color: string;
  desc: string; // short description shown inside node on zoom
  // event types or flow nodes that activate this stage
  triggers: string[];
  path: "main" | "fast" | "agent";
}

const FLOW_NODES: FlowNodeDef[] = [
  { id: "sensing",
    label: "Sensing", short: "SENSE", icon: "📡", color: "var(--lm-amber)", path: "main",
    desc: "POST /sensing/event · voice / motion / sound",
    triggers: [
      "sensing_input",
      "flow_enter:sensing_input", "flow_exit:sensing_input", "flow_event:sensing_input",
      "flow_enter:voice_pipeline_start", "flow_event:voice_pipeline_start",
    ] },

  { id: "telegram_input",
    label: "Telegram In", short: "TG IN", icon: "💬", color: "#229ed9", path: "main",
    desc: "Inbound message via Telegram / Slack / Discord",
    triggers: [
      "chat_input",
      "flow_event:chat_input",
    ] },

  { id: "intent_check",
    label: "Intent Check", short: "INTENT", icon: "🔀", color: "var(--lm-teal)", path: "main",
    desc: "Route to local match or agent call",
    triggers: [
      "chat_send",
      "flow_event:chat_send", "flow_enter:chat_send", "flow_exit:chat_send",
      "flow_event:agent_call",
    ] },

  { id: "local_match",
    label: "Local Intent", short: "LOCAL", icon: "⚡", color: "var(--lm-green)", path: "fast",
    desc: "Fast path ~50ms · regex match → instant TTS · bypasses agent",
    triggers: [
      "intent_match",
      "flow_event:intent_match", "flow_enter:intent_match", "flow_exit:intent_match",
    ] },

  { id: "agent_call",
    label: "Agent Call", short: "AGENT", icon: "🤖", color: "var(--lm-blue)", path: "agent",
    desc: "WebSocket chat.send RPC to OpenClaw",
    triggers: [
      "flow_event:agent_call", "flow_enter:agent_call", "flow_exit:agent_call",
      "flow_event:lifecycle_start",
    ] },

  { id: "agent_thinking",
    label: "Thinking", short: "THINK", icon: "🧠", color: "var(--lm-purple)", path: "agent",
    desc: "LLM reasoning · streaming thinking tokens",
    triggers: [
      "thinking",
      "flow_event:lifecycle_start",
    ] },

  { id: "tool_exec",
    label: "Tool Exec", short: "TOOL", icon: "🔧", color: "#f59e0b", path: "agent",
    desc: "Agent invoked a tool · function call",
    triggers: [
      "tool_call",
      "flow_event:tool_call", "flow_enter:tool_call", "flow_exit:tool_call",
    ] },

  { id: "agent_response",
    label: "Response", short: "RESP", icon: "💡", color: "var(--lm-green)", path: "agent",
    desc: "Agent turn ended · response accumulated",
    triggers: [
      "chat_response",
      "flow_event:lifecycle_end",
    ] },

  { id: "tts_speak",
    label: "TTS / Action", short: "TTS", icon: "🔊", color: "var(--lm-purple)", path: "agent",
    desc: "POST /voice/speak · LED · Display",
    triggers: [
      "tts",
      "flow_event:tts_send", "flow_enter:tts_send", "flow_exit:tts_send",
      "intent_match", "flow_event:intent_match",
      "flow_event:voice_pipeline_start",
    ] },

  { id: "schedule_trigger",
    label: "Schedule", short: "CRON", icon: "⏰", color: "#f97316", path: "main",
    desc: "Cron/timer fired · agent turn triggered by schedule",
    triggers: [
      "schedule_trigger", "flow_event:schedule_trigger",
      "flow_enter:schedule_trigger", "flow_exit:schedule_trigger",
      "flow_event:cron_fire", "cron_fire",
    ] },
];

// Derive active stage from most recent relevant events
function deriveActiveStage(events: DisplayEvent[]): ActiveFlowStage {
  const recent = events.slice(-30);
  for (let i = recent.length - 1; i >= 0; i--) {
    const ev = recent[i];
    const key = ev.type === "flow_event" && ev.detail?.node
      ? `flow_event:${ev.detail.node}`
      : ev.type === "flow_enter" && ev.detail?.node
      ? `flow_enter:${ev.detail.node}`
      : ev.type === "flow_exit" && ev.detail?.node
      ? `flow_exit:${ev.detail.node}`
      : ev.type;
    for (const node of [...FLOW_NODES].reverse()) {
      if (node.triggers.includes(key)) return node.id;
    }
  }
  return "idle";
}

// Group events into turns by runId (a new turn starts on each sensing_input)
interface Turn {
  id: string;          // runId or a synthetic id for local turns
  runId?: string;
  startTime: string;
  sessionBreak?: boolean; // true if this turn starts after a BE restart (new session)
  endTime?: string;
  type: string;        // "voice", "motion", etc.
  path: "local" | "agent" | "unknown";
  status: "active" | "done" | "error";
  events: DisplayEvent[];
}

function extractEventRunId(ev: DisplayEvent): string | undefined {
  if (ev.runId) return ev.runId;
  const detail = ev.detail as Record<string, any> | undefined;
  return detail?.run_id ?? detail?.runId ?? detail?.data?.run_id ?? detail?.data?.runId;
}

function parseTelegramSummary(summary: string): string {
  const m = summary.match(/^\[telegram\]\s*(.*)/i);
  if (!m) return summary.trim();
  return (m[1] ?? "").trim();
}

const TELEGRAM_FALLBACK_MESSAGE = "Message from telegram";
const TURN_INPUT_FALLBACK = "Input not captured";

function turnHasOutput(turn: Turn): boolean {
  return turn.events.some((ev) =>
    ev.type === "tts" ||
    ev.type === "intent_match" ||
    (ev.type === "flow_event" && (ev.detail?.node === "tts_send" || ev.detail?.node === "intent_match")),
  );
}

function turnHasRealTelegramInput(turn: Turn): boolean {
  return turn.events.some((ev) => {
    if (ev.type !== "chat_input") return false;
    const msg = parseTelegramSummary(ev.summary);
    return msg.length > 0;
  });
}

function turnHasSensingInput(turn: Turn): boolean {
  return turn.events.some((ev) =>
    ev.type === "sensing_input" ||
    (ev.type === "flow_enter" && ev.detail?.node === "sensing_input"),
  );
}

/** Bracket label from "[voice] hello" / "[motion] ..." on sensing_input / flow_enter sensing_input. */
function sensingInputBracketType(ev: DisplayEvent): string | null {
  if (ev.type !== "sensing_input" && !(ev.type === "flow_enter" && ev.detail?.node === "sensing_input")) {
    return null;
  }
  const m = ev.summary.match(/^\[([^\]]+)\]/);
  return m ? m[1] : null;
}

/**
 * Same run_id can include motion (camera) then voice in one session; merge keeps the first segment's type (often "motion").
 * For the turn badge, prefer voice / voice_command when any utterance is present — that is the user's intent.
 */
function refineTurnTypeFromSensingInputs(turn: Turn): void {
  if (turn.type === "telegram" || turn.type.startsWith("ambient:") || turn.type === "schedule") {
    return;
  }
  let sawVoice = false;
  let sawVoiceCommand = false;
  for (const ev of turn.events) {
    const t = sensingInputBracketType(ev);
    if (t === "voice_command") sawVoiceCommand = true;
    else if (t === "voice") sawVoice = true;
  }
  if (sawVoiceCommand) turn.type = "voice_command";
  else if (sawVoice) turn.type = "voice";
}

function groupIntoTurns(events: DisplayEvent[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;

  // Check if event starts a new turn
  function isTurnStart(ev: DisplayEvent): { type: string; path: Turn["path"] } | null {
    if (ev.type === "sensing_input" || (ev.type === "flow_enter" && ev.detail?.node === "sensing_input")) {
      const m = ev.summary.match(/^\[([^\]]+)\]/);
      return { type: m ? m[1] : "unknown", path: "unknown" };
    }
    if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
      return { type: "telegram", path: "agent" };
    }
    // Ambient actions (breathing, movement, mumble) start their own turn
    // BUT ambient_pause/ambient_resume are infra signals, NOT turns
    const ambientNode = ev.detail?.node ?? "";
    const isAmbientTurn = ev.type === "ambient_action" ||
      ((ev.type === "flow_event" || ev.type === "flow_enter") &&
       ambientNode.startsWith("ambient_") &&
       ambientNode !== "ambient_pause" && ambientNode !== "ambient_resume");
    if (isAmbientTurn) {
      const sub = ambientNode.replace("ambient_", "") || "idle";
      return { type: `ambient:${sub}`, path: "local" };
    }
    // Schedule/cron triggers start a turn
    if (ev.type === "schedule_trigger" || ev.type === "cron_fire" ||
        (ev.type === "flow_event" && (ev.detail?.node === "schedule_trigger" || ev.detail?.node === "cron_fire"))) {
      return { type: "schedule", path: "agent" };
    }
    return null;
  }

  for (const ev of events) {
    const evRunId = extractEventRunId(ev);
    const start = isTurnStart(ev);
    if (start) {
      // If this start marker belongs to the same run, keep a single turn.
      if (current && current.runId && evRunId && current.runId === evRunId) {
        current.events.push(ev);
        continue;
      }
      if (current) turns.push(current);
      current = {
        id: evRunId || `turn-${ev._seq}`,
        runId: evRunId,
        startTime: ev.time,
        type: start.type,
        path: start.path,
        status: "active",
        events: [ev],
      };
      continue;
    }

    // If event belongs to a different run_id, split into a new inferred turn
    // to avoid mixing input/output across runs in UI.
    if (current && current.runId && evRunId && current.runId !== evRunId) {
      const inferredType: Turn["type"] = current.type !== "unknown" ? current.type : "agent";
      const inferredPath: Turn["path"] = current.path !== "unknown" ? current.path : "agent";
      turns.push(current);
      current = {
        id: evRunId,
        runId: evRunId,
        startTime: ev.time,
        type: inferredType,
        path: inferredPath,
        status: "active",
        events: [ev],
      };
      continue;
    }

    if (!current) {
      // Orphan events before first turn start — skip
      continue;
    }
    current.events.push(ev);
    if (!current.runId && evRunId) {
      current.runId = evRunId;
      current.id = evRunId;
    }

    // Classify path — only from events that belong to this turn's run
    if (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match")) {
      current.path = "local";
    } else if (current.path !== "local") {
      const belongsToTurn = !current.runId || !evRunId || evRunId === current.runId;
      if (belongsToTurn && (evRunId || ev.type === "lifecycle" || ev.type === "thinking")) {
        current.path = "agent";
      }
    }

    // Detect turn end
    if (ev.type === "lifecycle" && ev.phase === "end") {
      current.status = ev.error ? "error" : "done";
      current.endTime = ev.time;
    }
    if (ev.type === "intent_match") {
      current.status = "done";
      current.endTime = ev.time;
    }
    if (ev.type === "flow_event" && ev.detail?.node === "tts_send") {
      current.status = "done";
      current.endTime = ev.time;
    }
    // Ambient actions are short-lived turns
    if (current.type.startsWith("ambient:") && ev.type === "flow_exit" && ev.detail?.node?.startsWith("ambient_")) {
      current.status = "done";
      current.endTime = ev.time;
    }
  }
  if (current) turns.push(current);

  // Merge fragmented segments that share the same run_id.
  // Some streams can emit start markers that temporarily split a run into multiple chunks.
  const merged: Turn[] = [];
  const runIndex = new Map<string, number>();
  for (const turn of turns) {
    if (!turn.runId) {
      merged.push(turn);
      continue;
    }
    const idx = runIndex.get(turn.runId);
    if (idx === undefined) {
      runIndex.set(turn.runId, merged.length);
      merged.push(turn);
      continue;
    }
    const base = merged[idx];
    base.events.push(...turn.events);
    if (base.status !== "error" && turn.status === "error") base.status = "error";
    else if (base.status === "active" && turn.status === "done") base.status = "done";
    if (!base.endTime && turn.endTime) base.endTime = turn.endTime;
    else if (base.endTime && turn.endTime && turn.endTime > base.endTime) base.endTime = turn.endTime;
    if (base.path !== "agent" && turn.path === "agent") base.path = "agent";
    if (base.type === "unknown" && turn.type !== "unknown") base.type = turn.type;
  }
  for (const turn of merged) {
    turn.events.sort((a, b) => a._seq - b._seq);
  }

  // Merge adjacent Telegram fallback + agent output fragments into one turn.
  // This handles cases where upstream emits separate run_ids for chat_input and response.
  const stitched: Turn[] = [];
  for (const turn of merged) {
    const prev = stitched[stitched.length - 1];
    if (!prev) {
      stitched.push(turn);
      continue;
    }
    const prevHasNoOutput = !turnHasOutput(prev);
    const currLooksAgentReply = turn.path === "agent" && turnHasOutput(turn);
    const prevTs = new Date(prev.endTime || prev.startTime).getTime();
    const currTs = new Date(turn.startTime).getTime();
    const closeInTime = Number.isFinite(prevTs) && Number.isFinite(currTs) && (currTs - prevTs) <= 30_000;

    // Case 1: Telegram fallback (no message) + agent output → merge
    const prevIsTelegramFallback = prev.type === "telegram" && !turnHasRealTelegramInput(prev);
    if (prevIsTelegramFallback && prevHasNoOutput && currLooksAgentReply && closeInTime) {
      prev.events.push(...turn.events);
      prev.events.sort((a, b) => a._seq - b._seq);
      prev.status = turn.status === "error" ? "error" : turn.status;
      prev.endTime = turn.endTime || prev.endTime;
      prev.path = "agent";
      continue;
    }

    // Case 2: Sensing input (no output) + orphan output-only turn → merge
    // Happens when server restart splits a sensing turn's input and output into separate turns.
    const prevIsSensingNoOutput = turnHasSensingInput(prev) && prevHasNoOutput;
    const currIsOrphanOutput = !turnHasSensingInput(turn) && !turnHasRealTelegramInput(turn) && turnHasOutput(turn);
    if (prevIsSensingNoOutput && currIsOrphanOutput && closeInTime) {
      prev.events.push(...turn.events);
      prev.events.sort((a, b) => a._seq - b._seq);
      prev.status = turn.status === "error" ? "error" : turn.status;
      prev.endTime = turn.endTime || prev.endTime;
      prev.path = "agent";
      continue;
    }

    stitched.push(turn);
  }

  for (const turn of stitched) {
    refineTurnTypeFromSensingInputs(turn);
  }

  // Detect session breaks: ws_connect after ws_disconnect gap or large time gap between turns
  for (let i = 1; i < stitched.length; i++) {
    const prev = stitched[i - 1];
    const curr = stitched[i];
    // Check if there's a ws_connect/ws_ready event between turns (BE restart)
    const prevEnd = new Date(prev.endTime || prev.startTime).getTime();
    const currStart = new Date(curr.startTime).getTime();
    // Session break if >60s gap between turns
    if (currStart - prevEnd > 60_000) {
      curr.sessionBreak = true;
    }
  }

  return stitched.slice(-100).reverse(); // latest 100, newest first
}

// Runtime detail lines; `ambient` is collected but not tied to an SVG node (no ambient stage)
type NodeInfoMap = Record<FlowStage, string[]> & { ambient: string[] };

// Extract runtime info for each node from turn events
function extractNodeInfo(events: DisplayEvent[]): NodeInfoMap {
  const info: NodeInfoMap = {
    sensing: [], telegram_input: [], intent_check: [], local_match: [],
    agent_call: [], agent_thinking: [], tool_exec: [],
    agent_response: [], tts_speak: [], schedule_trigger: [],
    ambient: [],
  };
  const fmtToken = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);
  const pushAgentResponse = (line: string) => {
    if (!line) return;
    if (!info.agent_response.includes(line)) info.agent_response.push(line);
  };

  for (const ev of events) {
    // sensing_input → sensing node
    if (ev.type === "sensing_input") {
      const m = ev.summary.match(/^\[([^\]]+)\]\s*(.*)/);
      if (m) info.sensing.push(`type: ${m[1]}`, `"${m[2]}"`);
      else info.sensing.push(ev.summary);
    }
    // ambient events → ambient node (skip pause/resume infra signals)
    {
      const aNode = ev.detail?.node ?? "";
      const isAmbientInfo = ev.type === "ambient_action" ||
        ((ev.type === "flow_event" || ev.type === "flow_enter" || ev.type === "flow_exit") &&
         aNode.startsWith("ambient_") && aNode !== "ambient_pause" && aNode !== "ambient_resume");
      if (isAmbientInfo) {
        const sub = aNode.replace("ambient_", "") || ev.summary || "";
        if (info.ambient.length < 3) info.ambient.push(`${sub}: ${ev.summary || "active"}`);
      }
    }
    // schedule events → schedule_trigger node
    if (ev.type === "schedule_trigger" || ev.type === "cron_fire" ||
        (ev.type === "flow_event" && (ev.detail?.node === "schedule_trigger" || ev.detail?.node === "cron_fire"))) {
      const d = ev.detail as Record<string, string> | undefined;
      info.schedule_trigger.push(d?.name ?? ev.summary ?? "cron fired");
    }
    // chat_input → telegram_input node
    if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
      const msg = parseTelegramSummary(ev.summary);
      info.telegram_input.push(`"${msg || TELEGRAM_FALLBACK_MESSAGE}"`);
    }
    // intent_match → local_match node
    if (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match")) {
      info.local_match.push(ev.summary);
    }
    // chat_send → intent_check / agent_call
    if (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send")) {
      info.intent_check.push("→ agent route");
      info.agent_call.push(`msg: "${ev.summary}"`);
    }
    // tool_call → tool_exec node — show tool name + args
    if (ev.type === "tool_call" || (ev.type === "flow_event" && ev.detail?.node === "tool_call")) {
      const d = ev.detail as Record<string, any> | undefined;
      const toolName = d?.tool ?? d?.data?.tool ?? "unknown";
      const args = d?.args ?? d?.data?.args ?? "";
      // Avoid duplicates
      const entry = `⚙ ${toolName}${args ? `(${args})` : ""}`;
      if (!info.tool_exec.includes(entry)) info.tool_exec.push(entry);
    }
    // thinking → agent_thinking node
    if (ev.type === "thinking" || (ev.type === "flow_event" && ev.detail?.node === "lifecycle_start")) {
      if (ev.type === "thinking" && ev.summary && info.agent_thinking.length < 2) {
        info.agent_thinking.push(`"${ev.summary}…"`);
      }
      // JSONL: lifecycle_start marks thinking began
      if (ev.type === "flow_event" && info.agent_thinking.length === 0) {
        info.agent_thinking.push("reasoning…");
      }
    }
    // chat_response / lifecycle_end → agent_response node
    if (ev.type === "chat_response" || (ev.type === "flow_event" && ev.detail?.node === "lifecycle_end")) {
      const d = ev.detail as Record<string, any> | undefined;
      if (d?.message && info.agent_response.length < 2) {
        info.agent_response.push(`"${d.message}…"`);
      }
      // JSONL: lifecycle_end has error in data
      const dataErr = d?.data?.error;
      if (dataErr && info.agent_response.length < 2) {
        info.agent_response.push(`❌ ${dataErr}`);
      }
    }
    // tts / tts_send → tts_speak node + output node
    if (ev.type === "tts" || (ev.type === "flow_event" && ev.detail?.node === "tts_send")) {
      const d = ev.detail as Record<string, any> | undefined;
      const text = d?.data?.text ?? d?.text ?? "";
      if (text && info.tts_speak.length < 2) {
        info.tts_speak.push(`🔊 "${text}"`);
      }
      // Also populate agent_response with the spoken text (more useful than lifecycle summary)
      if (text && info.agent_response.length < 2) {
        const preview = text.length > 80 ? text.slice(0, 80) + "…" : text;
        info.agent_response.push(`"${preview}"`);
      }
    }
    // lifecycle → idle / agent_call + token usage on agent_response
    // Monitor bus path
    if (ev.type === "lifecycle") {
      if (ev.phase === "start") info.agent_call.push(`run: ${ev.runId ?? "?"}`);
      if (ev.phase === "end") {
        pushAgentResponse(ev.error ? `❌ ${ev.error}` : "✓ done");
        const d = ev.detail as Record<string, string> | undefined;
        if (d?.inputTokens) {
          const inp = parseInt(d.inputTokens, 10);
          const out = parseInt(d.outputTokens ?? "0", 10);
          pushAgentResponse(`tokens: ${fmtToken(inp)} in / ${fmtToken(out)} out`);
        }
      }
    }
    // JSONL path: token_usage event has token counts
    if (ev.type === "flow_event" && ev.detail?.node === "token_usage") {
      const d = ev.detail as Record<string, any> | undefined;
      const u = d?.data;
      const inTok = Number(u?.input_tokens ?? 0);
      const outTok = Number(u?.output_tokens ?? 0);
      const cacheRead = Number(u?.cache_read_tokens ?? 0);
      const cacheWrite = Number(u?.cache_write_tokens ?? 0);
      const total = Number(u?.total_tokens ?? 0);
      if (inTok || outTok) pushAgentResponse(`tokens: ${fmtToken(inTok)} in / ${fmtToken(outTok)} out`);
      if (cacheRead || cacheWrite) pushAgentResponse(`cache: ${fmtToken(cacheRead)} read / ${fmtToken(cacheWrite)} write`);
      if (total) pushAgentResponse(`total: ${fmtToken(total)}`);
    }
    // JSONL path: lifecycle_end status
    if (ev.type === "flow_event" && ev.detail?.node === "lifecycle_end") {
      const d = ev.detail as Record<string, any> | undefined;
      const err = d?.data?.error;
      if (err) info.agent_response.push(`❌ ${err}`);
    }
    // tts_speak also captures intent_match and tool results (output merged into this node)
    if (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match")) {
      const d = ev.detail as Record<string, any> | undefined;
      const tts = d?.data?.tts ?? d?.tts ?? "";
      if (tts && info.tts_speak.length < 3) info.tts_speak.push(`💡 ${tts}`);
    }
  }
  return info;
}

// SVG Flow Diagram — renders the pipeline with zoom/pan, detailed node info
function FlowDiagram({
  activeStage,
  visitedStages,
  compact = false,
  turnEvents = [],
}: {
  activeStage: ActiveFlowStage;
  visitedStages: Set<FlowStage>;
  compact?: boolean;
  turnEvents?: DisplayEvent[];
}) {
  // viewBox dimensions (logical coordinate space)
  const VW = 920;
  const VH = 720;

  // Zoom / pan state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const svgRef = useRef<SVGSVGElement>(null);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    setZoom((z) => Math.min(4, Math.max(0.4, z + delta)));
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
  }, [pan]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    setPan({ x: dragStart.current.panX + dx / zoom, y: dragStart.current.panY + dy / zoom });
  }, [dragging, zoom]);

  const handleMouseUp = useCallback(() => setDragging(false), []);

  const resetView = useCallback(() => { setZoom(1); setPan({ x: 0, y: 0 }); }, []);

  // Compute viewBox from zoom + pan
  const vbW = VW / zoom;
  const vbH = VH / zoom;
  const vbX = (VW - vbW) / 2 - pan.x;
  const vbY = (VH - vbH) / 2 - pan.y;

  // Node positions — triangle: Lumi (top, spans full width), LeLamp (bottom-left), OpenClaw (bottom-right)
  // Nodes arranged so arrows flow cleanly: LeLamp ↗ Lumi ↘ OpenClaw → LeLamp (clockwise)
  // OpenClaw — 3-column grid (see docs/flow-monitor.md § OpenClaw layout rules):
  // Col1 Tool+Response | Col2 Agent+Thinking | Col3 TG In
  // Row1: Col2 Agent + Col3 TG In | Row2: Col1 Tool + Col2 Think | Row3: Col1 Response
  const positions: Record<FlowStage, { x: number; y: number }> = {
    // Lumi — top row: Intent, Local, Cron (Cron x aligns with OpenClaw Agent column — see flow-monitor.md)
    intent_check:      { x: 100, y: 100 },
    local_match:       { x: 240, y: 100 },
    schedule_trigger:  { x: 625, y: 100 },
    // LeLamp cluster (bottom-left) — same row y as OpenClaw Tool (tool_exec)
    sensing:           { x: 100, y: 480 },
    tts_speak:         { x: 240, y: 480 },
    // OpenClaw (x: col1≈500, col2≈625, col3≈775)
    agent_call:        { x: 625, y: 350 },
    telegram_input:    { x: 775, y: 350 },
    tool_exec:         { x: 500, y: 480 },
    agent_thinking:    { x: 625, y: 480 },
    agent_response:    { x: 500, y: 630 },
  };

  const edges: [FlowStage, FlowStage][] = [
    ["sensing",           "intent_check"],      // LeLamp → Lumi
    ["intent_check",      "local_match"],       // Lumi LOCAL path
    ["local_match",       "tts_speak"],         // Local match → LeLamp TTS directly
    ["intent_check",      "agent_call"],        // Lumi → OpenClaw
    ["telegram_input",    "agent_call"],         // Telegram plugin → OpenClaw agent
    ["schedule_trigger",  "agent_call"],         // Cron → OpenClaw
    ["agent_call",        "agent_thinking"],
    ["agent_thinking",    "tool_exec"],
    ["agent_thinking",    "agent_response"],
    ["tool_exec",         "agent_response"],
    ["tool_exec",         "tts_speak"],         // Tool exec → LeLamp (LED, etc.)
    ["agent_response",    "tts_speak"],         // Response → LeLamp TTS
  ];

  const nodeR = compact ? 28 : 38;

  function nodeColor(id: FlowStage) {
    if (id === activeStage) return FLOW_NODES.find((n) => n.id === id)?.color ?? "#fff";
    if (visitedStages.has(id)) return FLOW_NODES.find((n) => n.id === id)?.color ?? "#fff";
    return "var(--lm-text-muted)";
  }
  function nodeOpacity(id: FlowStage) {
    if (id === activeStage) return 1;
    if (visitedStages.has(id)) return 0.85;
    return 0.7;
  }
  function edgeColor(from: FlowStage, to: FlowStage) {
    const fromVisited = visitedStages.has(from) || from === activeStage;
    const toVisited = visitedStages.has(to) || to === activeStage;
    // Light up edge if either end was reached
    return fromVisited || toVisited ? "var(--lm-border-hi)" : "var(--lm-border)";
  }
  function edgeOpacity(from: FlowStage, to: FlowStage) {
    const fromVisited = visitedStages.has(from) || from === activeStage;
    const toVisited = visitedStages.has(to) || to === activeStage;
    if (fromVisited && toVisited) return 1;
    if (fromVisited || toVisited) return 0.7;
    return 0.5;
  }

  const glowId = compact ? "flow-glow-c" : "flow-glow";

  // Extract runtime info from events
  const nodeInfo = extractNodeInfo(turnEvents);

  return (
    <div style={{ position: "relative" }}>
      <svg
        ref={svgRef}
        viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
        style={{
          display: "block", width: "100%", height: "100%", minHeight: 360,
          cursor: dragging ? "grabbing" : "grab", userSelect: "none",
        }}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <defs>
          <filter id={glowId}>
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <marker id={`arrow-${compact ? "c" : "f"}`} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="var(--lm-border-hi)" />
          </marker>
        </defs>

        {/* Cluster group backgrounds — triangle layout */}
        {/* Lumi Server (top, full width, split LOCAL / ROUTE) */}
        <g>
          <rect x={50} y={50} width={730} height={160} rx={14}
            fill="var(--lm-teal)" fillOpacity={0.04} stroke="var(--lm-teal)" strokeWidth={1} opacity={0.25}
            strokeDasharray="4 4"
          />
          <text x={415} y={40} textAnchor="middle"
            fill="var(--lm-teal)" fontSize={11} fontWeight={700}
            fontFamily="monospace" opacity={0.6}
            style={{ letterSpacing: "0.08em" }}>
            Lumi Server
          </text>
        </g>
        {/* LeLamp (bottom-left) — band aligned with OpenClaw Tool+Think row */}
        <g>
          <rect x={30} y={395} width={280} height={200} rx={14}
            fill="var(--lm-amber)" fillOpacity={0.04} stroke="var(--lm-amber)" strokeWidth={1} opacity={0.3}
            strokeDasharray="4 4"
          />
          <text x={145} y={385} textAnchor="middle"
            fill="var(--lm-amber)" fontSize={11} fontWeight={700}
            fontFamily="monospace" opacity={0.6}
            style={{ letterSpacing: "0.08em" }}>
            LeLamp
          </text>
        </g>
        {/* OpenClaw — 3 cols: Tool+Resp | Agent+Think | TG; rows: Agent+TG, Tool+Think, Response */}
        <g>
          <rect x={448} y={292} width={385} height={540} rx={14}
            fill="var(--lm-blue)" fillOpacity={0.04} stroke="var(--lm-blue)" strokeWidth={1} opacity={0.3}
            strokeDasharray="4 4"
          />
          <text x={641} y={282} textAnchor="middle"
            fill="var(--lm-blue)" fontSize={11} fontWeight={700}
            fontFamily="monospace" opacity={0.6}
            style={{ letterSpacing: "0.08em" }}>
            OpenClaw
          </text>
        </g>

        {/* Edges */}
        {edges.map(([from, to]) => {
          const f = positions[from];
          const t = positions[to];
          const dx = t.x - f.x, dy = t.y - f.y;
          const len = Math.sqrt(dx * dx + dy * dy) || 1;
          const x1 = f.x + (dx / len) * nodeR;
          const y1 = f.y + (dy / len) * nodeR;
          const x2 = t.x - (dx / len) * (nodeR + 4);
          const y2 = t.y - (dy / len) * (nodeR + 4);
          return (
            <line key={`${from}-${to}`} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={edgeColor(from, to)}
              strokeWidth={edgeOpacity(from, to) > 0.5 ? 2 : 1.5}
              markerEnd={`url(#arrow-${compact ? "c" : "f"})`}
              opacity={edgeOpacity(from, to)}
            />
          );
        })}

        {/* Nodes */}
        {FLOW_NODES.map((node) => {
          const pos = positions[node.id];
          const isActive = node.id === activeStage;
          const isVisited = visitedStages.has(node.id);
          const color = nodeColor(node.id);
          const opacity = nodeOpacity(node.id);
          const lines = nodeInfo[node.id] ?? [];
          const hasInfo = lines.length > 0 && (isActive || isVisited);
          const descLines = node.desc.split(" · ").length;
          // Info box: below node for all clusters
          const infoBelow = true;
          const boxY = infoBelow
            ? pos.y + nodeR + 18 + descLines * 10 + 6
            : pos.y - nodeR - 10 - lines.slice(0, 4).length * 11 - 8;
          return (
            <g key={node.id} opacity={opacity}>
              {/* Glow ring for active */}
              {isActive && (
                <circle cx={pos.x} cy={pos.y} r={nodeR + 6}
                  fill="none" stroke={color} strokeWidth={2}
                  opacity={0.35} style={{ filter: `url(#${glowId})` }}
                />
              )}
              <circle cx={pos.x} cy={pos.y} r={nodeR}
                fill={isActive ? `${color}22` : "var(--lm-surface)"}
                stroke={color} strokeWidth={isActive ? 2.5 : 1.5}
                style={isActive ? { filter: `url(#${glowId})` } : undefined}
              />
              {/* Icon + short label (top line) */}
              <text x={pos.x} y={pos.y - 6} textAnchor="middle"
                fill={color} fontSize={9} fontWeight={isActive ? 700 : 600}>
                {node.icon} {node.short}
              </text>
              {/* Full label (bottom line) */}
              <text x={pos.x} y={pos.y + 6} textAnchor="middle"
                fill={color} fontSize={7} opacity={0.9}>
                {node.label}
              </text>
              {/* Description below circle */}
              {node.desc.split(" · ").map((part, i) => (
                <text key={`d${i}`} x={pos.x} y={pos.y + nodeR + 14 + i * 10} textAnchor="middle"
                  fill={color} fontSize={5.5} opacity={0.6}>
                  {part}
                </text>
              ))}

              {/* Runtime info box — shows tool names, func calls, messages */}
              {hasInfo && (() => {
                // Wrap long lines at ~35 chars per row
                const MAX_CHARS = 35;
                const wrapped: string[] = [];
                for (const line of lines.slice(0, 6)) {
                  if (line.length <= MAX_CHARS) { wrapped.push(line); }
                  else {
                    for (let j = 0; j < line.length; j += MAX_CHARS) {
                      wrapped.push(line.slice(j, j + MAX_CHARS));
                    }
                  }
                }
                const showLines = wrapped.slice(0, 8);
                const maxLen = Math.max(...showLines.map((l) => l.length));
                const boxW = Math.max(140, maxLen * 4 + 20);
                return (
                  <g>
                    <rect
                      x={pos.x - boxW / 2} y={boxY - 2}
                      width={boxW} height={showLines.length * 10 + 8}
                      rx={4} ry={4}
                      fill="var(--lm-card)" stroke={color} strokeWidth={0.5}
                      opacity={0.92}
                    />
                    {showLines.map((line, i) => (
                      <text
                        key={i}
                        x={pos.x} y={boxY + 8 + i * 10}
                        textAnchor="middle"
                        fill={color} fontSize={5.5} opacity={0.9}
                        fontFamily="monospace"
                      >
                        {line}
                      </text>
                    ))}
                  </g>
                );
              })()}
            </g>
          );
        })}
      </svg>

      {/* Zoom controls overlay */}
      <div style={{
        position: "absolute", bottom: 6, right: 6,
        display: "flex", gap: 4, alignItems: "center",
      }}>
        <span style={{ fontSize: 9, color: "var(--lm-text-muted)", marginRight: 4 }}>
          {Math.round(zoom * 100)}%
        </span>
        {[
          { label: "−", action: () => setZoom((z) => Math.max(0.4, z - 0.2)) },
          { label: "⟳", action: resetView },
          { label: "+", action: () => setZoom((z) => Math.min(4, z + 0.2)) },
        ].map((btn) => (
          <button key={btn.label} onClick={btn.action} style={{
            width: 22, height: 22, borderRadius: 5, border: "1px solid var(--lm-border)",
            background: "var(--lm-surface)", color: "var(--lm-text-dim)",
            cursor: "pointer", fontSize: 12, lineHeight: 1, padding: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>{btn.label}</button>
        ))}
      </div>
    </div>
  );
}

// Source type → icon map
const SOURCE_ICON: Record<string, string> = {
  voice: "🎤", motion: "👁", sound: "🔊", environment: "🌡", system: "⚙", unknown: "❓",
  telegram: "💬", schedule: "⏰",
  "ambient:breathing": "💨", "ambient:movement": "🤖", "ambient:mumble": "💭",
  "ambient:idle": "😴",
};

// Extract input/output summary from a turn
function turnIO(turn: Turn): { input: string; output: string } {
  let input = "";
  let output = "";
  let inputIsPlaceholder = false;
  let outputFromIntent = false;
  const turnRunId = turn.runId;
  for (const ev of turn.events) {
    const evRunId = extractEventRunId(ev);
    const sameRun = !turnRunId || !evRunId || evRunId === turnRunId;
    // Input: first sensing_input or chat_input message
    if (!input && (ev.type === "sensing_input" || (ev.type === "flow_enter" && ev.detail?.node === "sensing_input")
        || (ev.type === "flow_event" && ev.detail?.node === "sensing_input"))) {
      const d = ev.detail as Record<string, any> | undefined;
      const dataMsg = d?.data?.message ?? d?.message;
      const m = ev.summary.match(/^\[([^\]]+)\]\s*(.*)/);
      input = dataMsg || (m ? m[2] : "") || ev.summary;
    }
    if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
      // Prefer full message from detail (untruncated) over summary
      const d = ev.detail as Record<string, any> | undefined;
      const fullMsg = d?.message ?? d?.data?.message;
      const msg = fullMsg || parseTelegramSummary(ev.summary);
      if (msg) {
        // Prefer a real Telegram message and allow replacing a prior placeholder.
        if (!input || inputIsPlaceholder) {
          input = msg;
          inputIsPlaceholder = false;
        }
      } else if (!input) {
        input = TELEGRAM_FALLBACK_MESSAGE;
        inputIsPlaceholder = true;
      }
    }
    // Ambient turn input
    if (!input && turn.type.startsWith("ambient:")) {
      input = turn.type.replace("ambient:", "") + " behavior";
    }
    // Schedule turn input
    if (!input && (ev.type === "schedule_trigger" || ev.type === "cron_fire")) {
      const d = ev.detail as Record<string, any> | undefined;
      input = d?.name ?? d?.data?.name ?? ev.summary ?? "scheduled task";
    }
    // Fallback input: derive from chat_send summary emitted by sensing path
    // Example summary: "[sensing:motion] Small movement detected..."
    if (!input && (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send"))) {
      const d = ev.detail as Record<string, any> | undefined;
      const raw = (d?.message ?? ev.summary ?? "").trim();
      const m = raw.match(/^\[sensing:[^\]]+\]\s*(.*)$/i);
      const extracted = (m?.[1] ?? "").trim();
      if (extracted) input = extracted;
    }
    // Output: intent_match is authoritative for local turns; tts_send for agent turns.
    // intent_match output should never be overwritten by a stale tts_send from a different run.
    if (sameRun && (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match"))) {
      const d = ev.detail as Record<string, any> | undefined;
      output = d?.data?.tts ?? d?.tts ?? ev.summary ?? output;
      outputFromIntent = true;
    }
    if (!outputFromIntent && sameRun && (ev.type === "tts" || (ev.type === "flow_event" && ev.detail?.node === "tts_send"))) {
      const d = ev.detail as Record<string, any> | undefined;
      output = d?.data?.text ?? d?.text ?? ev.summary ?? output;
    }
    // Fallback: use final assistant chat_response when tts_send is missing
    if (!output && sameRun && ev.type === "chat_response" && ev.state === "final") {
      const d = ev.detail as Record<string, any> | undefined;
      output = d?.message ?? ev.summary ?? "";
    }
    // Ambient turn output
    if (turn.type.startsWith("ambient:") && ev.type === "flow_exit" && ev.detail?.node?.startsWith("ambient_")) {
      output = ev.summary || "done";
    }
  }
  return { input, output };
}

function TurnBadge({ turn }: { turn: Turn }) {
  const pathColor = turn.path === "local" ? "var(--lm-green)"
    : turn.path === "agent" ? "var(--lm-blue)"
    : "var(--lm-text-muted)";
  const statusColor = turn.status === "done" ? "var(--lm-green)"
    : turn.status === "error" ? "var(--lm-red)"
    : "var(--lm-amber)";
  const icon = SOURCE_ICON[turn.type] ?? SOURCE_ICON.unknown;
  const { input, output } = turnIO(turn);

  return (
    <div style={{
      padding: "8px 10px",
      borderRadius: 8,
      background: "var(--lm-surface)",
      border: "1px solid var(--lm-border)",
      fontSize: 11,
      cursor: "default",
    }}>
      {/* Row 1: source icon + type + path + status + time */}
      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 4 }}>
        <span style={{ fontSize: 14, lineHeight: 1 }}>{icon}</span>
        <span style={{
          fontSize: 10, fontWeight: 700, color: "var(--lm-text)",
          textTransform: "uppercase" as const,
        }}>{turn.type}</span>
        <span style={{
          fontSize: 8, padding: "1px 5px", borderRadius: 3,
          background: `${pathColor}18`, color: pathColor, fontWeight: 700,
          textTransform: "uppercase" as const,
        }}>{turn.path}</span>
        <span style={{
          width: 6, height: 6, borderRadius: "50%",
          background: statusColor, display: "inline-block", flexShrink: 0,
        }} />
        <span style={{ fontSize: 8, color: "var(--lm-text-muted)", marginLeft: "auto", fontFamily: "monospace" }}>
          {turn.startTime}
        </span>
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
      {/* Row 3: output */}
      {output && (
        <div style={{
          fontSize: 10, color: "var(--lm-text-dim)",
          wordBreak: "break-word" as const, lineHeight: 1.4,
        }}>
          <span style={{ color: "var(--lm-amber)", fontWeight: 600, marginRight: 4 }}>OUT 🔊</span>
          {output}
        </div>
      )}
      {/* Row 4: token usage + event count */}
      <div style={{ fontSize: 9, color: "var(--lm-text-muted)", marginTop: 3, display: "flex", gap: 8, alignItems: "center" }}>
        <span>{turn.events.length} events</span>
        {(() => {
          const endEvt = turn.events.find((e) => e.type === "lifecycle" && e.phase === "end" && e.detail?.inputTokens);
          if (!endEvt?.detail) return null;
          const d = endEvt.detail as Record<string, string>;
          const inp = parseInt(d.inputTokens ?? "0", 10);
          const out = parseInt(d.outputTokens ?? "0", 10);
          if (!inp && !out) return null;
          const fmt = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
          return (
            <span style={{ color: "var(--lm-purple)", fontWeight: 600 }}>
              {fmt(inp)} in / {fmt(out)} out
            </span>
          );
        })()}
      </div>
    </div>
  );
}

// Canvas modal overlay
function CanvasModal({
  activeStage,
  visitedStages,
  turnEvents,
  onClose,
}: {
  activeStage: ActiveFlowStage;
  visitedStages: Set<FlowStage>;
  turnEvents: DisplayEvent[];
  onClose: () => void;
}) {
  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(0,0,0,0.72)", backdropFilter: "blur(4px)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "var(--lm-card)", border: "1px solid var(--lm-border)",
          borderRadius: 16, padding: 32, maxWidth: 820, width: "90vw",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "var(--lm-text)" }}>Lumi Turn Workflow</span>
          <button onClick={onClose} style={{
            background: "none", border: "none", color: "var(--lm-text-muted)",
            cursor: "pointer", fontSize: 16, lineHeight: 1,
          }}>✕</button>
        </div>

        {/* Full-size diagram with zoom/pan */}
        <FlowDiagram activeStage={activeStage} visitedStages={visitedStages} turnEvents={turnEvents} />
        <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginTop: 8, textAlign: "center" as const }}>
          Scroll to zoom · Drag to pan · Click ⟳ to reset · Zoom in to see tool/func details
        </div>

        {/* Legend */}
        <div style={{ marginTop: 20, display: "flex", flexWrap: "wrap" as const, gap: 8 }}>
          {FLOW_NODES.map((n) => (
            <div key={n.id} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10.5, color: "var(--lm-text-dim)" }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: n.color, display: "inline-block", flexShrink: 0 }} />
              {n.label}
            </div>
          ))}
        </div>

        {/* Path descriptions */}
        <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, fontSize: 10.5, color: "var(--lm-text-dim)" }}>
          <div style={{ padding: "8px 12px", borderRadius: 8, background: "var(--lm-surface)", border: "1px solid var(--lm-border)" }}>
            <span style={{ color: "var(--lm-green)", fontWeight: 600 }}>Fast path (~50ms)</span><br />
            Sensing → Intent Check → Local Match → TTS Speak → Idle
          </div>
          <div style={{ padding: "8px 12px", borderRadius: 8, background: "var(--lm-surface)", border: "1px solid var(--lm-border)" }}>
            <span style={{ color: "var(--lm-blue)", fontWeight: 600 }}>Agent path (~2–5s)</span><br />
            Sensing → Intent Check → Agent Call → Thinking → [Tools] → Response → TTS → Idle
          </div>
        </div>
      </div>
    </div>
  );
}

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

function FlowSection({
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

  const clearFlowMessages = useCallback(() => {
    const ok = window.confirm("Clear all flow messages/events from this panel?");
    if (!ok) return;
    setSelectedTurnId(null);
    onClearEvents();
  }, [onClearEvents]);

  const clearServerFlowLog = useCallback(async () => {
    const ok = window.confirm("Clear flow log file on server (today)? This cannot be undone.");
    if (!ok) return;
    try {
      const r = await fetch(`${API}/openclaw/flow-logs`, { method: "DELETE" });
      const j = await r.json();
      if (!r.ok || j?.status !== 1) throw new Error(j?.message || "request failed");
      setSelectedTurnId(null);
      onClearEvents();
      window.alert("Server flow log cleared.");
    } catch (e) {
      window.alert(`Failed to clear server flow log: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [onClearEvents]);

  /** Exact in-memory panel state — used by ↓ Pair (second file) to diff feed vs grouping. */
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

  /** Same tail as GET /flow-events — fetch+blob so Pair can trigger two saves in one click. */
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

  /** One click → two files (delay avoids browser blocking the second download). */
  const downloadFlowPair = useCallback(async () => {
    await downloadServerJsonlTail();
    await new Promise((resolve) => setTimeout(resolve, 500));
    downloadUISnapshot();
  }, [downloadServerJsonlTail, downloadUISnapshot]);

  const turns = groupIntoTurns(events);
  const selectedTurn = selectedTurnId ? turns.find((t) => t.id === selectedTurnId) : turns[0];

  // Derive active stage and visited stages from selected (or latest) turn's events
  const turnEvents = selectedTurn?.events ?? events.slice(-30);
  const activeStage = deriveActiveStage(turnEvents);

  const visitedStages = new Set<FlowStage>();
  for (const ev of turnEvents) {
    const key = ev.type === "flow_event" && ev.detail?.node
      ? `flow_event:${ev.detail.node}` : ev.type;
    for (const node of FLOW_NODES) {
      if (node.triggers.includes(key)) visitedStages.add(node.id);
    }
  }
  // Fallback: some turns only retain chat_send/agent_call without sensing_input markers.
  // If payload clearly comes from sensing, still mark SENSE as visited.
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
              onClick={() => void downloadFlowPair()}
              title={`Downloads 2 files: (1) server JSONL last ${FLOW_EVENTS_MAX} lines — same tail as this panel; (2) UI snapshot JSON (events + turns). Short delay between saves so the browser allows both.`}
              style={{
                fontSize: 11, padding: "4px 12px", borderRadius: 6,
                background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                color: "var(--lm-text-dim)", cursor: "pointer", fontWeight: 600,
              }}
            >
              ↓ Pair
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
            <a
              href={`${API}/openclaw/debug-logs`}
              download
              style={{
                fontSize: 11, padding: "4px 12px", borderRadius: 6,
                background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                color: "var(--lm-text-dim)", cursor: "pointer", fontWeight: 600,
                textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 5,
              }}
              title="Download OpenClaw debug payload logs"
            >
              ↓ Debug
            </a>
            <button
              onClick={clearFlowMessages}
              style={{
                fontSize: 11, padding: "4px 12px", borderRadius: 6,
                background: "rgba(248,113,113,0.12)", border: "1px solid rgba(248,113,113,0.35)",
                color: "var(--lm-red)", cursor: "pointer", fontWeight: 600,
              }}
              title="Clear Flow Panel messages"
            >
              ✕ Clear
            </button>
            <button
              onClick={clearServerFlowLog}
              style={{
                fontSize: 11, padding: "4px 12px", borderRadius: 6,
                background: "rgba(248,113,113,0.12)", border: "1px solid rgba(248,113,113,0.35)",
                color: "var(--lm-red)", cursor: "pointer", fontWeight: 700,
              }}
              title="Clear flow log file on server"
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
                  {/* Session break separator (reversed list: break on NEXT item means gap before this one) */}
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

        {/* Center: flow diagram + icon guide */}
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

          {/* Icon guide */}
          <div style={{ ...S.card, padding: "12px 16px" }}>
            <div style={S.cardLabel}>Guide</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {[
                { icon: "●", color: "var(--lm-amber)",   label: "Active node — currently processing" },
                { icon: "◌", color: "var(--lm-text-dim)", label: "Visited — stage was reached this turn" },
                { icon: "◯", color: "var(--lm-border)",  label: "Inactive — not reached yet" },
                { icon: "⬢", color: "var(--lm-amber)",   label: "Canvas — click to expand full diagram" },
                { icon: "→", color: "var(--lm-green)",   label: "Fast path — local intent (~50ms)" },
                { icon: "→", color: "var(--lm-blue)",    label: "Agent path — OpenClaw AI (~2–5s)" },
                { icon: "⬡", color: "var(--lm-purple)",  label: "Flow Panel — this section" },
                { icon: "◎", color: "var(--lm-teal)",    label: "Workflow — raw event feed" },
              ].map((item, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 10.5, color: "var(--lm-text-dim)" }}>
                  <span style={{ color: item.color, fontSize: 12, lineHeight: 1, flexShrink: 0 }}>{item.icon}</span>
                  {item.label}
                </div>
              ))}
            </div>
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
                // Determine which flow node this event maps to
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

function CameraSection({
  displayTs: _displayTs,
}: {
  displayTs: number;
}) {
  const [snapTs, setSnapTs] = useState(Date.now());

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={S.grid2}>
        {/* Live camera stream */}
        <div style={S.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={S.cardLabel}>Camera Stream</div>
            <span style={{
              fontSize: 10,
              padding: "2px 7px",
              borderRadius: 4,
              background: "rgba(248,113,113,0.15)",
              color: "var(--lm-red)",
              fontWeight: 700,
              letterSpacing: "0.05em",
            }}>LIVE</span>
          </div>
          <img
            src={`${HW}/camera/stream`}
            alt="camera"
            style={{
              width: "100%",
              borderRadius: 8,
              border: "1px solid var(--lm-border)",
              display: "block",
              background: "var(--lm-surface)",
            }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        </div>

        {/* Display eyes preview */}
        <div style={S.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={S.cardLabel}>Display Eyes (GC9A01)</div>
            <button
              onClick={() => setSnapTs(Date.now())}
              style={{
                fontSize: 10,
                padding: "3px 10px",
                borderRadius: 6,
                background: "var(--lm-amber-dim)",
                border: "1px solid var(--lm-amber)",
                color: "var(--lm-amber)",
                cursor: "pointer",
              }}
            >
              Refresh
            </button>
          </div>
          <div style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            padding: 16,
          }}>
            <img
              src={`${HW}/display/snapshot?t=${snapTs}`}
              alt="display"
              style={{
                width: 160,
                height: 160,
                borderRadius: "50%",
                border: "3px solid var(--lm-amber)",
                boxShadow: "0 0 20px var(--lm-amber-glow)",
                objectFit: "cover",
                display: "block",
                background: "var(--lm-surface)",
              }}
              onError={(e) => {
                const el = e.target as HTMLImageElement;
                el.style.display = "none";
              }}
            />
          </div>
          <div style={{ textAlign: "center" as const, fontSize: 11, color: "var(--lm-text-muted)" }}>
            1.28″ round LCD — 240×240
          </div>
        </div>
      </div>

      {/* Camera snapshot */}
      <div style={S.card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={S.cardLabel}>Camera Snapshot</div>
          <button
            onClick={() => setSnapTs(Date.now())}
            style={{
              fontSize: 10,
              padding: "3px 10px",
              borderRadius: 6,
              background: "var(--lm-surface)",
              border: "1px solid var(--lm-border)",
              color: "var(--lm-text-dim)",
              cursor: "pointer",
            }}
          >
            Capture
          </button>
        </div>
        <img
          src={`${HW}/camera/snapshot?t=${snapTs}`}
          alt="snapshot"
          style={{
            width: "100%",
            maxHeight: 280,
            objectFit: "contain",
            borderRadius: 8,
            border: "1px solid var(--lm-border)",
            display: "block",
            background: "var(--lm-surface)",
          }}
          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
        />
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

// ─── Analytics types ─────────────────────────────────────────────────────────

interface VersionMetrics {
  turnCount: number;
  durationAvg: number;
  durationP50: number;
  durationP95: number;
  tokensTotal: number;
  tokensInput: number;
  tokensOutput: number;
  tokensAvg: number;
  innerAvg: number;
  innerMax: number;
}

interface AnalyticsRow {
  date: string;
  version: string;
  metrics: VersionMetrics;
}

interface AnalyticsData {
  rows: AnalyticsRow[];
  dates: string[];
  versions: string[];
}

type Preset = "7d" | "14d" | "30d" | "custom";

function fmtDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

const CHART_COLORS = {
  amber: "rgba(245,158,11,0.85)",
  amberFill: "rgba(245,158,11,0.15)",
  green: "rgba(52,211,153,0.85)",
  greenFill: "rgba(52,211,153,0.15)",
  blue: "rgba(96,165,250,0.85)",
  blueFill: "rgba(96,165,250,0.15)",
  purple: "rgba(168,85,247,0.85)",
  purpleFill: "rgba(168,85,247,0.15)",
  teal: "rgba(45,212,191,0.85)",
  tealFill: "rgba(45,212,191,0.15)",
  red: "rgba(248,113,113,0.85)",
  gridColor: "rgba(255,255,255,0.06)",
  tickColor: "rgba(255,255,255,0.4)",
};

const chartScaleDefaults = {
  grid: { color: CHART_COLORS.gridColor },
  ticks: { color: CHART_COLORS.tickColor, font: { size: 10 } },
};

// Color palette for version series (cycles if more versions than colors)
const VERSION_COLORS = [
  { border: "rgba(245,158,11,0.85)", bg: "rgba(245,158,11,0.15)" },  // amber
  { border: "rgba(96,165,250,0.85)",  bg: "rgba(96,165,250,0.15)" },  // blue
  { border: "rgba(168,85,247,0.85)", bg: "rgba(168,85,247,0.15)" },  // purple
  { border: "rgba(52,211,153,0.85)", bg: "rgba(52,211,153,0.15)" },  // green
  { border: "rgba(45,212,191,0.85)", bg: "rgba(45,212,191,0.15)" },  // teal
  { border: "rgba(248,113,113,0.85)", bg: "rgba(248,113,113,0.15)" }, // red
];

function vColor(i: number) {
  return VERSION_COLORS[i % VERSION_COLORS.length];
}

function AnalyticsSection() {
  const [preset, setPreset] = useState<Preset>("7d");
  const [customFrom, setCustomFrom] = useState(fmtDate(new Date(Date.now() - 7 * 86400000)));
  const [customTo, setCustomTo] = useState(fmtDate(new Date()));
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(false);

  const dateRange = useMemo(() => {
    if (preset === "custom") return { from: customFrom, to: customTo };
    const days = preset === "7d" ? 7 : preset === "14d" ? 14 : 30;
    return { from: fmtDate(new Date(Date.now() - days * 86400000)), to: fmtDate(new Date()) };
  }, [preset, customFrom, customTo]);

  const fetchAnalytics = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/openclaw/analytics?from=${dateRange.from}&to=${dateRange.to}`);
      const j = await r.json();
      if (j.status === 1) setAnalytics(j.data);
    } catch { /* ignore */ }
    setLoading(false);
  }, [dateRange]);

  useEffect(() => { fetchAnalytics(); }, [fetchAnalytics]);

  const dates = analytics?.dates ?? [];
  const versions = analytics?.versions ?? [];
  const rows = analytics?.rows ?? [];
  const labels = dates.map((d) => d.slice(5)); // MM-DD
  const multiVersion = versions.length > 1;

  // Build lookup: rowMap[date][version] = metrics
  const rowMap = useMemo(() => {
    const m: Record<string, Record<string, VersionMetrics>> = {};
    for (const r of rows) {
      if (!m[r.date]) m[r.date] = {};
      m[r.date][r.version] = r.metrics;
    }
    return m;
  }, [rows]);

  // Helper: get metric value for (date, version), default 0
  const val = (date: string, ver: string, fn: (m: VersionMetrics) => number) => {
    const m = rowMap[date]?.[ver];
    return m ? fn(m) : 0;
  };

  // Summary totals (across all versions)
  const totalTurns = rows.reduce((s, r) => s + r.metrics.turnCount, 0);
  const totalTokens = rows.reduce((s, r) => s + r.metrics.tokensTotal, 0);
  const durRows = rows.filter((r) => r.metrics.durationAvg > 0);
  const avgDuration = durRows.length > 0 ? durRows.reduce((s, r) => s + r.metrics.durationAvg, 0) / durRows.length : 0;
  const innerRows = rows.filter((r) => r.metrics.innerAvg > 0);
  const avgInner = innerRows.length > 0 ? innerRows.reduce((s, r) => s + r.metrics.innerAvg, 0) / innerRows.length : 0;

  const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: CHART_COLORS.tickColor, font: { size: 11 } } },
    },
    scales: { x: chartScaleDefaults, y: chartScaleDefaults },
  };

  const pillStyle = (active: boolean): React.CSSProperties => ({
    padding: "5px 14px",
    borderRadius: 6,
    border: `1px solid ${active ? "var(--lm-amber)" : "var(--lm-border)"}`,
    background: active ? "rgba(245,158,11,0.12)" : "transparent",
    color: active ? "var(--lm-amber)" : "var(--lm-text-dim)",
    fontSize: 11.5,
    fontWeight: active ? 600 : 400,
    cursor: "pointer",
  });

  const summaryCardStyle: React.CSSProperties = {
    ...S.card,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 4,
    padding: "16px 12px",
  };

  // Build per-version datasets for a given metric
  const makeVersionDatasets = (
    fn: (m: VersionMetrics) => number,
    opts?: { type?: "bar" | "line"; fill?: boolean },
  ) => {
    const type = opts?.type ?? "line";
    return versions.map((ver, vi) => ({
      label: multiVersion ? `v${ver}` : fn.name || "Value",
      data: dates.map((d) => val(d, ver, fn)),
      ...(type === "bar"
        ? { backgroundColor: vColor(vi).border, borderRadius: 4, barPercentage: multiVersion ? 0.8 : 0.6 }
        : {
            borderColor: vColor(vi).border,
            backgroundColor: opts?.fill !== false ? vColor(vi).bg : undefined,
            fill: opts?.fill !== false,
            tension: 0.3,
            pointRadius: 3,
          }),
    }));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Date range picker */}
      <div style={{ ...S.card, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--lm-text-muted)", fontWeight: 600 }}>RANGE</span>
        {(["7d", "14d", "30d", "custom"] as Preset[]).map((p) => (
          <button key={p} style={pillStyle(preset === p)} onClick={() => setPreset(p)}>
            {p === "custom" ? "Custom" : p}
          </button>
        ))}
        {preset === "custom" && (
          <>
            <input
              type="date"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
              style={{ background: "var(--lm-card)", color: "var(--lm-text)", border: "1px solid var(--lm-border)", borderRadius: 6, padding: "4px 8px", fontSize: 11 }}
            />
            <span style={{ color: "var(--lm-text-muted)" }}>—</span>
            <input
              type="date"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
              style={{ background: "var(--lm-card)", color: "var(--lm-text)", border: "1px solid var(--lm-border)", borderRadius: 6, padding: "4px 8px", fontSize: 11 }}
            />
          </>
        )}
        {loading && <span style={{ fontSize: 11, color: "var(--lm-text-muted)" }}>Loading...</span>}
        {versions.length > 0 && (
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            {versions.map((v, i) => (
              <span key={v} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "var(--lm-text-muted)" }}>
                <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: vColor(i).border }} />
                v{v}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Summary cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
        <div style={summaryCardStyle}>
          <span style={{ fontSize: 22, fontWeight: 700, color: "var(--lm-amber)" }}>{totalTurns}</span>
          <span style={{ fontSize: 10, color: "var(--lm-text-muted)", fontWeight: 600 }}>TOTAL TURNS</span>
        </div>
        <div style={summaryCardStyle}>
          <span style={{ fontSize: 22, fontWeight: 700, color: "var(--lm-green)" }}>{totalTokens.toLocaleString()}</span>
          <span style={{ fontSize: 10, color: "var(--lm-text-muted)", fontWeight: 600 }}>TOTAL TOKENS</span>
        </div>
        <div style={summaryCardStyle}>
          <span style={{ fontSize: 22, fontWeight: 700, color: "var(--lm-blue)" }}>{avgDuration ? (avgDuration / 1000).toFixed(1) + "s" : "—"}</span>
          <span style={{ fontSize: 10, color: "var(--lm-text-muted)", fontWeight: 600 }}>AVG DURATION</span>
        </div>
        <div style={summaryCardStyle}>
          <span style={{ fontSize: 22, fontWeight: 700, color: "var(--lm-purple)" }}>{avgInner ? avgInner.toFixed(1) : "—"}</span>
          <span style={{ fontSize: 10, color: "var(--lm-text-muted)", fontWeight: 600 }}>AVG INNER STEPS</span>
        </div>
      </div>

      {rows.length === 0 && !loading && (
        <div style={{ ...S.card, textAlign: "center", padding: 40, color: "var(--lm-text-muted)" }}>
          No analytics data for selected range
        </div>
      )}

      {rows.length > 0 && (
        <>
          {/* Row 1: Turn count + Duration */}
          <div style={S.grid2}>
            <div style={{ ...S.card, height: 260 }}>
              <div style={S.cardLabel}>Turn Count per Day {multiVersion && "— by version"}</div>
              <div style={{ height: 210 }}>
                <Bar
                  data={{ labels, datasets: makeVersionDatasets((m) => m.turnCount, { type: "bar" }) }}
                  options={commonOptions}
                />
              </div>
            </div>

            <div style={{ ...S.card, height: 260 }}>
              <div style={S.cardLabel}>Avg Duration (seconds) {multiVersion && "— by version"}</div>
              <div style={{ height: 210 }}>
                <Line
                  data={{ labels, datasets: makeVersionDatasets((m) => +(m.durationAvg / 1000).toFixed(2)) }}
                  options={commonOptions}
                />
              </div>
            </div>
          </div>

          {/* Row 2: Tokens stacked bar + Tokens per turn */}
          <div style={S.grid2}>
            <div style={{ ...S.card, height: 260 }}>
              <div style={S.cardLabel}>Token Usage {multiVersion && "— by version"}</div>
              <div style={{ height: 210 }}>
                {multiVersion ? (
                  <Bar
                    data={{ labels, datasets: makeVersionDatasets((m) => m.tokensTotal, { type: "bar" }) }}
                    options={commonOptions}
                  />
                ) : (
                  <Bar
                    data={{
                      labels,
                      datasets: [
                        { label: "Input", data: dates.map((d) => val(d, versions[0], (m) => m.tokensInput)), backgroundColor: CHART_COLORS.blue, borderRadius: 2 },
                        { label: "Output", data: dates.map((d) => val(d, versions[0], (m) => m.tokensOutput)), backgroundColor: CHART_COLORS.purple, borderRadius: 2 },
                      ],
                    }}
                    options={{ ...commonOptions, scales: { ...commonOptions.scales, x: { ...chartScaleDefaults, stacked: true }, y: { ...chartScaleDefaults, stacked: true } } }}
                  />
                )}
              </div>
            </div>

            <div style={{ ...S.card, height: 260 }}>
              <div style={S.cardLabel}>Tokens per Turn {multiVersion && "— by version"}</div>
              <div style={{ height: 210 }}>
                <Line
                  data={{ labels, datasets: makeVersionDatasets((m) => Math.round(m.tokensAvg)) }}
                  options={commonOptions}
                />
              </div>
            </div>
          </div>

          {/* Row 3: Inner steps */}
          <div style={{ ...S.card, height: 260 }}>
            <div style={S.cardLabel}>Inner Loop Steps {multiVersion && "— by version"}</div>
            <div style={{ height: 210 }}>
              <Line
                data={{ labels, datasets: makeVersionDatasets((m) => +m.innerAvg.toFixed(1)) }}
                options={commonOptions}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

type LogSource = "lelamp" | "lumi" | "openclaw";
const LOG_SOURCES: { id: LogSource; label: string; color: string }[] = [
  { id: "lelamp",   label: "LeLamp",   color: "var(--lm-green)" },
  { id: "lumi",     label: "Lumi",     color: "var(--lm-amber)" },
  { id: "openclaw", label: "OpenClaw", color: "var(--lm-blue)" },
];

const LOG_LEVELS = ["ALL", "DEBUG", "INFO", "WARN", "ERROR"] as const;
type LogLevel = (typeof LOG_LEVELS)[number];

function detectLevel(line: string): LogLevel {
  const u = line.toUpperCase();
  if (u.includes("ERROR") || u.includes("ERR ")) return "ERROR";
  if (u.includes("WARN") || u.includes("WARNING")) return "WARN";
  if (u.includes("DEBUG") || u.includes("DBG ")) return "DEBUG";
  if (u.includes("INFO") || u.includes("INF ")) return "INFO";
  return "ALL";
}

const levelColor: Record<LogLevel, string> = {
  ALL: "var(--lm-text-dim)",
  DEBUG: "#a78bfa",
  INFO: "var(--lm-text-dim)",
  WARN: "#fbbf24",
  ERROR: "#f87171",
};

function LogPanel({ source, label, color }: { source: LogSource; label: string; color: string }) {
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastN, setLastN] = useState(200);
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [level, setLevel] = useState<LogLevel>("ALL");
  const scrollRef = useRef<HTMLDivElement>(null);
  const sseRef = useRef<EventSource | null>(null);

  // Initial fetch
  const fetchLines = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${API}/logs/tail?source=${source}&lines=${lastN}`);
      if (!resp.ok) {
        setError(`HTTP ${resp.status} ${resp.statusText}`);
        setLines([]);
        return;
      }
      const r = await resp.json();
      const data = r?.data;
      if (data?.error) setError(data.error);
      else setError(null);
      setLines(Array.isArray(data?.lines) ? data.lines : []);
    } catch (e) {
      setError(`Fetch error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [source, lastN]);

  useEffect(() => { fetchLines(); }, [fetchLines]);

  // SSE stream for new lines
  useEffect(() => {
    if (paused) return;
    const es = new EventSource(`${API}/logs/stream?source=${source}`);
    sseRef.current = es;
    es.addEventListener("log", (e) => {
      const line = (e as MessageEvent).data;
      if (line) setLines((prev) => [...prev.slice(-4999), line]);
    });
    es.addEventListener("error", () => {
      // EventSource reconnects automatically
    });
    return () => { es.close(); sseRef.current = null; };
  }, [source, paused]);

  // Filtered lines
  const filtered = useMemo(() => {
    let result = lines;
    if (level !== "ALL") {
      const levelIdx = LOG_LEVELS.indexOf(level);
      result = result.filter((l) => {
        const ll = detectLevel(l);
        return ll === "ALL" || LOG_LEVELS.indexOf(ll) >= levelIdx;
      });
    }
    if (filter.trim()) {
      try {
        const re = new RegExp(filter, "i");
        result = result.filter((l) => re.test(l));
      } catch {
        const lower = filter.toLowerCase();
        result = result.filter((l) => l.toLowerCase().includes(lower));
      }
    }
    return result;
  }, [lines, level, filter]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filtered, autoScroll]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  };

  // Highlight matching text
  const highlightLine = (line: string) => {
    if (!filter.trim()) return line;
    try {
      const re = new RegExp(`(${filter})`, "gi");
      const parts = line.split(re);
      if (parts.length <= 1) return line;
      return parts.map((p, i) =>
        re.test(p) ? <mark key={i} style={{ background: "#fbbf2466", color: "inherit", borderRadius: 2, padding: "0 1px" }}>{p}</mark> : p
      );
    } catch {
      return line;
    }
  };

  const btnStyle: React.CSSProperties = {
    fontSize: 10, padding: "3px 8px", borderRadius: 5,
    background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
    color: "var(--lm-text-dim)", cursor: "pointer", fontWeight: 600,
  };

  return (
    <div style={{ ...S.card, flex: 1, minHeight: 0, padding: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--lm-border)", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />
        <span style={{ ...S.cardLabel, marginBottom: 0, fontSize: 12 }}>{label}</span>
        <button onClick={fetchLines} style={btnStyle}>↻</button>
        <button
          onClick={() => setPaused((p) => !p)}
          style={{
            ...btnStyle,
            background: paused ? "var(--lm-amber-dim)" : "var(--lm-surface)",
            color: paused ? "var(--lm-amber)" : "var(--lm-text-dim)",
          }}
        >
          {paused ? "▶" : "⏸"}
        </button>
        <select
          value={lastN}
          onChange={(e) => setLastN(Number(e.target.value))}
          style={{ fontSize: 10, padding: "3px 6px", borderRadius: 5, background: "var(--lm-surface)", border: "1px solid var(--lm-border)", color: "var(--lm-text)" }}
        >
          {[100, 200, 500, 1000].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <span style={{ width: 1, height: 16, background: "var(--lm-border)", margin: "0 2px" }} />
        {/* Log level filter */}
        <select
          value={level}
          onChange={(e) => setLevel(e.target.value as LogLevel)}
          style={{
            fontSize: 10, padding: "3px 6px", borderRadius: 5,
            background: level !== "ALL" ? "var(--lm-amber-dim)" : "var(--lm-surface)",
            border: "1px solid var(--lm-border)",
            color: level !== "ALL" ? "var(--lm-amber)" : "var(--lm-text)",
            fontWeight: level !== "ALL" ? 700 : 400,
          }}
        >
          {LOG_LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
        {/* Grep filter */}
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="grep..."
          style={{
            fontSize: 10, padding: "3px 8px", borderRadius: 5, width: 120,
            background: filter ? "var(--lm-amber-dim)" : "var(--lm-surface)",
            border: `1px solid ${filter ? "var(--lm-amber)" : "var(--lm-border)"}`,
            color: "var(--lm-text)", fontFamily: "monospace",
            outline: "none",
          }}
        />
        {filter && (
          <button onClick={() => setFilter("")} style={{ ...btnStyle, padding: "3px 6px" }}>✕</button>
        )}
        <button onClick={() => setLines([])} style={btnStyle}>Clear</button>
        <label style={{ marginLeft: "auto", fontSize: 9, color: "var(--lm-text-muted)", display: "flex", alignItems: "center", gap: 4, cursor: "pointer", userSelect: "none" }}>
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            style={{ width: 11, height: 11, accentColor: "var(--lm-amber)", cursor: "pointer" }}
          />
          Auto-scroll
        </label>
        <span style={{ fontSize: 9, color: "var(--lm-text-muted)" }}>
          {loading ? "Loading..." : error ? error : filtered.length !== lines.length ? `${filtered.length}/${lines.length}` : `${lines.length} lines`}
        </span>
      </div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          flex: 1, overflowY: "auto", padding: "6px 0",
          fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
          fontSize: 10.5, lineHeight: 1.55, whiteSpace: "pre-wrap" as const, wordBreak: "break-all" as const,
        }}
        className="lm-hide-scroll"
      >
        {filtered.length === 0 ? (
          <div style={{ padding: "12px 14px", color: "var(--lm-text-muted)", fontSize: 11 }}>
            {error ? error : filter || level !== "ALL" ? "No matching lines." : `No log lines from ${label} yet.`}
          </div>
        ) : (
          filtered.map((line, i) => {
            const ll = detectLevel(line);
            return (
              <div key={i} style={{
                padding: "1px 12px",
                color: levelColor[ll],
                borderLeft: `2px solid ${ll === "ERROR" ? "#f87171" : ll === "WARN" ? "#fbbf24" : "transparent"}`,
              }}>
                {highlightLine(line)}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function LogsSection() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, height: "100%" }}>
      {LOG_SOURCES.map((src) => (
        <LogPanel key={src.id} source={src.id} label={src.label} color={src.color} />
      ))}
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────

export default function Monitor() {
  const [section, setSection] = useState<Section>("overview");

  const [sys, setSys] = useState<SystemInfo | null>(null);
  const [net, setNet] = useState<NetworkInfo | null>(null);
  const [hw, setHw] = useState<HWHealth | null>(null);
  const [oc, setOc] = useState<OCStatus | null>(null);
  const [presence, setPresence] = useState<PresenceInfo | null>(null);
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const [servo, setServo] = useState<ServoState | null>(null);
  const [displayState, setDisplayState] = useState<DisplayState | null>(null);
  const [audio, setAudio] = useState<AudioVolume | null>(null);
  const [ledColor, setLedColor] = useState<LEDColor | null>(null);
  const [sceneInfo, setSceneInfo] = useState<SceneInfo | null>(null);
  const [events, setEvents] = useState<DisplayEvent[]>([]);
  const [displayTs, setDisplayTs] = useState(0);

  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [ramHistory, setRamHistory] = useState<number[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string>("");

  const evtIdRef = useRef(0);
  const clearFlowEvents = useCallback(() => {
    setEvents([]);
  }, []);

  // Polling
  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [sysR, netR, ocR] = await Promise.all([
          fetch(`${API}/system/info`).then((r) => r.json()),
          fetch(`${API}/system/network`).then((r) => r.json()),
          fetch(`${API}/openclaw/status`).then((r) => r.json()),
        ]);
        if (sysR.status === 1) {
          const d = sysR.data;
          setSys(d);
          setCpuHistory((h) => [...h.slice(-(HISTORY_LEN - 1)), d.cpuLoad]);
          setRamHistory((h) => [...h.slice(-(HISTORY_LEN - 1)), d.memPercent]);
        }
        if (netR.status === 1) setNet(netR.data);
        if (ocR.status === 1) setOc(ocR.data);
        setLastUpdate(new Date().toLocaleTimeString());
      } catch {}

      try {
        const hwR = await fetch(`${HW}/health`).then((r) => r.json());
        setHw(hwR);
      } catch {}

      try {
        const presR = await fetch(`${HW}/presence`).then((r) => r.json());
        setPresence(presR);
      } catch {}

      try {
        const [voiceR, servoR, dispR, audioR, ledR] = await Promise.all([
          fetch(`${HW}/voice/status`).then((r) => r.json()),
          fetch(`${HW}/servo`).then((r) => r.json()),
          fetch(`${HW}/display`).then((r) => r.json()),
          fetch(`${HW}/audio/volume`).then((r) => r.json()),
          fetch(`${HW}/led/color`).then((r) => r.json()),
        ]);
        setVoice(voiceR);
        setServo(servoR);
        setDisplayState(dispR);
        setAudio(audioR);
        if (ledR.hex) setLedColor(ledR);
        setDisplayTs(Date.now());
      } catch {}

      try {
        const sceneR = await fetch(`${HW}/scene`).then((r) => r.json());
        if (sceneR.scenes) setSceneInfo(sceneR);
      } catch {}
    };

    fetchAll();
    const t = setInterval(fetchAll, 3000);
    return () => clearInterval(t);
  }, []);

  // Flow data source (Doggi-style): seed from file REST + live file stream.
  useEffect(() => {
    let es: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    const applyEvents = (rows: MonitorEvent[]) => {
      const next = rows
        .slice(-FLOW_EVENTS_MAX)
        .map((ev, i) => ({ ...ev, _seq: i }));
      setEvents(next);
      evtIdRef.current = next.length;
    };
    const fetchRecentFlow = async () => {
      try {
        const r = await fetch(`${API}/openclaw/flow-events?last=${FLOW_EVENTS_MAX}`).then((x) => x.json());
        const rows = (r?.data?.events ?? []) as MonitorEvent[];
        if (!Array.isArray(rows)) return;
        applyEvents(rows);
      } catch {
        // keep previous UI state on fetch failure
      }
    };

    fetchRecentFlow();
    es = new EventSource(`${API}/openclaw/flow-stream`);
    es.onmessage = (msg) => {
      try {
        const payload = JSON.parse(msg.data) as { events?: MonitorEvent[] };
        if (!Array.isArray(payload.events)) return;
        applyEvents(payload.events);
      } catch {
        // ignore malformed stream payload
      }
    };
    es.onerror = () => {
      es?.close();
      es = null;
      // Fallback to polling if stream disconnects.
      if (!pollTimer) pollTimer = setInterval(fetchRecentFlow, 2000);
    };
    return () => {
      es?.close();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, []);

  const ocOnline = oc?.connected ?? false;

  return (
    <div className="lm-root" style={S.root}>
      {/* Sidebar */}
      <aside style={S.sidebar}>
        <div style={S.sidebarLogo}>
          <div style={S.sidebarLogoName}>✦ Lumi</div>
          <div style={S.sidebarLogoSub}>Monitor Dashboard</div>
        </div>
        <nav style={{ padding: "10px 0", flex: 1 }}>
          {NAV.map((item) => (
            <button
              key={item.id}
              style={S.navItem(section === item.id)}
              onClick={() => setSection(item.id)}
            >
              <span style={{ fontSize: 14, lineHeight: 1 }}>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div style={{
          padding: "12px 16px",
          borderTop: "1px solid var(--lm-border)",
          fontSize: 10,
          color: "var(--lm-text-muted)",
          display: "flex",
          flexDirection: "column",
          gap: 3,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <StatusDot ok={ocOnline} />
            <span>{ocOnline ? "OpenClaw Online" : "OpenClaw Offline"}</span>
          </div>
          {lastUpdate && <div>Updated {lastUpdate}</div>}
        </div>
      </aside>

      {/* Main */}
      <main style={S.main}>
        {/* Topbar */}
        <div style={S.topbar}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--lm-text)" }}>
            {NAV.find((n) => n.id === section)?.label}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {sys && (
              <span style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                CPU {sys.cpuLoad.toFixed(1)}% · RAM {sys.memPercent.toFixed(0)}% · {sys.cpuTemp.toFixed(0)}°C
              </span>
            )}
            <span style={{
              fontSize: 10,
              padding: "2px 8px",
              borderRadius: 4,
              background: ocOnline ? "rgba(52,211,153,0.1)" : "rgba(248,113,113,0.1)",
              color: ocOnline ? "var(--lm-green)" : "var(--lm-red)",
              border: `1px solid ${ocOnline ? "rgba(52,211,153,0.3)" : "rgba(248,113,113,0.25)"}`,
              fontWeight: 600,
            }}>
              {ocOnline ? "● ONLINE" : "○ OFFLINE"}
            </span>
          </div>
        </div>

        {/* Content */}
        <div style={S.content} className="lm-fade-in">
          {section === "overview" && (
            <OverviewSection
              sys={sys}
              net={net}
              hw={hw}
              oc={oc}
              presence={presence}
              voice={voice}
              servo={servo}
              displayState={displayState}
              audio={audio}
              ledColor={ledColor}
              sceneInfo={sceneInfo}
              onSceneActivate={(scene) => {
                fetch(`${HW}/scene`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ scene }),
                }).then((r) => r.json()).then((res) => {
                  if (res.status === "ok") setSceneInfo((prev) => prev ? { ...prev, active: scene } : prev);
                }).catch(() => {});
              }}
            />
          )}
          {section === "system" && (
            <SystemSection
              sys={sys}
              net={net}
              cpuHistory={cpuHistory}
              ramHistory={ramHistory}
            />
          )}
          {section === "flow"      && <FlowSection events={events} onClearEvents={clearFlowEvents} />}
          {section === "camera"    && <CameraSection displayTs={displayTs} />}
          {section === "analytics" && <AnalyticsSection />}
          {section === "logs"      && <LogsSection />}
        </div>
      </main>
    </div>
  );
}
