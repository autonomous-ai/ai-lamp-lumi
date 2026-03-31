import { S } from "./styles";
import type { SystemInfo, NetworkInfo } from "./types";
import { GaugeRing, Sparkline, StatPill, formatUptime } from "./components";

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
