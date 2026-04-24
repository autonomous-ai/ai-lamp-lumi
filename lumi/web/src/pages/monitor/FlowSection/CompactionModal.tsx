import { useEffect, useState } from "react";
import { API } from "../types";

type CompactionPayload = {
  found: boolean;
  sessionKey?: string;
  sessionFile?: string;
  compactionCount?: number;
  id?: string | number;
  parentId?: string | number;
  timestamp?: string;
  tokensBefore?: number;
  summaryChars?: number;
  summary?: string;
  details?: { readFiles?: string[]; modifiedFiles?: string[] } & Record<string, unknown>;
  fromHook?: boolean;
  firstKeptEntryId?: string | number;
};

type ApiEnvelope = {
  status?: number;
  data?: CompactionPayload;
  message?: string | null;
};

export function CompactionModal({ onClose }: { onClose: () => void }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<CompactionPayload | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const r = await fetch(`${API}/openclaw/compaction-latest`, { signal: ac.signal });
        const j: ApiEnvelope = await r.json();
        if (!r.ok || j?.status !== 1 || !j.data) {
          throw new Error(j?.message || `HTTP ${r.status}`);
        }
        setData(j.data);
      } catch (e) {
        if ((e as { name?: string })?.name === "AbortError") return;
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
    return () => ac.abort();
  }, []);

  const tsLocal = data?.timestamp ? new Date(data.timestamp).toLocaleString() : "";

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
          borderRadius: 16, padding: 24, maxWidth: 960, width: "92vw",
          maxHeight: "88vh", display: "flex", flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" as const }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: "var(--lm-text)" }}>📋 Active Compaction Summary</span>
            <span style={{ fontSize: 11, color: "var(--lm-amber)", fontWeight: 600 }}>
              ⚡ injected at top of every agent turn until the next compact
            </span>
          </div>
          <button onClick={onClose} style={{
            background: "none", border: "none", color: "var(--lm-text-muted)",
            cursor: "pointer", fontSize: 16, lineHeight: 1,
          }}>✕</button>
        </div>

        <div style={{
          flex: 1, minHeight: 0, overflow: "auto",
          display: "flex", flexDirection: "column" as const,
        }}>

        {loading && (
          <div style={{ padding: 24, textAlign: "center", color: "var(--lm-text-muted)", fontSize: 12 }}>
            Loading…
          </div>
        )}

        {error && !loading && (
          <div style={{
            padding: 12, borderRadius: 8, fontSize: 12,
            background: "rgba(248,113,113,0.12)", color: "var(--lm-red)",
            border: "1px solid rgba(248,113,113,0.35)",
          }}>
            {error}
          </div>
        )}

        {!loading && !error && data && !data.found && (
          <div style={{ padding: 16, fontSize: 12, color: "var(--lm-text-muted)" }}>
            No compaction record yet in <code>{data.sessionFile}</code>.
          </div>
        )}

        {!loading && !error && data && data.found && (
          <>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: 8, marginBottom: 14, fontSize: 11,
            }}>
              <Field label="timestamp" value={tsLocal} mono />
              <Field label="summary chars" value={String(data.summaryChars ?? "?")} mono />
              <Field label="session file" value={data.sessionFile ?? "?"} mono />
            </div>

            <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.4 }}>
              summary
            </div>
            <pre style={{
              margin: 0,
              padding: 12, borderRadius: 8,
              background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
              color: "var(--lm-text)", fontSize: 12, lineHeight: 1.5,
              whiteSpace: "pre-wrap", wordBreak: "break-word",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}>{data.summary}</pre>
          </>
        )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{
      padding: "6px 10px", borderRadius: 6,
      background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
    }}>
      <div style={{ fontSize: 9, color: "var(--lm-text-muted)", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{
        fontSize: 11, color: "var(--lm-text)", fontWeight: 600,
        fontFamily: mono ? "ui-monospace, SFMono-Regular, Menlo, monospace" : undefined,
        wordBreak: "break-all",
      }}>{value}</div>
    </div>
  );
}
