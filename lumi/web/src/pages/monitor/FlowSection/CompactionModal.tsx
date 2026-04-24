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
  const [showHow, setShowHow] = useState(true);

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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: "var(--lm-text)" }}>📋 Active Compaction Summary</span>
            <span style={{ fontSize: 11, color: "var(--lm-text-muted)" }}>
              chèn đầu prompt mỗi turn agent cho đến lần compact kế
            </span>
          </div>
          <button onClick={onClose} style={{
            background: "none", border: "none", color: "var(--lm-text-muted)",
            cursor: "pointer", fontSize: 16, lineHeight: 1,
          }}>✕</button>
        </div>

        <div style={{
          marginBottom: 14, borderRadius: 10,
          background: "rgba(167,139,250,0.08)", border: "1px solid rgba(167,139,250,0.35)",
          overflow: "hidden",
        }}>
          <button
            onClick={() => setShowHow((v) => !v)}
            style={{
              width: "100%", padding: "8px 12px",
              display: "flex", alignItems: "center", justifyContent: "space-between",
              background: "transparent", border: "none", cursor: "pointer",
              color: "var(--lm-purple)", fontSize: 11, fontWeight: 700,
              textTransform: "uppercase" as const, letterSpacing: 0.4,
            }}
          >
            <span>❓ Compact hoạt động thế nào</span>
            <span style={{ fontSize: 10 }}>{showHow ? "▼ ẩn" : "▶ mở"}</span>
          </button>
          {showHow && (
            <div style={{ padding: "0 14px 14px", fontSize: 11.5, color: "var(--lm-text-dim)", lineHeight: 1.6 }}>
              <div style={{ marginBottom: 10, fontSize: 12, color: "var(--lm-text)" }}>
                <b>Vì sao có compact?</b> OpenClaw agent giữ conversation history dài (mỗi turn = user event + thinking + tools + reply). Khi tổng context chạm <b>~80k tokens</b>, LLM không nhét thêm được nữa → OpenClaw auto-compact.
              </div>

              <div style={{ marginBottom: 10 }}>
                <b style={{ color: "var(--lm-text)" }}>Quy trình compact (fromHook = true):</b>
                <pre style={{
                  margin: "6px 0 0", padding: 10, borderRadius: 6,
                  background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                  fontSize: 10.5, lineHeight: 1.55, color: "var(--lm-text-dim)",
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                }}>{
`1. Hook fire khi tokens ≥ 80k
2. OpenClaw đọc history + một số file (KNOWLEDGE.md, HEARTBEAT.md, SKILL active…)
3. Gọi LLM riêng để tóm tắt → sinh 1 chuỗi "summary" (≤ ~16000 chars)
4. Ghi 1 dòng JSONL type:"compaction" vào session file, kèm:
     • firstKeptEntryId  (mốc chia)
     • tokensBefore       (~80k)
     • readFiles[]        (file đã đọc vào prompt compact)
5. Từ turn kế tiếp, history < firstKeptEntryId KHÔNG còn gửi lên LLM;
   summary được chèn thay vào vị trí đó.`
                }</pre>
              </div>

              <div style={{ marginBottom: 10 }}>
                <b style={{ color: "var(--lm-text)" }}>Prompt mỗi turn TRƯỚC vs SAU compact:</b>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 6 }}>
                  <pre style={{
                    margin: 0, padding: 10, borderRadius: 6, fontSize: 10.5,
                    background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                    color: "var(--lm-text-dim)", whiteSpace: "pre-wrap",
                  }}>{
`TRƯỚC:
[system prompt]
[SOUL.md / AGENTS.md]
[history entries
 ... turn 1
 ... turn 2
 ...
 ... turn N]
[SKILL.md load theo event]
[user event mới]`
                  }</pre>
                  <pre style={{
                    margin: 0, padding: 10, borderRadius: 6, fontSize: 10.5,
                    background: "rgba(167,139,250,0.10)", border: "1px solid rgba(167,139,250,0.45)",
                    color: "var(--lm-text)", whiteSpace: "pre-wrap",
                  }}>{
`SAU compact:
[system prompt]
[SOUL.md / AGENTS.md]
[📋 SUMMARY ~3–4k tokens]  ← NEW
[kept entries sau
 firstKeptEntryId]
[SKILL.md load theo event]
[user event mới]`
                  }</pre>
                </div>
              </div>

              <div style={{ marginBottom: 10 }}>
                <b style={{ color: "var(--lm-text)" }}>Tần suất thực tế (quan sát 48h):</b>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  <li>Busy ban ngày: <b>1–3h/lần</b></li>
                  <li>Qua đêm idle: <b>10–13h/lần</b></li>
                  <li>Thỉnh thoảng cluster bất thường: nhiều lần compact trong vài phút ở tokens thấp (~45–60k)</li>
                </ul>
              </div>

              <div style={{
                padding: 10, borderRadius: 6,
                background: "rgba(248,113,113,0.10)", border: "1px solid rgba(248,113,113,0.35)",
                color: "var(--lm-text)",
              }}>
                <b style={{ color: "var(--lm-red)" }}>⚠ Vì sao summary có thể làm agent sai:</b>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  <li>Summary đứng <b>trước</b> SKILL.md trong prompt → LLM coi là "fact đã chốt", trọng số cao hơn.</li>
                  <li>Quá trình tóm tắt có thể <b>generalize</b> case hẹp thành rule chung, hoặc <b>đóng băng</b> giá trị cũ (vd <code>last=50</code>) trong khi SKILL đã update (<code>last=200</code>).</li>
                  <li>Lần compact kế đọc lại summary cũ + KNOWLEDGE.md → <b>generational loss</b>, rule méo lan truyền.</li>
                  <li>Cap 16000 chars → rule bị drop ngẫu nhiên khi summary đụng trần.</li>
                </ul>
              </div>
            </div>
          )}
        </div>

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
              gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
              gap: 8, marginBottom: 14, fontSize: 11,
            }}>
              <Field label="timestamp" value={tsLocal} mono />
              <Field label="tokensBefore" value={String(data.tokensBefore ?? "?")} mono />
              <Field label="summary chars" value={String(data.summaryChars ?? "?")} mono />
              <Field label="compaction count" value={String(data.compactionCount ?? "?")} mono />
              <Field label="fromHook" value={data.fromHook ? "true" : "false"} mono />
              <Field label="firstKeptEntryId" value={String(data.firstKeptEntryId ?? "?")} mono />
            </div>

            {Array.isArray(data.details?.readFiles) && data.details!.readFiles!.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.4 }}>
                  readFiles (fed into compaction prompt)
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {data.details!.readFiles!.map((f) => (
                    <span key={f} style={{
                      fontSize: 10, padding: "2px 8px", borderRadius: 4,
                      background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                      color: "var(--lm-text-dim)", fontFamily: "monospace",
                    }}>{f}</span>
                  ))}
                </div>
              </div>
            )}

            <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.4 }}>
              summary
            </div>
            <pre style={{
              flex: 1, overflow: "auto", margin: 0,
              padding: 12, borderRadius: 8,
              background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
              color: "var(--lm-text)", fontSize: 12, lineHeight: 1.5,
              whiteSpace: "pre-wrap", wordBreak: "break-word",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}>{data.summary}</pre>

            <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginTop: 8 }}>
              {data.sessionFile}
            </div>
          </>
        )}
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
