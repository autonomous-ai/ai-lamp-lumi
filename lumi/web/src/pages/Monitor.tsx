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

type Section = "overview" | "system" | "flow" | "camera";

const NAV: { id: Section; label: string; icon: string }[] = [
  { id: "overview", label: "Overview",  icon: "◈" },
  { id: "system",   label: "System",    icon: "⬡" },
  { id: "flow",     label: "Flow",      icon: "⬢" },
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
                {servo.available_recordings?.length ?? 0} poses available
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4, marginTop: 4 }}>
                {(servo.available_recordings ?? []).slice(0, 8).map((p) => (
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
                {displayState.available_expressions?.length ?? 0} expressions
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4, marginTop: 4 }}>
                {(displayState.available_expressions ?? []).slice(0, 8).map((e) => (
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

// ─── Flow Panel ──────────────────────────────────────────────────────────────

// Maps a MonitorEvent type/node to a flow stage ID
type FlowStage =
  | "idle" | "sensing" | "intent_check" | "local_match"
  | "agent_call" | "agent_thinking" | "tool_exec" | "agent_response" | "tts_speak";

interface FlowNodeDef {
  id: FlowStage;
  label: string;
  short: string;
  color: string;
  // event types or flow nodes that activate this stage
  triggers: string[];
  path: "main" | "fast" | "agent";
}

const FLOW_NODES: FlowNodeDef[] = [
  // idle  — triggered by ambient resume or ws_ready (connection established)
  { id: "idle",
    label: "Idle", short: "IDLE", color: "var(--lm-text-muted)", path: "main",
    triggers: ["ambient_resume", "flow_event:ambient_resume", "flow_event:ws_ready"] },

  // sensing — triggered by sensing_input (HTTP POST /sensing/event received)
  { id: "sensing",
    label: "Sensing", short: "SENSE", color: "var(--lm-amber)", path: "main",
    triggers: ["sensing_input", "flow_enter:sensing_input", "flow_exit:sensing_input"] },

  // intent_check — triggered when we decide to route (agent_call dispatched or intent checked)
  { id: "intent_check",
    label: "Intent Check", short: "INTENT", color: "var(--lm-teal)", path: "main",
    triggers: ["flow_event:agent_call", "flow_event:chat_send", "chat_send"] },

  // local_match — fast path: matched a local intent rule
  { id: "local_match",
    label: "Local Match", short: "LOCAL", color: "var(--lm-green)", path: "fast",
    triggers: ["intent_match", "flow_event:intent_match"] },

  // agent_call — message sent to OpenClaw via chat.send WebSocket RPC
  { id: "agent_call",
    label: "Agent Call", short: "AGENT", color: "var(--lm-blue)", path: "agent",
    triggers: ["flow_event:agent_call", "flow_event:chat_send", "flow_event:lifecycle_start"] },

  // agent_thinking — agent is reasoning (thinking stream events)
  { id: "agent_thinking",
    label: "Thinking", short: "THINK", color: "var(--lm-purple)", path: "agent",
    triggers: ["thinking", "flow_event:lifecycle_start"] },

  // tool_exec — agent invoked a tool
  { id: "tool_exec",
    label: "Tool Exec", short: "TOOL", color: "#f59e0b", path: "agent",
    triggers: ["tool_call", "flow_event:tool_call"] },

  // agent_response — agent turn ended, response accumulated
  { id: "agent_response",
    label: "Response", short: "RESP", color: "var(--lm-green)", path: "agent",
    triggers: ["chat_response", "flow_event:lifecycle_end"] },

  // tts_speak — text sent to LeLamp /voice/speak for playback
  { id: "tts_speak",
    label: "TTS Speak", short: "TTS", color: "var(--lm-purple)", path: "agent",
    triggers: ["tts", "flow_event:tts_send"] },
];

// Derive active stage from most recent relevant events
function deriveActiveStage(events: DisplayEvent[]): FlowStage {
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
  startTime: string;
  endTime?: string;
  type: string;        // "voice", "motion", etc.
  path: "local" | "agent" | "unknown";
  status: "active" | "done" | "error";
  events: DisplayEvent[];
}

function groupIntoTurns(events: DisplayEvent[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;

  for (const ev of events) {
    // sensing_input always starts a new turn
    if (ev.type === "sensing_input") {
      if (current) turns.push(current);
      const typeMatch = ev.summary.match(/^\[([^\]]+)\]/);
      current = {
        id: ev.runId || `local-${ev._seq}`,
        startTime: ev.time,
        type: typeMatch ? typeMatch[1] : "unknown",
        path: "unknown",
        status: "active",
        events: [ev],
      };
      continue;
    }
    if (!current) {
      // Orphan events before first sensing_input — create a synthetic turn
      current = { id: "init", startTime: ev.time, type: "system", path: "unknown", status: "active", events: [] };
    }
    current.events.push(ev);

    // Classify path
    if (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match")) {
      current.path = "local";
    } else if (ev.runId || ev.type === "lifecycle" || ev.type === "thinking") {
      current.path = "agent";
      if (ev.runId && current.id === "init") current.id = ev.runId;
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
  }
  if (current) turns.push(current);
  return turns.slice(-15).reverse(); // latest 15, newest first
}

// SVG Flow Diagram — renders the pipeline with highlighted active stage and visited stages
function FlowDiagram({
  activeStage,
  visitedStages,
  compact = false,
}: {
  activeStage: FlowStage;
  visitedStages: Set<FlowStage>;
  compact?: boolean;
}) {
  const W = compact ? 560 : 720;
  const H = compact ? 160 : 200;

  // Node positions (in 720x200 space, scaled for compact)
  const positions: Record<FlowStage, { x: number; y: number }> = {
    idle:           { x: 42,  y: 100 },
    sensing:        { x: 140, y: 100 },
    intent_check:   { x: 240, y: 100 },
    local_match:    { x: 340, y: 44  },
    agent_call:     { x: 340, y: 100 },
    agent_thinking: { x: 440, y: 100 },
    tool_exec:      { x: 540, y: 44  },
    agent_response: { x: 540, y: 100 },
    tts_speak:      { x: 640, y: 100 },
  };

  // Edges (from → to)
  const edges: [FlowStage, FlowStage][] = [
    ["idle",           "sensing"],
    ["sensing",        "intent_check"],
    ["intent_check",   "local_match"],
    ["intent_check",   "agent_call"],
    ["local_match",    "tts_speak"],
    ["agent_call",     "agent_thinking"],
    ["agent_thinking", "tool_exec"],
    ["agent_thinking", "agent_response"],
    ["tool_exec",      "agent_response"],
    ["agent_response", "tts_speak"],
    ["tts_speak",      "idle"],
  ];

  const nodeR = compact ? 22 : 28;
  const fontSize = compact ? 7.5 : 9;

  function nodeColor(id: FlowStage) {
    if (id === activeStage) return FLOW_NODES.find((n) => n.id === id)?.color ?? "#fff";
    if (visitedStages.has(id)) return FLOW_NODES.find((n) => n.id === id)?.color ?? "#fff";
    return "var(--lm-text-muted)";
  }
  function nodeOpacity(id: FlowStage) {
    if (id === activeStage) return 1;
    if (visitedStages.has(id)) return 0.55;
    return 0.25;
  }
  function edgeColor(from: FlowStage, to: FlowStage) {
    const fromVisited = visitedStages.has(from) || from === activeStage;
    const toVisited = visitedStages.has(to) || to === activeStage;
    return fromVisited && toVisited ? "var(--lm-border-hi)" : "var(--lm-border)";
  }

  const glowId = "flow-glow";

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 720 200`}
      style={{ display: "block", width: "100%", maxWidth: W, height: "auto" }}
    >
      <defs>
        <filter id={glowId}>
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      {/* Edges */}
      {edges.map(([from, to]) => {
        const f = positions[from];
        const t = positions[to];
        // Offset edge endpoints to circle edge
        const dx = t.x - f.x, dy = t.y - f.y;
        const len = Math.sqrt(dx * dx + dy * dy) || 1;
        const x1 = f.x + (dx / len) * nodeR;
        const y1 = f.y + (dy / len) * nodeR;
        const x2 = t.x - (dx / len) * (nodeR + 4);
        const y2 = t.y - (dy / len) * (nodeR + 4);
        return (
          <g key={`${from}-${to}`}>
            <line x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={edgeColor(from, to)} strokeWidth={1.5}
              markerEnd="url(#arrow)" opacity={0.6}
            />
          </g>
        );
      })}

      {/* Arrow marker */}
      <defs>
        <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L0,6 L6,3 z" fill="var(--lm-border-hi)" />
        </marker>
      </defs>

      {/* Nodes */}
      {FLOW_NODES.map((node) => {
        const pos = positions[node.id];
        const isActive = node.id === activeStage;
        const color = nodeColor(node.id);
        const opacity = nodeOpacity(node.id);
        return (
          <g key={node.id} opacity={opacity}>
            {/* Glow ring for active */}
            {isActive && (
              <circle cx={pos.x} cy={pos.y} r={nodeR + 6}
                fill="none" stroke={color} strokeWidth={2}
                opacity={0.35} style={{ filter: `url(#${glowId})` }}
              />
            )}
            {/* Node circle */}
            <circle cx={pos.x} cy={pos.y} r={nodeR}
              fill={isActive ? `${color}22` : "var(--lm-surface)"}
              stroke={color} strokeWidth={isActive ? 2 : 1}
              style={isActive ? { filter: `url(#${glowId})` } : undefined}
            />
            {/* Short label inside */}
            <text x={pos.x} y={pos.y - 3} textAnchor="middle"
              fill={color} fontSize={fontSize} fontWeight={isActive ? 700 : 500}>
              {node.short}
            </text>
            {/* Full label below */}
            <text x={pos.x} y={pos.y + 9} textAnchor="middle"
              fill={color} fontSize={fontSize - 1} opacity={0.8}>
              {node.label.split(" ")[1] ?? ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function TurnBadge({ turn }: { turn: Turn }) {
  const pathColor = turn.path === "local" ? "var(--lm-green)"
    : turn.path === "agent" ? "var(--lm-blue)"
    : "var(--lm-text-muted)";
  const statusColor = turn.status === "done" ? "var(--lm-green)"
    : turn.status === "error" ? "var(--lm-red)"
    : "var(--lm-amber)";

  return (
    <div style={{
      padding: "7px 10px",
      borderRadius: 8,
      background: "var(--lm-surface)",
      border: "1px solid var(--lm-border)",
      fontSize: 11,
      cursor: "default",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
        <span style={{
          fontSize: 9, padding: "1px 5px", borderRadius: 3,
          background: `${pathColor}18`, color: pathColor, fontWeight: 700,
          textTransform: "uppercase" as const,
        }}>{turn.path}</span>
        <span style={{
          fontSize: 9, padding: "1px 5px", borderRadius: 3,
          background: `${statusColor}15`, color: statusColor, fontWeight: 600,
        }}>{turn.status}</span>
        <span style={{ fontSize: 9, color: "var(--lm-text-muted)", marginLeft: "auto", fontFamily: "monospace" }}>
          {turn.startTime}
        </span>
      </div>
      <div style={{ color: "var(--lm-text-dim)", fontSize: 10.5, whiteSpace: "nowrap" as const, overflow: "hidden", textOverflow: "ellipsis" }}>
        [{turn.type}] — {turn.events.length} events
      </div>
    </div>
  );
}

// Canvas modal overlay
function CanvasModal({
  activeStage,
  visitedStages,
  onClose,
}: {
  activeStage: FlowStage;
  visitedStages: Set<FlowStage>;
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

        {/* Full-size diagram */}
        <FlowDiagram activeStage={activeStage} visitedStages={visitedStages} />

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

function FlowSection({ events }: { events: DisplayEvent[] }) {
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

  const activeNode = FLOW_NODES.find((n) => n.id === activeStage);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      {showCanvas && (
        <CanvasModal
          activeStage={activeStage}
          visitedStages={visitedStages}
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
          <div style={{ display: "flex", gap: 8 }}>
            <a
              href={`${API}/openclaw/flow-logs`}
              download
              style={{
                fontSize: 11, padding: "4px 12px", borderRadius: 6,
                background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                color: "var(--lm-text-dim)", cursor: "pointer", fontWeight: 600,
                textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 5,
              }}
            >
              ↓ Logs
            </a>
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

      {/* Simulate card — only on localhost */}
      {window.location.hostname === "localhost" && (
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
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 5 }} className="lm-hide-scroll">
            {turns.length === 0 ? (
              <div style={{ padding: 12, color: "var(--lm-text-muted)", fontSize: 11 }}>No turns yet</div>
            ) : (
              turns.map((turn) => (
                <div
                  key={turn.id}
                  onClick={() => setSelectedTurnId(turn.id === selectedTurn?.id ? null : turn.id)}
                  style={{
                    borderRadius: 8,
                    outline: turn.id === selectedTurn?.id ? `2px solid var(--lm-amber)` : "none",
                    cursor: "pointer",
                  }}
                >
                  <TurnBadge turn={turn} />
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
            <FlowDiagram activeStage={activeStage} visitedStages={visitedStages} compact />
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
                    <div style={{ fontSize: 10.5, color: "var(--lm-text-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const }}>
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
          {section === "flow"     && <FlowSection events={events} />}
          {section === "camera"   && <CameraSection displayTs={displayTs} />}
        </div>
      </main>
    </div>
  );
}
