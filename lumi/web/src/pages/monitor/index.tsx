declare const __WEB_VERSION__: string;
import { useCallback, useEffect, useRef, useState } from "react";
import { useTheme } from "@/lib/useTheme";

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
import { API, HW, HISTORY_LEN, FLOW_EVENTS_MAX, NAV, isNavGroup, isNavLink } from "./types";
import type { Section, SystemInfo, NetworkInfo, HWHealth, OCStatus, PresenceInfo, VoiceStatus, ServoState, DisplayState, AudioVolume, LEDColor, SceneInfo, MonitorEvent, DisplayEvent, NavEntry } from "./types";
import { StatusDot, SoftwareUpdateButtons } from "./components";
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

function allNavLeaves(): { id: Section; label: string }[] {
  const leaves: { id: Section; label: string }[] = [];
  for (const entry of NAV) {
    if (isNavGroup(entry)) entry.children.forEach((c) => { if (!isNavLink(c)) leaves.push(c); });
    else leaves.push(entry);
  }
  return leaves;
}

function NavGroupItem({ entry, section, setSection, closeSidebar }: {
  entry: Extract<NavEntry, { group: string }>;
  section: Section;
  setSection: (s: Section) => void;
  closeSidebar: () => void;
}) {
  const hasActiveChild = entry.children.some((c) => !isNavLink(c) && c.id === section);
  const [open, setOpen] = useState(hasActiveChild);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{ ...S.navGroupHeader(hasActiveChild), display: "flex", alignItems: "center", justifyContent: "space-between" }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ fontSize: 14, lineHeight: 1 }}>{entry.icon}</span>
          {entry.label}
        </span>
        <span style={{ fontSize: 9, color: "var(--lm-text-muted)", transition: "transform 0.15s", transform: open ? "rotate(90deg)" : "none" }}>▶</span>
      </button>
      {open && (
        <div>
          {entry.children.map((child) =>
            isNavLink(child) ? (
              <a
                key={child.href}
                href={child.href}
                style={S.navSubItem(false)}
                target={child.external ? "_blank" : undefined}
                rel={child.external ? "noreferrer" : undefined}
                onClick={closeSidebar}
              >
                <span style={{ fontSize: 13, lineHeight: 1 }}>{child.icon}</span>
                {child.label}
              </a>
            ) : (
              <a
                key={child.id}
                href={`#${child.id}`}
                style={S.navSubItem(section === child.id)}
                onClick={(e) => { e.preventDefault(); setSection(child.id); closeSidebar(); }}
              >
                <span style={{ fontSize: 13, lineHeight: 1 }}>{child.icon}</span>
                {child.label}
              </a>
            )
          )}
        </div>
      )}
    </div>
  );
}

function AgentGWMenu({ closeSidebar }: { closeSidebar: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          ...S.navItem(false),
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: "transparent", cursor: "pointer",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ fontSize: 14, lineHeight: 1 }}>⬡</span>
          Agent GW
        </span>
        <span style={{ fontSize: 9, color: "var(--lm-text-muted)", transition: "transform 0.15s", transform: open ? "rotate(90deg)" : "none" }}>▶</span>
      </button>
      {open && (
        <div style={{ paddingLeft: 12 }}>
          <a href="/gw" style={S.navItem(false)} target="_blank" rel="noreferrer" onClick={closeSidebar}>
            <span style={{ fontSize: 12, lineHeight: 1 }}>↗</span>
            Gateway
          </a>
          <a href="/gw-config" style={S.navItem(false)} onClick={closeSidebar}>
            <span style={{ fontSize: 12, lineHeight: 1 }}>◈</span>
            GW Config
          </a>
        </div>
      )}
    </div>
  );
}

