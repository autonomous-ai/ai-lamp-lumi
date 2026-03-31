import { useCallback, useEffect, useMemo, useState } from "react";
import { Bar, Line } from "react-chartjs-2";
import { S } from "./styles";
import { API } from "./types";

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

const VERSION_COLORS = [
  { border: "rgba(245,158,11,0.85)", bg: "rgba(245,158,11,0.15)" },
  { border: "rgba(96,165,250,0.85)",  bg: "rgba(96,165,250,0.15)" },
  { border: "rgba(168,85,247,0.85)", bg: "rgba(168,85,247,0.15)" },
  { border: "rgba(52,211,153,0.85)", bg: "rgba(52,211,153,0.15)" },
  { border: "rgba(45,212,191,0.85)", bg: "rgba(45,212,191,0.15)" },
  { border: "rgba(248,113,113,0.85)", bg: "rgba(248,113,113,0.15)" },
];

function vColor(i: number) {
  return VERSION_COLORS[i % VERSION_COLORS.length];
}

export function AnalyticsSection() {
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
  const labels = dates.map((d) => d.slice(5));
  const multiVersion = versions.length > 1;

  const rowMap = useMemo(() => {
    const m: Record<string, Record<string, VersionMetrics>> = {};
    for (const r of rows) {
      if (!m[r.date]) m[r.date] = {};
      m[r.date][r.version] = r.metrics;
    }
    return m;
  }, [rows]);

  const val = (date: string, ver: string, fn: (m: VersionMetrics) => number) => {
    const m = rowMap[date]?.[ver];
    return m ? fn(m) : 0;
  };

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
