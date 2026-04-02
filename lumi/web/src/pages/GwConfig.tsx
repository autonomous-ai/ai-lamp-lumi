import { useEffect, useState } from "react";

const API = "/api";

const C = {
  bg:        "var(--lm-bg)",
  sidebar:   "var(--lm-sidebar)",
  border:    "var(--lm-border)",
  text:      "var(--lm-text)",
  textMuted: "var(--lm-text-muted)",
  textDim:   "var(--lm-text-dim)",
  card:      "var(--lm-card)",
  amber:     "var(--lm-amber)",
  teal:      "var(--lm-teal)",
};

export default function GwConfig() {
  const [raw, setRaw] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/openclaw/config-json`)
      .then((r) => r.json())
      .then((res) => {
        if (res.status === 1) {
          setRaw(JSON.stringify(res.data, null, 2));
        } else {
          setError(res.message ?? "Failed to load config");
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.text, fontFamily: "monospace" }}>
      {/* Topbar */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 20px",
        background: C.sidebar,
        borderBottom: `1px solid ${C.border}`,
      }}>
        <a href="/monitor" style={{ color: C.textMuted, textDecoration: "none", fontSize: 13 }}>
          ← Monitor
        </a>
        <span style={{ color: C.border }}>|</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: C.teal }}>⬡ openclaw.json</span>
      </div>

      {/* Content */}
      <div style={{ padding: "24px 28px", maxWidth: 900 }}>
        {loading && (
          <div style={{ color: C.textMuted, fontSize: 13 }}>Loading...</div>
        )}
        {error && (
          <div style={{
            padding: "12px 16px",
            background: "rgba(248,113,113,0.08)",
            border: "1px solid rgba(248,113,113,0.25)",
            borderRadius: 6,
            color: "var(--lm-red)",
            fontSize: 12,
          }}>
            {error}
          </div>
        )}
        {raw && (
          <pre style={{
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            padding: "16px 20px",
            fontSize: 12,
            lineHeight: 1.7,
            color: C.text,
            overflowX: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            margin: 0,
          }}>
            {raw}
          </pre>
        )}
      </div>
    </div>
  );
}
