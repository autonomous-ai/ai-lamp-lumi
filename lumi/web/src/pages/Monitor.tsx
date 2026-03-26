import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Progress } from "@/components/ui/progress";
import { ThemeToggle } from "@/components/ThemeToggle";
import { cn } from "@/lib/utils";

// --- API URLs ---
const API = "/api";
const HW = "/hw";

// --- Types ---
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

interface VoiceStatus {
  voice_available: boolean;
  voice_listening: boolean;
  tts_available: boolean;
  tts_speaking: boolean;
}

interface PresenceInfo {
  state: string;
  enabled: boolean;
  seconds_since_motion: number;
  idle_timeout: number;
  away_timeout: number;
}

interface DisplayInfo {
  mode: string;
  expression: string;
  pupil_x: number;
  pupil_y: number;
  openness: number;
  available_expressions: string[];
  hardware: boolean;
}

interface AudioInfo {
  output_device: number | null;
  input_device: number | null;
  available: boolean;
}

interface LEDInfo {
  led_count: number;
}

interface SceneInfo {
  scenes: string[];
}

interface ServoInfo {
  recordings?: string[];
  playing?: boolean;
  current_animation?: string;
}

interface MonitorEvent {
  id: string;
  time: string;
  type: string;
  summary: string;
  detail?: Record<string, string>;
  runId?: string;
  phase?: string;
  state?: string;
  error?: string;
}

// Types whose text can be long (merged deltas) — show full text instead of truncating
const STREAMABLE_TYPES = new Set(["assistant_delta", "thinking", "chat_response"]);

// --- Event type display config ---
const EVENT_CFG: Record<string, { label: string; color: string; icon: string }> = {
  sensing_input:   { label: "Sensing",  color: "bg-blue-500",    icon: "👁" },
  chat_send:       { label: "Send",     color: "bg-indigo-500",  icon: "➜" },
  lifecycle:       { label: "Agent",    color: "bg-yellow-500",  icon: "⚙" },
  thinking:        { label: "Think",    color: "bg-amber-500",   icon: "🧠" },
  tool_call:       { label: "Tool",     color: "bg-orange-500",  icon: "🔧" },
  assistant_delta: { label: "Write",    color: "bg-emerald-500", icon: "✏" },
  chat_response:   { label: "Response", color: "bg-green-500",   icon: "💬" },
  tts:             { label: "TTS",      color: "bg-purple-500",  icon: "🔊" },
};

// --- Helpers ---
function formatUptime(sec: number): string {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatMB(kb: number): string {
  return (kb / 1024).toFixed(0);
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

function signalPercent(dbm: number): number {
  if (dbm >= -30) return 100;
  if (dbm <= -90) return 0;
  return Math.round(((dbm + 90) / 60) * 100);
}

// --- Fetch helper ---
async function fetchJSON<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const json = await res.json();
    if (json?.status === 1) return json.data as T;
    return json as T;
  } catch {
    return null;
  }
}

