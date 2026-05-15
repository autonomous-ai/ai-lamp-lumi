import { useEffect, useState } from "react";
import { S } from "./styles";
import type { SystemInfo, NetworkInfo } from "./types";
import { GaugeRing, Sparkline, StatPill, formatUptime, formatSize } from "./components";

// Temperature tier: matches Pi thermal behavior (throttle ~80°C, warning ~70°C).
// Scale uses 80°C as full-circle so the ring visually reaches red as it fills.
const TEMP_MAX = 80;
function tempColor(t: number): string {
  if (t > 70) return "var(--lm-red)";
  if (t > 60) return "var(--lm-amber)";
  return "var(--lm-teal)";
}

export function SystemSection({
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
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  useEffect(() => { if (sys) setLastUpdate(new Date()); }, [sys]);

  if (!sys) return <div style={{ color: "var(--lm-text-muted)", padding: 20 }}>Loading system data…</div>;

  const diskColor = (sys.diskPercent ?? 0) > 90 ? "var(--lm-red)" : (sys.diskPercent ?? 0) > 75 ? "var(--lm-amber)" : "var(--lm-teal)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Performance — one card per metric so each gets a clean visual unit.
          CPU card includes a compact per-core strip so spikes pinned to a single
          core (e.g. STT thread) are visible against an otherwise low aggregate. */}
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <span style={{ fontSize: 10, color: "var(--lm-text-muted)" }}>
          updated {lastUpdate.toLocaleTimeString()}
        </span>
      </div>
      {/* Row 1: CPU + CPU history */}
      <div className="lm-grid-2">
        <div style={{ ...S.card, padding: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={S.cardLabel}>CPU</div>
            <span style={{ fontSize: 11, color: "var(--lm-amber)", fontWeight: 600 }}>
              {sys.cpuCount ? `${sys.cpuCount} cores` : ""}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
            <GaugeRing value={sys.cpuLoad} label="" detail={`${sys.cpuLoad.toFixed(1)}%`} color="var(--lm-amber)" size={140} />
            {sys.cpuPerCore && sys.cpuPerCore.length > 0 && (
              <CoreStrip values={sys.cpuPerCore} />
            )}
          </div>
        </div>
        <div style={{ ...S.card, padding: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={S.cardLabel}>CPU History</div>
            <span style={{ fontSize: 11, color: "var(--lm-amber)", fontWeight: 600 }}>{sys.cpuLoad.toFixed(1)}%</span>
          </div>
          <Sparkline data={cpuHistory} color="var(--lm-amber)" height={140} max={100} grid />
        </div>
      </div>

      {/* Row 2: Memory + RAM history */}
      <div className="lm-grid-2">
        <div style={{ ...S.card, padding: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={S.cardLabel}>Memory</div>
            <span style={{ fontSize: 11, color: "var(--lm-blue)", fontWeight: 600 }}>
              {formatSize(sys.memUsed, "KB")} / {formatSize(sys.memTotal, "KB")}
            </span>
          </div>
          <div style={{ display: "flex", justifyContent: "center" }}>
            <GaugeRing value={sys.memPercent} label="" detail={`${sys.memPercent.toFixed(0)}%`} color="var(--lm-blue)" size={140} />
          </div>
        </div>
        <div style={{ ...S.card, padding: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={S.cardLabel}>RAM History</div>
            <span style={{ fontSize: 11, color: "var(--lm-blue)", fontWeight: 600 }}>{sys.memPercent.toFixed(0)}%</span>
          </div>
          <Sparkline data={ramHistory} color="var(--lm-blue)" height={140} max={100} grid />
        </div>
      </div>

      {/* Row 3: Disk + Temp */}
      <div className="lm-grid-2">
        <div style={{ ...S.card, padding: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={S.cardLabel}>Disk</div>
            <span style={{ fontSize: 11, color: diskColor, fontWeight: 600 }}>
              {formatSize(sys.diskUsed ?? 0, "MB")} / {formatSize(sys.diskTotal ?? 0, "MB")}
            </span>
          </div>
          <div style={{ display: "flex", justifyContent: "center" }}>
            <GaugeRing value={sys.diskPercent ?? 0} label="" detail={`${(sys.diskPercent ?? 0).toFixed(0)}%`} color={diskColor} size={140} />
          </div>
        </div>
        <div style={{ ...S.card, padding: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={S.cardLabel}>Temp</div>
            <span style={{ fontSize: 11, color: tempColor(sys.cpuTemp), fontWeight: 600 }}>{sys.cpuTemp.toFixed(1)}°C</span>
          </div>
          <div style={{ display: "flex", justifyContent: "center" }}>
            <GaugeRing
              value={sys.cpuTemp > 0 ? Math.min(100, (sys.cpuTemp / TEMP_MAX) * 100) : 0}
              label=""
              detail={`${sys.cpuTemp.toFixed(1)}°C`}
              color={tempColor(sys.cpuTemp)}
              size={140}
            />
          </div>
        </div>
      </div>

      {/* Detail stats — version+SSID/IP already on Overview, so focus on uptimes + extended network. */}
      <div className="lm-grid-2">
        <div style={S.card}>
          <div style={S.cardLabel}>Service</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <StatPill label="OS Uptime"       value={formatUptime(sys.uptime)}                                                  bullet="var(--lm-text-dim)" />
            <StatPill label="Lumi Uptime"     value={sys.serviceUptime ? formatUptime(sys.serviceUptime) : "—"} color="var(--lm-amber)" bullet="var(--lm-amber)" />
            <StatPill label="Go Routines"     value={sys.goRoutines}                                            color="var(--lm-amber)" bullet="var(--lm-amber)" />
            <StatPill label="Hardware Uptime" value={sys.lelampUptime ? formatUptime(sys.lelampUptime) : "—"}   color="var(--lm-blue)"  bullet="var(--lm-blue)" />
            <DeviceIdPill deviceId={sys.deviceId} />
          </div>
        </div>

        <div style={S.card}>
          <div style={S.cardLabel}>Network Detail</div>
          {net ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <StatPill label="Link Rate"    value={net.linkRate > 0 ? `${net.linkRate} Mbps` : "—"} color="var(--lm-teal)" />
              <StatPill label="Signal"       value={net.signal !== 0 ? `${net.signal} dBm` : "—"} />
              <StatPill label="Public IP"    value={net.publicIp || "—"} color="var(--lm-amber)" />
              <StatPill label="Tailscale IP" value={net.tailscaleIp || "—"} color={net.tailscaleIp ? "var(--lm-teal)" : undefined} />
              <StatPill label="MAC"          value={net.mac || "—"} />
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>No network data</span>}
        </div>
      </div>
    </div>
  );
}

// CoreStrip renders per-core load as small vertical bars side by side —
// the compact "CPU history" look from system monitors. Hover for exact %.
function CoreStrip({ values }: { values: number[] }) {
  const coreColor = (p: number) =>
    p > 85 ? "var(--lm-red)" : p > 60 ? "var(--lm-amber)" : "var(--lm-teal)";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, width: "100%" }}>
      <div style={{
        display: "flex",
        gap: 3,
        alignItems: "flex-end",
        height: 22,
        padding: "0 4px",
      }}>
        {values.map((p, i) => {
          const clamped = Math.max(0, Math.min(100, p));
          const c = coreColor(clamped);
          return (
            <div
              key={i}
              title={`Core ${i}: ${clamped.toFixed(0)}%`}
              style={{
                width: 7,
                height: "100%",
                background: "var(--lm-surface)",
                borderRadius: 2,
                position: "relative",
                overflow: "hidden",
              }}
            >
              <div style={{
                position: "absolute",
                left: 0,
                right: 0,
                bottom: 0,
                height: `${Math.max(4, clamped)}%`,
                background: c,
                transition: "height 0.6s ease, background 0.3s ease",
              }} />
            </div>
          );
        })}
      </div>
      <span style={{ fontSize: 9.5, color: "var(--lm-text-muted)", letterSpacing: 0.3 }}>per-core</span>
    </div>
  );
}

// DeviceIdPill shows the full ID truncated, with click-to-copy.
function DeviceIdPill({ deviceId }: { deviceId: string }) {
  const [copied, setCopied] = useState(false);
  if (!deviceId) {
    return <StatPill label="Device ID" value="—" />;
  }
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(deviceId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* ignore */ }
  };
  return (
    <div
      onClick={onCopy}
      title="Click to copy"
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 10,
        padding: "6px 12px",
        background: "var(--lm-surface)",
        borderRadius: 8,
        border: "1px solid var(--lm-border)",
        cursor: "pointer",
      }}
    >
      <span style={{ fontSize: 11.5, color: "var(--lm-text-dim)", flexShrink: 0 }}>Device ID</span>
      <span style={{
        fontSize: 11,
        fontWeight: 600,
        fontFamily: "monospace",
        color: copied ? "var(--lm-green)" : "var(--lm-text)",
        wordBreak: "break-all",
        textAlign: "right",
      }}>
        {copied ? "copied!" : deviceId}
      </span>
    </div>
  );
}