export default function Monitor() {
  const [theme, toggleTheme, themeClass] = useTheme();
  const [section, setSectionRaw] = useState<Section>(() => {
    const h = window.location.hash.replace("#", "") as Section;
    return allNavLeaves().some((n) => n.id === h) ? h : "overview";
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
  const [musicPlaying, setMusicPlaying] = useState(false);
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

  // Section ref so polling callback always sees current section without re-mounting
  const sectionRef = useRef(section);
  useEffect(() => { sectionRef.current = section; }, [section]);

  // Section-aware polling: only fetch APIs the active section needs
  useEffect(() => {
    const fetchForSection = async () => {
      const s = sectionRef.current;

      // Sidebar needs openclaw status + system info (version, uptime)
      try {
        const [ocR, sysR] = await Promise.all([
          fetch(`${API}/openclaw/status`).then((r) => r.json()),
          fetch(`${API}/system/info`).then((r) => r.json()),
        ]);
        if (ocR.status === 1) setOc(ocR.data);
        if (sysR.status === 1) {
          const d = sysR.data;
          setSys(d);
          if (s === "overview" || s === "system") {
            setCpuHistory((h) => [...h.slice(-(HISTORY_LEN - 1)), d.cpuLoad]);
            setRamHistory((h) => [...h.slice(-(HISTORY_LEN - 1)), d.memPercent]);
          }
        }
        setLastUpdate(new Date().toLocaleTimeString());
      } catch {}

      if (s === "overview" || s === "system") {
        try {
          const netR = await fetch(`${API}/system/network`).then((r) => r.json());
          if (netR.status === 1) setNet(netR.data);
        } catch {}
      }

      if (s === "overview") {
        try {
          const hwR = await fetch(`${HW}/health`).then((r) => r.json());
          setHw(hwR);
        } catch {}

        try {
          const presR = await fetch(`${HW}/presence`).then((r) => r.json());
          setPresence(presR);
        } catch {}

        try {
          const [voiceR, servoR, dispR, audioR, musicR, ledR] = await Promise.all([
            fetch(`${HW}/voice/status`).then((r) => r.json()),
            fetch(`${HW}/servo`).then((r) => r.json()),
            fetch(`${HW}/display`).then((r) => r.json()),
            fetch(`${HW}/audio/volume`).then((r) => r.json()),
            fetch(`${HW}/audio/status`).then((r) => r.json()),
            fetch(`${HW}/led/color`).then((r) => r.json()),
          ]);
          setVoice(voiceR);
          setServo(servoR);
          setDisplayState(dispR);
          setAudio(audioR);
          if (musicR.playing !== undefined) setMusicPlaying(musicR.playing);
          if (ledR.hex) setLedColor(ledR);
          setDisplayTs(Date.now());
        } catch {}

        try {
          const sceneR = await fetch(`${HW}/scene`).then((r) => r.json());
          if (sceneR.scenes) setSceneInfo(sceneR);
        } catch {}
      }
    };

    fetchForSection();
    const t = setInterval(fetchForSection, 3000);
    return () => clearInterval(t);
  }, []);

  // Flow data: only connect when flow or chat section is active
  useEffect(() => {
    const s = section;
    const needsFlow = s === "flow" || s === "chat";
    if (!needsFlow) return;

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
      } catch {}
    };

    fetchRecentFlow();
    es = new EventSource(`${API}/openclaw/flow-stream`);
    es.onmessage = (msg) => {
      try {
        const payload = JSON.parse(msg.data) as { events?: MonitorEvent[] };
        if (!Array.isArray(payload.events)) return;
        applyEvents(payload.events);
      } catch {}
    };
    es.onerror = () => {
      es?.close();
      es = null;
      if (!pollTimer) pollTimer = setInterval(fetchRecentFlow, 2000);
    };
    return () => {
      es?.close();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [section]);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const closeSidebar = () => setSidebarOpen(false);

  const ocOnline = oc?.connected ?? false;

  return (
    <div className={`lm-root ${themeClass}`} style={S.root}>
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
          {NAV.map((entry) =>
            isNavGroup(entry) ? (
              <NavGroupItem key={entry.group} entry={entry} section={section} setSection={setSection} closeSidebar={closeSidebar} />
            ) : (
              <a
                key={entry.id}
                href={`#${entry.id}`}
                style={S.navItem(section === entry.id)}
                onClick={(e) => { e.preventDefault(); setSection(entry.id); closeSidebar(); }}
              >
                <span style={{ fontSize: 14, lineHeight: 1 }}>{entry.icon}</span>
                {entry.label}
              </a>
            )
          )}
          <AgentGWMenu closeSidebar={closeSidebar} />
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
            <SoftwareUpdateButtons />
          </div>
          <button onClick={toggleTheme} style={{
            background: "none", border: "none", cursor: "pointer",
            fontSize: 13, color: "var(--lm-text-muted)", padding: "4px 0", marginTop: 4,
            textAlign: "left",
          }} title={`Theme: ${theme}`}>
            {theme === "dark" ? "◑ Dark" : "◐ Light"}
          </button>
        </div>
      </aside>

      {/* Main */}
      <main style={S.main}>
        {/* Mobile hamburger */}
        <button className="lm-hamburger" onClick={() => setSidebarOpen((v) => !v)} aria-label="Menu">☰</button>

        {/* Content */}
        <div style={{ ...S.content, ...(section === "chat" ? { padding: 0, overflow: "hidden" } : {}) }} className="lm-content lm-fade-in">
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
              musicPlaying={musicPlaying}
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