// ============================================================
// MONITOR PAGE
// ============================================================
export default function Monitor() {
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null);
  const [netInfo, setNetInfo] = useState<NetworkInfo | null>(null);
  const [hwHealth, setHWHealth] = useState<HWHealth | null>(null);
  const [ocStatus, setOCStatus] = useState<OCStatus | null>(null);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [presence, setPresence] = useState<PresenceInfo | null>(null);
  const [displayInfo, setDisplayInfo] = useState<DisplayInfo | null>(null);
  const [audioInfo, setAudioInfo] = useState<AudioInfo | null>(null);
  const [ledInfo, setLedInfo] = useState<LEDInfo | null>(null);
  const [sceneInfo, setSceneInfo] = useState<SceneInfo | null>(null);
  const [servoInfo, setServoInfo] = useState<ServoInfo | null>(null);
  const [events, setEvents] = useState<MonitorEvent[]>([]);
  const [sseConnected, setSseConnected] = useState(false);
  const [streaming, setStreaming] = useState(true);
  const imgRef = useRef<HTMLImageElement>(null);
  const eventsEndRef = useRef<HTMLDivElement>(null);

  // --- Polling ---
  usePolling(() => fetchJSON<SystemInfo>(`${API}/system/info`).then(setSysInfo), 5000);
  usePolling(() => fetchJSON<NetworkInfo>(`${API}/system/network`).then(setNetInfo), 10000);
  usePolling(() => fetchJSON<HWHealth>(`${HW}/health`).then(setHWHealth), 5000);
  usePolling(() => fetchJSON<OCStatus>(`${API}/openclaw/status`).then(setOCStatus), 3000);
  usePolling(() => fetchJSON<VoiceStatus>(`${HW}/voice/status`).then(setVoiceStatus), 3000);
  usePolling(() => fetchJSON<PresenceInfo>(`${HW}/presence`).then(setPresence), 5000);
  usePolling(() => fetchJSON<DisplayInfo>(`${HW}/display`).then(setDisplayInfo), 5000);
  usePolling(() => fetchJSON<AudioInfo>(`${HW}/audio`).then(setAudioInfo), 10000);
  usePolling(() => fetchJSON<LEDInfo>(`${HW}/led`).then(setLedInfo), 10000);
  usePolling(() => fetchJSON<SceneInfo>(`${HW}/scene`).then(setSceneInfo), 30000);
  usePolling(() => fetchJSON<ServoInfo>(`${HW}/servo`).then(setServoInfo), 5000);

  // --- Load recent events on mount ---
  useEffect(() => {
    fetchJSON<MonitorEvent[]>(`${API}/openclaw/recent`).then((data) => {
      if (data) setEvents(data);
    });
  }, []);

  // --- SSE subscription ---
  // Mergeable event types: accumulate text instead of creating new rows
  const MERGEABLE_TYPES = new Set(["assistant_delta", "thinking"]);

  useEffect(() => {
    const es = new EventSource(`${API}/openclaw/events`);
    es.onopen = () => setSseConnected(true);
    es.onmessage = (e) => {
      try {
        const evt: MonitorEvent = JSON.parse(e.data);
        setEvents((prev) => {
          // For streaming deltas, merge into the last event with same type+runId
          if (MERGEABLE_TYPES.has(evt.type) && prev.length > 0) {
            const last = prev[prev.length - 1];
            if (last.type === evt.type && last.runId === evt.runId) {
              const merged = { ...last, summary: last.summary + evt.summary };
              return [...prev.slice(0, -1), merged];
            }
          }
          // For partial chat_response, update existing row with same runId
          if (evt.type === "chat_response" && evt.state === "partial" && prev.length > 0) {
            let idx = -1;
            for (let i = prev.length - 1; i >= 0; i--) {
              if (prev[i].type === "chat_response" && prev[i].runId === evt.runId) { idx = i; break; }
            }
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = { ...evt };
              return updated;
            }
          }
          return [...prev.slice(-199), evt];
        });
      } catch { /* ignore */ }
    };
    es.onerror = () => setSseConnected(false);
    return () => es.close();
  }, []);

  // --- Auto-scroll events ---
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const toggleStream = () => {
    setStreaming((prev) => !prev);
    if (imgRef.current && streaming) imgRef.current.src = "";
  };

  const takeSnapshot = async () => {
    try {
      const res = await fetch(`${HW}/camera/snapshot`);
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `lumi-snapshot-${Date.now()}.jpg`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* ignore */ }
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold">Lumi Monitor</h1>
            {sysInfo?.version && (
              <Badge variant="outline" className="text-[10px] font-mono">{sysInfo.version}</Badge>
            )}
            {sysInfo?.deviceId && (
              <span className="text-[10px] text-muted-foreground font-mono">{sysInfo.deviceId}</span>
            )}
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-4 space-y-4">
        {/* ---- ROW 1: Core status cards ---- */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {/* Agent */}
          <StatusCard title={ocStatus?.name || "Agent"}>
            {ocStatus ? (
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Dot color={ocStatus.connected ? "green" : "red"} pulse={ocStatus.connected} />
                  <span className="text-sm font-medium">
                    {ocStatus.connected ? "Connected" : "Disconnected"}
                  </span>
                </div>
                {ocStatus.sessionKey && (
                  <span className="text-[11px] text-muted-foreground">Session active</span>
                )}
              </div>
            ) : <Unavailable label="Lumi" />}
          </StatusCard>

          {/* System */}
          <StatusCard title="System">
            {sysInfo ? (
              <div className="flex gap-3 items-center">
                <CircleGauge value={Math.min(100, (sysInfo.cpuLoad / 4) * 100)} label={`${Math.min(100, Math.round((sysInfo.cpuLoad / 4) * 100))}%`} sublabel="CPU" />
                <div className="flex-1 space-y-1.5 min-w-0">
                  <div className="space-y-0.5">
                    <div className="flex justify-between text-[11px]">
                      <span className="text-muted-foreground">RAM</span>
                      <span>{formatMB(sysInfo.memUsed)} / {formatMB(sysInfo.memTotal)} MB</span>
                    </div>
                    <Progress value={sysInfo.memPercent} className="h-1.5" />
                  </div>
                  <div className="flex gap-3 text-[11px]">
                    <span title="CPU Temperature">{sysInfo.cpuTemp > 0 ? `${sysInfo.cpuTemp.toFixed(0)}°C` : "--"}</span>
                    <span className="text-muted-foreground">up {formatUptime(sysInfo.uptime)}</span>
                  </div>
                </div>
              </div>
            ) : <Unavailable label="System" />}
          </StatusCard>

          {/* Network */}
          <StatusCard title="Network">
            {netInfo ? (
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Dot color={netInfo.internet ? "green" : "red"} />
                  <span className="text-sm font-medium truncate">{netInfo.ssid || "No WiFi"}</span>
                </div>
                {netInfo.ip && (
                  <span className="text-[11px] text-muted-foreground font-mono block">{netInfo.ip}</span>
                )}
                {netInfo.signal !== 0 && (
                  <div className="flex items-center gap-1.5 text-[11px]">
                    <span className="text-muted-foreground">Signal</span>
                    <Progress value={signalPercent(netInfo.signal)} className="h-1 w-12" />
                    <span>{netInfo.signal} dBm</span>
                  </div>
                )}
              </div>
            ) : <Unavailable label="Network" />}
          </StatusCard>

          {/* Voice & Audio */}
          <StatusCard title="Voice">
            {voiceStatus ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Dot color={voiceStatus.voice_available ? "green" : "red"} pulse={voiceStatus.voice_listening} />
                  <span className="text-sm font-medium">
                    {voiceStatus.voice_listening ? "Listening..." : voiceStatus.voice_available ? "Ready" : "Off"}
                  </span>
                  {voiceStatus.tts_speaking && (
                    <Badge variant="default" className="text-[10px] py-0 px-1.5 animate-pulse">Speaking</Badge>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <HWBadge label="STT" ok={voiceStatus.voice_available} />
                  <HWBadge label="TTS" ok={voiceStatus.tts_available} />
                  {audioInfo && <HWBadge label="Mic" ok={audioInfo.input_device !== null} />}
                  {audioInfo && <HWBadge label="Speaker" ok={audioInfo.output_device !== null} />}
                </div>
              </div>
            ) : <Unavailable label="Voice" />}
          </StatusCard>
        </div>

        {/* ---- ROW 2: Hardware subsystems ---- */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {/* Display / Eyes */}
          <StatusCard title="Display">
            {displayInfo ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Dot color={displayInfo.hardware ? "green" : "yellow"} />
                  <span className="text-sm font-medium capitalize">{displayInfo.expression}</span>
                </div>
                <div className="flex flex-wrap gap-1 text-[10px]">
                  <Badge variant="outline" className="py-0 px-1">{displayInfo.mode}</Badge>
                  {!displayInfo.hardware && (
                    <Badge variant="secondary" className="py-0 px-1">SW only</Badge>
                  )}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {displayInfo.available_expressions.length} expressions
                </div>
              </div>
            ) : <Unavailable label="Display" />}
          </StatusCard>

          {/* LED */}
          <StatusCard title="LED">
            {hwHealth ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Dot color={hwHealth.led ? "green" : "red"} />
                  <span className="text-sm font-medium">{hwHealth.led ? "Active" : "Off"}</span>
                </div>
                {ledInfo && (
                  <span className="text-[11px] text-muted-foreground">{ledInfo.led_count} LEDs (WS2812)</span>
                )}
              </div>
            ) : <Unavailable label="LED" />}
          </StatusCard>

          {/* Servo */}
          <StatusCard title="Servo">
            {hwHealth ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Dot color={hwHealth.servo ? "green" : "red"} />
                  <span className="text-sm font-medium">{hwHealth.servo ? "Active" : "Unavailable"}</span>
                </div>
                {servoInfo?.playing && (
                  <Badge variant="default" className="text-[10px] py-0 px-1.5 animate-pulse">
                    Playing {servoInfo.current_animation || ""}
                  </Badge>
                )}
                {servoInfo?.recordings && servoInfo.recordings.length > 0 && (
                  <span className="text-[10px] text-muted-foreground">
                    {servoInfo.recordings.length} recordings
                  </span>
                )}
              </div>
            ) : <Unavailable label="Servo" />}
          </StatusCard>

          {/* Sensing & Presence */}
          <StatusCard title="Sensing">
            <div className="space-y-1.5">
              {hwHealth && (
                <div className="flex flex-wrap gap-1.5">
                  <HWBadge label="Camera" ok={hwHealth.camera} />
                  <HWBadge label="Motion" ok={hwHealth.sensing} />
                </div>
              )}
              {presence && (
                <div className="flex items-center gap-2">
                  <PresenceBadge state={presence.state} />
                  {presence.seconds_since_motion > 0 && (
                    <span className="text-[10px] text-muted-foreground">
                      {formatUptime(presence.seconds_since_motion)} ago
                    </span>
                  )}
                </div>
              )}
              {presence && (
                <Badge variant={presence.enabled ? "default" : "secondary"} className="text-[10px] py-0 px-1.5">
                  {presence.enabled ? "Auto-detect" : "Manual"}
                </Badge>
              )}
            </div>
          </StatusCard>
        </div>

        {/* ---- ROW 3: Scenes (if available) ---- */}
        {sceneInfo && sceneInfo.scenes.length > 0 && (
          <Card className="rounded-xl border shadow-sm">
            <CardContent className="py-3 px-4">
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Scenes</span>
                {sceneInfo.scenes.map((scene) => (
                  <Badge key={scene} variant="outline" className="text-[11px] capitalize">{scene}</Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ---- ROW 4: Workflow + Camera ---- */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Workflow */}
          <Card className="rounded-xl border shadow-sm lg:col-span-3">
            <CardHeader className="pb-2 px-4 pt-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold">Workflow</CardTitle>
                <div className="flex items-center gap-2">
                  <Badge
                    variant={sseConnected ? "default" : "secondary"}
                    className={cn("text-[10px]", sseConnected && "animate-pulse")}
                  >
                    {sseConnected ? "Live" : "Reconnecting..."}
                  </Badge>
                  {events.length > 0 && (
                    <Button variant="ghost" size="sm" className="h-6 text-[11px] px-2" onClick={() => setEvents([])}>
                      Clear
                    </Button>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-4 pb-3">
              <ScrollArea className="h-[50vh] lg:h-[60vh] w-full rounded-md border bg-muted/20">
                <div className="p-2 space-y-0.5">
                  {events.length === 0 && (
                    <p className="text-sm text-muted-foreground text-center py-12">
                      Waiting for events...
                    </p>
                  )}
                  {events.map((evt) => (
                    <EventRow key={evt.id} event={evt} />
                  ))}
                  <div ref={eventsEndRef} />
                </div>
              </ScrollArea>
            </CardContent>
          </Card>

          {/* Camera */}
          <Card className="rounded-xl border shadow-sm lg:col-span-2">
            <CardHeader className="pb-2 px-4 pt-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold">Camera</CardTitle>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" className="h-7 text-xs" onClick={takeSnapshot}>
                    Snapshot
                  </Button>
                  <Button
                    variant={streaming ? "destructive" : "default"}
                    size="sm"
                    className="h-7 text-xs"
                    onClick={toggleStream}
                  >
                    {streaming ? "Stop" : "Start"}
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-4 pb-3">
              <div className="relative aspect-video bg-black rounded-lg overflow-hidden">
                {streaming ? (
                  <img
                    ref={imgRef}
                    src={`${HW}/camera/stream`}
                    alt="Camera stream"
                    className="w-full h-full object-contain"
                    onError={() => setStreaming(false)}
                  />
                ) : (
                  <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                    Stream paused
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* ---- Footer: HW API link ---- */}
        <div className="text-center pb-4">
          <a href="/hw/docs" target="_blank" rel="noopener noreferrer" className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2">
            LeLamp API Docs
          </a>
        </div>
      </main>
    </div>
  );
}

// ============================================================
// SUB-COMPONENTS
// ============================================================

function StatusCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="rounded-xl border shadow-sm">
      <CardHeader className="pb-1 px-3 pt-2.5">
        <CardTitle className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-3 pb-2.5">{children}</CardContent>
    </Card>
  );
}

function Dot({ color, pulse }: { color: "green" | "red" | "yellow"; pulse?: boolean }) {
  const c = color === "green" ? "bg-green-400" : color === "red" ? "bg-red-400" : "bg-yellow-400";
  return <span className={cn("inline-block w-2 h-2 rounded-full shrink-0", c, pulse && "animate-pulse")} />;
}

function Unavailable({ label }: { label: string }) {
  return <span className="text-xs text-muted-foreground">{label} unreachable</span>;
}

function CircleGauge({ value, label, sublabel }: { value: number; label: string; sublabel: string }) {
  const size = 52;
  const stroke = 4;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const offset = circumference - (value / 100) * circumference;
  const strokeColor = value > 80 ? "#ef4444" : value > 50 ? "#eab308" : "#10b981";
  const textColor = value > 80 ? "text-red-500" : value > 50 ? "text-yellow-500" : "text-emerald-500";

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} stroke="currentColor" className="text-muted" />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke}
          strokeDasharray={circumference} strokeDashoffset={offset}
          strokeLinecap="round"
          stroke={strokeColor}
          style={{ transition: "stroke-dashoffset 500ms ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn("text-[11px] font-semibold leading-none", textColor)}>{label}</span>
        <span className="text-[8px] text-muted-foreground leading-none mt-0.5">{sublabel}</span>
      </div>
    </div>
  );
}

function HWBadge({ label, ok }: { label: string; ok: boolean }) {
  return (
    <Badge variant={ok ? "default" : "secondary"} className="text-[10px] py-0 px-1.5">
      <span className={cn("inline-block w-1.5 h-1.5 rounded-full mr-1", ok ? "bg-green-400" : "bg-red-400")} />
      {label}
    </Badge>
  );
}

function PresenceBadge({ state }: { state: string }) {
  const map: Record<string, { variant: "default" | "secondary" | "destructive"; label: string }> = {
    present:  { variant: "default",     label: "Present" },
    idle:     { variant: "secondary",   label: "Idle" },
    away:     { variant: "secondary",   label: "Away" },
    disabled: { variant: "destructive", label: "Disabled" },
  };
  const cfg = map[state] ?? { variant: "secondary" as const, label: state };
  return <Badge variant={cfg.variant} className="text-[11px]">{cfg.label}</Badge>;
}

function EventRow({ event }: { event: MonitorEvent }) {
  const cfg = EVENT_CFG[event.type] ?? { label: event.type, color: "bg-gray-500", icon: "?" };
  const time = formatTime(event.time);

  return (
    <div className="flex items-start gap-2 py-1 px-2 rounded hover:bg-muted/50 transition-colors group">
      <span className={cn("w-1.5 h-1.5 rounded-full shrink-0 mt-1.5", cfg.color)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[11px] font-medium">{cfg.icon} {cfg.label}</span>
          <span className="text-[10px] text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
            {time}
          </span>
          {event.runId && (
            <span className="text-[9px] text-muted-foreground font-mono opacity-0 group-hover:opacity-100 transition-opacity">
              {event.runId}
            </span>
          )}
          {event.phase && (
            <Badge variant="outline" className="text-[9px] py-0 px-1 h-3.5">{event.phase}</Badge>
          )}
          {event.state === "partial" && (
            <Badge variant="secondary" className="text-[9px] py-0 px-1 h-3.5">streaming</Badge>
          )}
          {event.error && (
            <Badge variant="destructive" className="text-[9px] py-0 px-1 h-3.5">error</Badge>
          )}
        </div>
        <p className={cn(
          "text-[11px] text-muted-foreground",
          STREAMABLE_TYPES.has(event.type) ? "whitespace-pre-wrap break-words" : "truncate"
        )}>{event.summary}</p>
      </div>
    </div>
  );
}

// ============================================================
// HOOKS
// ============================================================

function usePolling(fn: () => void, intervalMs: number) {
  useEffect(() => {
    fn();
    const id = setInterval(fn, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);
}
