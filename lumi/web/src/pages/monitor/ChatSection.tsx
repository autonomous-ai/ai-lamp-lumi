import { useEffect, useRef, useState } from "react";
import { API } from "./types";
import type { DisplayEvent } from "./types";

const STORAGE_KEY = "lumi_chat_history";
const MAX_STORED = 200;

interface ChatMessage {
  id: string;
  role: "user" | "lumi";
  text: string;
  time: string;
  runId?: string;
  pending?: boolean;
  error?: boolean;
}

function loadMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const msgs = JSON.parse(raw) as ChatMessage[];
    // Clear any pending/error states from a previous session
    return msgs.map((m) =>
      m.pending ? { ...m, pending: false, text: "…", error: true } : m,
    );
  } catch {
    return [];
  }
}

function saveMessages(msgs: ChatMessage[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(msgs.slice(-MAX_STORED)));
  } catch {}
}

interface Props {
  events: DisplayEvent[];
}

// Extract the final response text from a flow event.
// Priority: tts_send (full assembled text) > chat_response complete > no_reply
function extractResponse(ev: DisplayEvent): { text: string; final: boolean } | null {
  const d = ev.detail as Record<string, any> | undefined;

  // tts_send = the fully-assembled assistant text that gets spoken — most reliable
  if (ev.type === "flow_event" && d?.node === "tts_send") {
    const text: string = d?.data?.text ?? d?.text ?? "";
    if (text) return { text, final: true };
  }

  // no_reply flow event
  if (ev.type === "flow_event" && d?.node === "no_reply") {
    return { text: "…", final: true };
  }

  // chat_response with state=complete (full message from chat stream)
  if (ev.type === "chat_response" && (ev.state === "complete" || ev.state === "final")) {
    const msg: string = d?.message ?? ev.summary ?? "";
    if (msg && msg !== "[no reply]") return { text: msg, final: true };
    if (msg === "[no reply]") return { text: "…", final: true };
  }

  // chat_response NO_REPLY from lifecycle_end path
  if (ev.type === "chat_response" && d?.message === "[no reply]") {
    return { text: "…", final: true };
  }

  return null;
}

