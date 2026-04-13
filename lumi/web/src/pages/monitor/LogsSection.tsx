import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { S } from "./styles";
import { API } from "./types";

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
  }, [source, paused, fetchLines]);

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

export function LogsSection() {
  const [active, setActive] = useState<LogSource>("openclaw");

  const src = LOG_SOURCES.find((s) => s.id === active)!;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0, height: "100%" }}>
      <div style={{ display: "flex", gap: 4, padding: "0 0 8px 0", flexShrink: 0 }}>
        {LOG_SOURCES.map((s) => (
          <button
            key={s.id}
            onClick={() => setActive(s.id)}
            style={{
              fontSize: 11, padding: "4px 12px", borderRadius: 6, cursor: "pointer",
              border: active === s.id ? `1px solid ${s.color}` : "1px solid var(--lm-border)",
              background: active === s.id ? `${s.color}22` : "var(--lm-surface)",
              color: active === s.id ? s.color : "var(--lm-text-dim)",
              fontWeight: active === s.id ? 700 : 400,
              transition: "all 0.15s",
            }}
          >
            <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: s.color, marginRight: 5, verticalAlign: "middle" }} />
            {s.label}
          </button>
        ))}
      </div>
      <LogPanel key={active} source={src.id} label={src.label} color={src.color} />
    </div>
  );
}
