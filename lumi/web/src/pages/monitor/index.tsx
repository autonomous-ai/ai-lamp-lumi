declare const __WEB_VERSION__: string;
import { useCallback, useEffect, useRef, useState } from "react";

function fmtDur(s: number): string {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}
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

import { S } from "./styles";
import { API, HW, HISTORY_LEN, FLOW_EVENTS_MAX, NAV } from "./types";
import type { Section, SystemInfo, NetworkInfo, HWHealth, OCStatus, PresenceInfo, VoiceStatus, ServoState, DisplayState, AudioVolume, LEDColor, SceneInfo, MonitorEvent, DisplayEvent } from "./types";
import { StatusDot, ForceUpdateButton } from "./components";
import { OverviewSection } from "./OverviewSection";
import { SystemSection } from "./SystemSection";
import { FlowSection } from "./FlowSection";
import { CameraSection } from "./CameraSection";
import { ServoSection } from "./ServoSection";
import { AnalyticsSection } from "./AnalyticsSection";
import { LogsSection } from "./LogsSection";
import { ChatSection } from "./ChatSection";
import { FaceOwnersSection } from "./FaceOwnersSection";
import { CliSection } from "./CliSection";

ChartJS.register(CategoryScale, LinearScale, BarElement, PointElement, LineElement, Title, Tooltip, Legend, Filler);

export default function Monitor() {
  const [section, setSectionRaw] = useState<Section>(() => {
    const h = window.location.hash.replace("#", "") as Section;
    return NAV.some((n) => n.id === h) ? h : "overview";
  });
  const setSection = (s: Section) => {
    window.location.hash = s;
    setSectionRaw(s);
  };

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
  const [lelampVersion, setLelampVersion] = useState<string | null>(null);
  const [events, setEvents] = useState<DisplayEvent[]>([]);
  const [displayTs, setDisplayTs] = useState(0);

  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [ramHistory, setRamHistory] = useState<number[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string>("");
  const [webTick, setWebTick] = useState(0);

  const evtIdRef = useRef(0);
  const clearFlowEvents = useCallback(() => {
    setEvents([]);
  }, []);

  // Ticker for web lifetime display
  useEffect(() => {
    const id = setInterval(() => setWebTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Fetch LeLamp version once
  useEffect(() => {
    fetch(`${HW}/version`).then((r) => r.json()).then((r) => {
      if (r.version) setLelampVersion(r.version);
    }).catch(() => {});
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

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const closeSidebar = () => setSidebarOpen(false);

  const ocOnline = oc?.connected ?? false;

  return (
    <div className="lm-root" style={S.root}>
      {/* Mobile overlay */}
      <div
        className={`lm-sidebar-overlay${sidebarOpen ? " lm-sidebar-overlay--open" : ""}`}
        onClick={closeSidebar}
      />

      {/* Sidebar */}
      <aside style={S.sidebar} className={`lm-sidebar${sidebarOpen ? " lm-sidebar--open" : ""}`}>
        <div style={S.sidebarLogo}>
          <div style={S.sidebarLogoName}>✦ Lumi</div>
          <div style={S.sidebarLogoSub}>Monitor Dashboard</div>
        </div>
        <nav style={{ padding: "10px 0", flex: 1 }}>
          {NAV.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              style={S.navItem(section === item.id)}
              onClick={(e) => { e.preventDefault(); setSection(item.id); closeSidebar(); }}
            >
              <span style={{ fontSize: 14, lineHeight: 1 }}>{item.icon}</span>
              {item.label}
            </a>
          ))}
          <AgentGWMenu closeSidebar={closeSidebar} />
          <a href="/hw/docs" style={S.navItem(false)} target="_blank" rel="noreferrer" onClick={closeSidebar}>
            <span style={{ fontSize: 14, lineHeight: 1 }}>⬟</span>
            HW Docs
          </a>
          <a href="/edit" style={S.navItem(false)} onClick={closeSidebar}>
            <span style={{ fontSize: 14, lineHeight: 1 }}>⚙</span>
            Settings
          </a>
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
          <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 2, fontSize: 9.5, color: "var(--lm-text-muted)" }}>
            <div>Web <span style={{ color: "var(--lm-teal)", fontWeight: 600 }}>{__WEB_VERSION__}</span>{" "}<span style={{ opacity: 0.65 }}>{fmtDur(webTick)}</span></div>
            <div>Lumi <span style={{ color: "var(--lm-amber)", fontWeight: 600 }}>{sys?.version ?? "—"}</span>{" "}<span style={{ opacity: 0.65 }}>{sys?.serviceUptime != null ? fmtDur(sys.serviceUptime) : "—"}</span></div>
            <div>LeLamp <span style={{ color: "var(--lm-blue)", fontWeight: 600 }}>{lelampVersion ?? "—"}</span>{" "}<span style={{ opacity: 0.65 }}>{sys?.lelampUptime != null ? fmtDur(sys.lelampUptime) : "—"}</span></div>
            <ForceUpdateButton />
          </div>
        </div>
      </aside>

      {/* Main */}
      <main style={S.main}>
        {/* Topbar */}
        <div style={S.topbar}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button className="lm-hamburger" onClick={() => setSidebarOpen((v) => !v)} aria-label="Menu">☰</button>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--lm-text)" }}>
              {NAV.find((n) => n.id === section)?.label}
            </span>
          </div>
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
        <div style={S.content} className="lm-content lm-fade-in">
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
          {section === "servo"     && <ServoSection />}
          {section === "face-owners" && <FaceOwnersSection />}
          {section === "analytics" && <AnalyticsSection />}
          {section === "logs"      && <LogsSection />}
          {/* Chat is always mounted to preserve history across tab switches */}
          <div style={{ display: section === "chat" ? "contents" : "none" }}>
            <ChatSection events={events} />
          </div>
          {section === "cli" && <CliSection />}
        </div>
      </main>
    </div>
  );
}