export function ChatSection({ events }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  // runId we're currently waiting on
  const pendingRunIdRef = useRef<string | null>(null);
  // runIds already resolved (avoid double-applying)
  const resolvedIds = useRef<Set<string>>(new Set());

  // Persist messages to localStorage on every change
  useEffect(() => { saveMessages(messages); }, [messages]);

  // Watch flow events for Lumi's response
  useEffect(() => {
    const pending = pendingRunIdRef.current;
    if (!pending || resolvedIds.current.has(pending)) return;

    for (const ev of [...events].reverse()) {
      // Resolve event runId (may be in different fields)
      const evRunId: string | undefined =
        ev.runId ??
        (ev.detail as any)?.run_id ??
        (ev.detail as any)?.runId ??
        (ev.detail as any)?.data?.run_id;

      if (!evRunId || evRunId !== pending) continue;

      const result = extractResponse(ev);
      if (!result) continue;

      // Found a final response for this runId
      resolvedIds.current.add(pending);
      pendingRunIdRef.current = null;
      setSending(false);
      setMessages((prev) =>
        prev.map((m) =>
          m.runId === pending && m.role === "lumi" && m.pending
            ? { ...m, text: result.text, pending: false }
            : m,
        ),
      );
      break;
    }
  }, [events]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;

    const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", text, time: now }]);
    setInput("");
    setSending(true);

    try {
      const res = await fetch(`${API}/sensing/event`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "voice", message: text }),
      });
      const json = await res.json();

      if (json.status === 1 && json.data?.runId) {
        const runId: string = json.data.runId;
        pendingRunIdRef.current = runId;
        const replyTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        setMessages((prev) => [
          ...prev,
          { id: `l-${runId}`, role: "lumi", text: "", time: replyTime, runId, pending: true },
        ]);
        // Safety timeout
        setTimeout(() => {
          if (pendingRunIdRef.current === runId) {
            pendingRunIdRef.current = null;
            setSending(false);
            setMessages((prev) =>
              prev.map((m) =>
                m.runId === runId && m.pending
                  ? { ...m, text: "⏱ no response", pending: false, error: true }
                  : m,
              ),
            );
          }
        }, 30_000);
      } else if (json.data?.handler === "local") {
        setSending(false);
        setMessages((prev) => [
          ...prev,
          { id: `l-local-${Date.now()}`, role: "lumi", text: "✓ handled locally", time: now },
        ]);
      } else if (json.data?.handler === "dropped") {
        setSending(false);
        setMessages((prev) => [
          ...prev,
          { id: `l-drop-${Date.now()}`, role: "lumi", text: "⏸ busy — try again", time: now, error: true },
        ]);
      } else {
        setSending(false);
        setMessages((prev) => [
          ...prev,
          { id: `l-err-${Date.now()}`, role: "lumi", text: json.message ?? "error", time: now, error: true },
        ]);
      }
    } catch {
      setSending(false);
      setMessages((prev) => [
        ...prev,
        { id: `l-err-${Date.now()}`, role: "lumi", text: "connection error", time: now, error: true },
      ]);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", maxWidth: 720, margin: "0 auto" }}>
      {/* Header */}
      {messages.length > 0 && (
        <div style={{ padding: "8px 16px", borderBottom: "1px solid var(--lm-border)", display: "flex", justifyContent: "flex-end" }}>
          <button
            onClick={() => { setMessages([]); localStorage.removeItem(STORAGE_KEY); }}
            style={{ fontSize: 11, color: "var(--lm-text-muted)", background: "none", border: "none", cursor: "pointer", padding: "2px 6px" }}
          >clear history</button>
        </div>
      )}
      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 16px 8px", display: "flex", flexDirection: "column", gap: 12 }}>
        {messages.length === 0 && (
          <div style={{ margin: "auto", textAlign: "center", color: "var(--lm-text-muted)", fontSize: 13, lineHeight: 1.8 }}>
            <div style={{ fontSize: 28, marginBottom: 10 }}>✦</div>
            <div>Chat with Lumi</div>
            <div style={{ fontSize: 11, marginTop: 4 }}>Messages are sent as voice commands</div>
          </div>
        )}
        {messages.map((msg) => (
          <div key={msg.id} style={{ display: "flex", flexDirection: msg.role === "user" ? "row-reverse" : "row", alignItems: "flex-end", gap: 8 }}>
            {msg.role === "lumi" && (
              <div style={{
                width: 28, height: 28, borderRadius: "50%",
                background: "var(--lm-amber-dim)", border: "1px solid rgba(245,158,11,0.3)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 12, flexShrink: 0, color: "var(--lm-amber)",
              }}>✦</div>
            )}
            <div style={{ maxWidth: "72%", display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start", gap: 3 }}>
              <div style={{
                padding: "9px 13px",
                borderRadius: msg.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
                background: msg.role === "user" ? "rgba(245,158,11,0.15)" : "var(--lm-surface)",
                border: `1px solid ${msg.role === "user" ? "rgba(245,158,11,0.25)" : "var(--lm-border)"}`,
                color: msg.error ? "var(--lm-red)" : "var(--lm-text)",
                fontSize: 13, lineHeight: 1.55, wordBreak: "break-word",
                minWidth: 40, minHeight: 36,
              }}>
                {msg.pending ? (
                  <span style={{ color: "var(--lm-text-muted)" }}>
                    <span className="lm-blink">●</span>
                    <span style={{ marginLeft: 4 }}>●</span>
                    <span style={{ marginLeft: 4 }}>●</span>
                  </span>
                ) : msg.text}
              </div>
              <div style={{ fontSize: 10, color: "var(--lm-text-muted)", paddingInline: 4 }}>{msg.time}</div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: "12px 16px", borderTop: "1px solid var(--lm-border)", display: "flex", gap: 8, background: "var(--lm-sidebar)" }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={sending}
          placeholder="Send a message to Lumi…"
          style={{
            flex: 1, background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
            borderRadius: 8, padding: "9px 13px", color: "var(--lm-text)", fontSize: 13,
            outline: "none", opacity: sending ? 0.6 : 1,
          }}
        />
        <button
          onClick={send}
          disabled={!input.trim() || sending}
          style={{
            padding: "9px 16px", borderRadius: 8, flexShrink: 0,
            background: input.trim() && !sending ? "rgba(245,158,11,0.2)" : "var(--lm-surface)",
            border: `1px solid ${input.trim() && !sending ? "rgba(245,158,11,0.4)" : "var(--lm-border)"}`,
            color: input.trim() && !sending ? "var(--lm-amber)" : "var(--lm-text-muted)",
            fontSize: 13, fontWeight: 600, cursor: input.trim() && !sending ? "pointer" : "default",
            transition: "all 0.15s",
          }}
        >{sending ? "…" : "Send"}</button>
      </div>
    </div>
  );
}
