import { useEffect, useRef, useState } from "react";
import { API } from "./types";
import type { DisplayEvent } from "./types";

interface ChatMessage {
  id: string;
  role: "user" | "lumi";
  text: string;
  time: string;
  runId?: string;
  pending?: boolean;
  error?: boolean;
}

interface Props {
  events: DisplayEvent[];
}

function extractResponseText(ev: DisplayEvent): string | null {
  const d = ev.detail as Record<string, any> | undefined;
  if (ev.type === "chat_response") {
    const msg = d?.message ?? d?.data?.message;
    if (msg) return msg;
  }
  if (ev.type === "tts_speak" || ev.type === "tts") {
    const text = d?.text ?? d?.data?.text ?? ev.summary;
    if (text && !text.startsWith("[")) return text;
  }
  return null;
}

export function ChatSection({ events }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pendingRunIdRef = useRef<string | null>(null);
  const respondedRunIds = useRef<Set<string>>(new Set());

  // Watch flow events for Lumi's response
  useEffect(() => {
    const pending = pendingRunIdRef.current;
    if (!pending) return;

    for (const ev of [...events].reverse()) {
      const evRunId =
        ev.runId ??
        (ev.detail as any)?.run_id ??
        (ev.detail as any)?.runId ??
        (ev.detail as any)?.data?.run_id;

      if (evRunId !== pending) continue;
      if (respondedRunIds.current.has(pending)) break;

      const text = extractResponseText(ev);
      if (text) {
        respondedRunIds.current.add(pending);
        pendingRunIdRef.current = null;
        setSending(false);
        setMessages((prev) =>
          prev.map((m) =>
            m.runId === pending && m.role === "lumi"
              ? { ...m, text, pending: false }
              : m,
          ),
        );
        break;
      }

      // lifecycle_end with NO_REPLY
      if (
        ev.type === "flow_event" &&
        (ev.detail as any)?.node === "lifecycle_end"
      ) {
        const d = ev.detail as any;
        const noReply =
          d?.data?.message === "NO_REPLY" ||
          d?.message === "NO_REPLY" ||
          ev.summary?.includes("NO_REPLY");
        if (noReply && !respondedRunIds.current.has(pending)) {
          respondedRunIds.current.add(pending);
          pendingRunIdRef.current = null;
          setSending(false);
          setMessages((prev) =>
            prev.map((m) =>
              m.runId === pending && m.role === "lumi"
                ? { ...m, text: "…", pending: false }
                : m,
            ),
          );
          break;
        }
      }
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
    const msgId = `msg-${Date.now()}`;

    setMessages((prev) => [
      ...prev,
      { id: msgId, role: "user", text, time: now },
    ]);
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
        setMessages((prev) => [
          ...prev,
          {
            id: `lumi-${runId}`,
            role: "lumi",
            text: "",
            time: now,
            runId,
            pending: true,
          },
        ]);
        // Safety timeout — give up waiting after 30s
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
        // Handled by local intent — no agent response
        setSending(false);
        setMessages((prev) => [
          ...prev,
          {
            id: `lumi-local-${Date.now()}`,
            role: "lumi",
            text: "✓ handled locally",
            time: now,
          },
        ]);
      } else {
        setSending(false);
        setMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: "lumi",
            text: json.message ?? "error sending message",
            time: now,
            error: true,
          },
        ]);
      }
    } catch (e) {
      setSending(false);
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "lumi",
          text: "connection error",
          time: now,
          error: true,
        },
      ]);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", maxWidth: 720, margin: "0 auto" }}>
      {/* Messages */}
      <div style={{
        flex: 1,
        overflowY: "auto",
        padding: "20px 16px 8px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}>
        {messages.length === 0 && (
          <div style={{
            margin: "auto",
            textAlign: "center",
            color: "var(--lm-text-muted)",
            fontSize: 13,
            lineHeight: 1.8,
          }}>
            <div style={{ fontSize: 28, marginBottom: 10 }}>✦</div>
            <div>Chat with Lumi</div>
            <div style={{ fontSize: 11, marginTop: 4 }}>Messages are sent as voice commands</div>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              display: "flex",
              flexDirection: msg.role === "user" ? "row-reverse" : "row",
              alignItems: "flex-end",
              gap: 8,
            }}
          >
            {/* Avatar */}
            {msg.role === "lumi" && (
              <div style={{
                width: 28,
                height: 28,
                borderRadius: "50%",
                background: "var(--lm-amber-dim)",
                border: "1px solid rgba(245,158,11,0.3)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 12,
                flexShrink: 0,
                color: "var(--lm-amber)",
              }}>✦</div>
            )}
            {/* Bubble */}
            <div style={{ maxWidth: "72%", display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start", gap: 3 }}>
              <div style={{
                padding: "9px 13px",
                borderRadius: msg.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
                background: msg.role === "user"
                  ? "rgba(245,158,11,0.15)"
                  : "var(--lm-surface)",
                border: `1px solid ${msg.role === "user" ? "rgba(245,158,11,0.25)" : "var(--lm-border)"}`,
                color: msg.error ? "var(--lm-red)" : "var(--lm-text)",
                fontSize: 13,
                lineHeight: 1.55,
                wordBreak: "break-word",
                minWidth: 40,
                minHeight: 36,
              }}>
                {msg.pending ? (
                  <span style={{ color: "var(--lm-text-muted)" }}>
                    <span className="lm-blink">●</span>
                    <span style={{ marginLeft: 4 }}>●</span>
                    <span style={{ marginLeft: 4 }}>●</span>
                  </span>
                ) : (
                  msg.text
                )}
              </div>
              <div style={{ fontSize: 10, color: "var(--lm-text-muted)", paddingInline: 4 }}>{msg.time}</div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div style={{
        padding: "12px 16px",
        borderTop: "1px solid var(--lm-border)",
        display: "flex",
        gap: 8,
        background: "var(--lm-sidebar)",
      }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={sending}
          placeholder="Send a message to Lumi…"
          style={{
            flex: 1,
            background: "var(--lm-surface)",
            border: "1px solid var(--lm-border)",
            borderRadius: 8,
            padding: "9px 13px",
            color: "var(--lm-text)",
            fontSize: 13,
            outline: "none",
            opacity: sending ? 0.6 : 1,
          }}
        />
        <button
          onClick={send}
          disabled={!input.trim() || sending}
          style={{
            padding: "9px 16px",
            borderRadius: 8,
            background: input.trim() && !sending ? "rgba(245,158,11,0.2)" : "var(--lm-surface)",
            border: `1px solid ${input.trim() && !sending ? "rgba(245,158,11,0.4)" : "var(--lm-border)"}`,
            color: input.trim() && !sending ? "var(--lm-amber)" : "var(--lm-text-muted)",
            fontSize: 13,
            fontWeight: 600,
            cursor: input.trim() && !sending ? "pointer" : "default",
            flexShrink: 0,
            transition: "all 0.15s",
          }}
        >
          {sending ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
