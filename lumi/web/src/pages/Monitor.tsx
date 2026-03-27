import { useEffect, useRef, useState } from "react";

const API = "http://<DEVICE_IP>/api";
const HW  = "http://<DEVICE_IP>/hw";
const HISTORY_LEN = 60;

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

type Section = "overview" | "system" | "workflow" | "camera";

const NAV: { id: Section; label: string; icon: string }[] = [
  { id: "overview", label: "Overview",  icon: "◈" },
  { id: "system",   label: "System",    icon: "⬡" },
  { id: "workflow", label: "Workflow",  icon: "◎" },
  { id: "camera",   label: "Camera",    icon: "⬟" },
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
                {servo.available_recordings.length} poses available
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4, marginTop: 4 }}>
                {servo.available_recordings.slice(0, 8).map((p) => (
                  <span key={p} style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: p === servo.current ? "var(--lm-amber-dim)" : "var(--lm-surface)",
                    border: `1px solid ${p === servo.current ? "var(--lm-amber)" : "var(--lm-border)"}`,
                    color: p === servo.current ? "var(--lm-amber)" : "var(--lm-text-dim)",
                  }}>{p}</span>
                ))}
              </div>
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
                {displayState.available_expressions.length} expressions
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4, marginTop: 4 }}>
                {displayState.available_expressions.slice(0, 8).map((e) => (
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
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
            <StatPill label="CPU" value={`${sys.cpuLoad.toFixed(1)}%`} color="var(--lm-amber)" />
            <StatPill label="RAM" value={`${sys.memPercent.toFixed(0)}%`} color="var(--lm-blue)" />
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
          <GaugeRing value={sys.cpuLoad} label="CPU" detail={`${sys.cpuLoad.toFixed(1)}%`} color="var(--lm-amber)" size={120} />
          <GaugeRing value={sys.memPercent} label="Memory" detail={`${Math.round(sys.memUsed/1024)}/${Math.round(sys.memTotal/1024)} MB`} color="var(--lm-blue)" size={120} />
          <GaugeRing
            value={sys.cpuTemp > 0 ? Math.min(100, (sys.cpuTemp / 85) * 100) : 0}
            label="Temp"
            detail={`${sys.cpuTemp.toFixed(1)}°C`}
            color={sys.cpuTemp > 70 ? "var(--lm-red)" : "var(--lm-teal)"}
            size={120}
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

function WorkflowSection({ events }: { events: DisplayEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const typeColor = (t: string): string => {
    switch (t) {
      case "lifecycle":       return "var(--lm-amber)";
      case "tool_call":       return "var(--lm-teal)";
      case "thinking":        return "var(--lm-purple)";
      case "assistant_delta": return "var(--lm-blue)";
      case "chat_response":   return "var(--lm-green)";
      default:
        if (t.includes("error")) return "var(--lm-red)";
        return "var(--lm-text-dim)";
    }
  };

  const typeLabel = (t: string): string => {
    switch (t) {
      case "lifecycle":       return "Lifecycle";
      case "tool_call":       return "Tool";
      case "thinking":        return "Thinking";
      case "assistant_delta": return "Assistant";
      case "chat_response":   return "Chat";
      default: return t;
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      <div style={{
        ...S.card,
        flex: 1,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        padding: 0,
        overflow: "hidden",
      }}>
        <div style={{
          padding: "12px 16px",
          borderBottom: "1px solid var(--lm-border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}>
          <span style={S.cardLabel}>OpenClaw Event Feed</span>
          <span style={{ fontSize: 10, color: "var(--lm-text-muted)" }}>{events.length} events</span>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }} className="lm-hide-scroll">
          {events.length === 0 ? (
            <div style={{ padding: "20px 16px", color: "var(--lm-text-muted)", fontSize: 12 }}>
              Waiting for workflow events…
            </div>
          ) : (
            events.map((ev) => (
              <div
                key={ev._seq}
                style={{
                  padding: "7px 16px",
                  borderLeft: `3px solid ${typeColor(ev.type)}`,
                  marginLeft: 8,
                  marginBottom: 2,
                  borderRadius: "0 6px 6px 0",
                  background: "var(--lm-surface)",
                  marginRight: 8,
                }}
                className="lm-fade-in"
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3, flexWrap: "wrap" as const }}>
                  <span style={{
                    fontSize: 10, padding: "1px 6px", borderRadius: 4,
                    background: `${typeColor(ev.type)}22`,
                    color: typeColor(ev.type), fontWeight: 600,
                  }}>{typeLabel(ev.type)}</span>
                  {ev.phase && (
                    <span style={{ fontSize: 10, color: "var(--lm-text-muted)", fontStyle: "italic" }}>{ev.phase}</span>
                  )}
                  {ev.runId && (
                    <span style={{ fontSize: 10, color: "var(--lm-text-muted)", fontFamily: "monospace" }}>
                      {ev.runId.slice(0, 8)}
                    </span>
                  )}
                  <span style={{ fontSize: 10, color: "var(--lm-text-muted)", marginLeft: "auto" }}>{ev.time}</span>
                </div>
                <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)", wordBreak: "break-all" as const }}>
                  {ev.summary}
                </div>
                {ev.error && (
                  <div style={{ fontSize: 11, color: "var(--lm-red)", marginTop: 3 }}>{ev.error}</div>
                )}
              </div>
            ))
          )}
          <div ref={bottomRef} />
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
  const [events, setEvents] = useState<DisplayEvent[]>([]);
  const [displayTs, setDisplayTs] = useState(0);

  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [ramHistory, setRamHistory] = useState<number[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string>("");

  const evtIdRef = useRef(0);

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
    };

    fetchAll();
    const t = setInterval(fetchAll, 3000);
    return () => clearInterval(t);
  }, []);

  // Seed recent events on mount
  useEffect(() => {
    fetch(`${API}/openclaw/recent`)
      .then((r) => r.json())
      .then((r) => {
        if (r.status === 1 && Array.isArray(r.data) && r.data.length > 0) {
          const seeded = (r.data as MonitorEvent[]).map((ev) => ({
            ...ev,
            _seq: evtIdRef.current++,
          }));
          setEvents(seeded);
        }
      })
      .catch(() => {});
  }, []);

  // SSE
  useEffect(() => {
    const es = new EventSource(`${API}/openclaw/events`);
    es.onmessage = (e) => {
      try {
        const ev: MonitorEvent = JSON.parse(e.data);
        setEvents((prev) => [
          ...prev.slice(-299),
          { ...ev, _seq: evtIdRef.current++ },
        ]);
      } catch {
        setEvents((prev) => [
          ...prev.slice(-299),
          {
            _seq: evtIdRef.current++,
            id: "", time: new Date().toLocaleTimeString(),
            type: "raw", summary: e.data,
          },
        ]);
      }
    };
    return () => es.close();
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
          {section === "workflow" && <WorkflowSection events={events} />}
          {section === "camera" && <CameraSection displayTs={displayTs} />}
        </div>
      </main>
    </div>
  );
}
