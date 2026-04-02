import { useEffect, useRef, useState, useCallback, type ReactNode } from "react";
import { API } from "./types";
import type { DisplayEvent } from "./types";

// Lightweight inline markdown: **bold**, *italic*, `code`, newlines
function renderMarkdown(text: string): ReactNode {
  const lines = text.split("\n");
  return lines.map((line, li) => {
    const parts: ReactNode[] = [];
    const re = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
    let last = 0;
    let match: RegExpExecArray | null;
    while ((match = re.exec(line)) !== null) {
      if (match.index > last) parts.push(line.slice(last, match.index));
      if (match[2]) parts.push(<strong key={`${li}-${match.index}`}>{match[2]}</strong>);
      else if (match[3]) parts.push(<em key={`${li}-${match.index}`}>{match[3]}</em>);
      else if (match[4]) parts.push(<code key={`${li}-${match.index}`} style={{ background: "rgba(255,255,255,0.06)", padding: "1px 5px", borderRadius: 3, fontSize: "0.9em" }}>{match[4]}</code>);
      last = match.index + match[0].length;
    }
    if (last < line.length) parts.push(line.slice(last));
    if (parts.length === 0) parts.push("");
    return (
      <span key={li}>
        {li > 0 && <br />}
        {parts}
      </span>
    );
  });
}

// ─── Storage ────────────────────────────────────────────────────────────────

const CONVOS_KEY = "lumi_chat_convos";
const ACTIVE_KEY = "lumi_chat_active";
const MAX_MESSAGES = 200;
const MAX_CONVOS = 50;

interface ChatMessage {
  id: string;
  role: "user" | "lumi";
  text: string;
  time: string;
  runId?: string;
  pending?: boolean;
  error?: boolean;
}

interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  messages: ChatMessage[];
  manualTitle?: boolean;
}

function loadConvos(): Conversation[] {
  try {
    const raw = localStorage.getItem(CONVOS_KEY);
    if (!raw) {
      // Migrate from old single-chat format
      const oldRaw = localStorage.getItem("lumi_chat_history");
      if (oldRaw) {
        const oldMsgs = JSON.parse(oldRaw) as ChatMessage[];
        if (oldMsgs.length > 0) {
          const migrated: Conversation = {
            id: `c-${Date.now()}`,
            title: titleFromMessages(oldMsgs),
            createdAt: Date.now(),
            messages: cleanPending(oldMsgs),
          };
          localStorage.removeItem("lumi_chat_history");
          return [migrated];
        }
      }
      return [];
    }
    const convos = JSON.parse(raw) as Conversation[];
    return convos.map((c) => ({ ...c, messages: cleanPending(c.messages) }));
  } catch {
    return [];
  }
}

function cleanPending(msgs: ChatMessage[]): ChatMessage[] {
  return msgs.map((m) =>
    m.pending ? { ...m, pending: false, text: m.text || "…", error: true } : m,
  );
}

function titleFromMessages(msgs: ChatMessage[]): string {
  const userMsg = msgs.find((m) => m.role === "user");
  if (!userMsg) return "New chat";
  const lumiMsg = msgs.find((m) => m.role === "lumi" && !m.pending && !m.error && m.text && m.text !== "…");
  // If we have both sides, build a concise "Q → A" style title
  if (lumiMsg) {
    const q = userMsg.text.length > 20 ? userMsg.text.slice(0, 20) + "…" : userMsg.text;
    const a = lumiMsg.text.replace(/\n/g, " ");
    const aShort = a.length > 20 ? a.slice(0, 20) + "…" : a;
    return `${q} → ${aShort}`;
  }
  return userMsg.text.length > 36 ? userMsg.text.slice(0, 36) + "…" : userMsg.text;
}

function saveConvos(convos: Conversation[]) {
  try {
    const trimmed = convos.slice(0, MAX_CONVOS).map((c) => ({
      ...c,
      messages: c.messages.slice(-MAX_MESSAGES),
    }));
    localStorage.setItem(CONVOS_KEY, JSON.stringify(trimmed));
  } catch {}
}

function loadActiveId(): string | null {
  try { return localStorage.getItem(ACTIVE_KEY); } catch { return null; }
}

function saveActiveId(id: string | null) {
  try {
    if (id) localStorage.setItem(ACTIVE_KEY, id);
    else localStorage.removeItem(ACTIVE_KEY);
  } catch {}
}

// ─── Event extraction ───────────────────────────────────────────────────────

function extractResponse(ev: DisplayEvent): { text: string; final: boolean } | null {
  const d = ev.detail as Record<string, any> | undefined;

  if (ev.type === "flow_event" && d?.node === "tts_send") {
    const text: string = d?.data?.text ?? d?.text ?? "";
    if (text) return { text, final: true };
  }
  if (ev.type === "flow_event" && d?.node === "no_reply") {
    return { text: "…", final: true };
  }
  if (ev.type === "chat_response" && d?.message === "[no reply]") {
    return { text: "…", final: true };
  }
  if (ev.type === "chat_response" && (ev.state === "complete" || ev.state === "final")) {
    const msg: string = d?.message ?? ev.summary ?? "";
    if (msg && msg !== "[no reply]") return { text: msg, final: true };
    if (msg === "[no reply]") return { text: "…", final: true };
  }
  if (ev.type === "chat_response" && ev.state !== "error") {
    const msg: string = d?.message ?? ev.summary ?? "";
    if (msg) return { text: msg, final: false };
  }
  return null;
}

// ─── Component ──────────────────────────────────────────────────────────────

interface Props {
  events: DisplayEvent[];
}

export function ChatSection({ events }: Props) {
  const [convos, setConvos] = useState<Conversation[]>(loadConvos);
  const [activeId, setActiveId] = useState<string | null>(() => {
    const saved = loadActiveId();
    return saved && loadConvos().some((c) => c.id === saved) ? saved : null;
  });
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const pendingRunIdRef = useRef<string | null>(null);
  const resolvedIds = useRef<Set<string>>(new Set());

  const active = convos.find((c) => c.id === activeId) ?? null;
  const messages = active?.messages ?? [];

  // Persist
  useEffect(() => { saveConvos(convos); }, [convos]);
  useEffect(() => { saveActiveId(activeId); }, [activeId]);

  // Update messages helper — updates active conversation's messages
  const updateMessages = useCallback((fn: (prev: ChatMessage[]) => ChatMessage[]) => {
    setConvos((prev) =>
      prev.map((c) => {
        if (c.id !== activeId) return c;
        const updated = fn(c.messages);
        // Auto-update title until user has manually renamed it
        const autoTitle = !c.manualTitle ? titleFromMessages(updated) : c.title;
        return { ...c, messages: updated, title: autoTitle };
      }),
    );
  }, [activeId]);

  // Watch flow events for response
  useEffect(() => {
    const pending = pendingRunIdRef.current;
    if (!pending || resolvedIds.current.has(pending)) return;

    let bestResult: { text: string; final: boolean } | null = null;
    for (const ev of [...events].reverse()) {
      const evRunId: string | undefined =
        ev.runId ??
        (ev.detail as any)?.run_id ??
        (ev.detail as any)?.runId ??
        (ev.detail as any)?.data?.run_id;
      if (!evRunId || evRunId !== pending) continue;

      const result = extractResponse(ev);
      if (!result) continue;
      if (!bestResult || result.final) {
        bestResult = result;
        if (result.final) break;
      }
    }
    if (!bestResult) return;

    if (bestResult.final) {
      resolvedIds.current.add(pending);
      pendingRunIdRef.current = null;
      setSending(false);
      const text = bestResult.text;
      updateMessages((prev) =>
        prev.map((m) =>
          m.runId === pending && m.role === "lumi" && m.pending
            ? { ...m, text, pending: false }
            : m,
        ),
      );
    } else {
      const text = bestResult.text;
      updateMessages((prev) =>
        prev.map((m) =>
          m.runId === pending && m.role === "lumi" && m.pending
            ? { ...m, text }
            : m,
        ),
      );
    }
  }, [events, updateMessages]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const newChat = () => {
    // If current active conversation is empty, keep it
    if (active && active.messages.length === 0) return;
    const id = `c-${Date.now()}`;
    const convo: Conversation = { id, title: "New chat", createdAt: Date.now(), messages: [] };
    setConvos((prev) => [convo, ...prev]);
    setActiveId(id);
    setSending(false);
    pendingRunIdRef.current = null;
  };

  const switchTo = (id: string) => {
    if (id === activeId) return;
    setActiveId(id);
    setSending(false);
    pendingRunIdRef.current = null;
  };

  const deleteConvo = (id: string) => {
    setConvos((prev) => prev.filter((c) => c.id !== id));
    if (activeId === id) setActiveId(null);
  };

  const startRename = (c: Conversation) => {
    setEditingId(c.id);
    setEditTitle(c.title);
  };

  const commitRename = () => {
    if (!editingId) return;
    const trimmed = editTitle.trim();
    if (trimmed) {
      setConvos((prev) =>
        prev.map((c) => c.id === editingId ? { ...c, title: trimmed, manualTitle: true } : c),
      );
    }
    setEditingId(null);
  };

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;

    // Auto-create conversation if none active
    let targetId = activeId;
    if (!targetId) {
      const id = `c-${Date.now()}`;
      const convo: Conversation = { id, title: "New chat", createdAt: Date.now(), messages: [] };
      setConvos((prev) => [convo, ...prev]);
      setActiveId(id);
      targetId = id;
    }

    const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: "user", text, time: now };

    // Append user message
    setConvos((prev) =>
      prev.map((c) => {
        if (c.id !== targetId) return c;
        const msgs = [...c.messages, userMsg];
        const title = !c.manualTitle ? titleFromMessages(msgs) : c.title;
        return { ...c, messages: msgs, title };
      }),
    );
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
        setConvos((prev) =>
          prev.map((c) =>
            c.id === targetId
              ? { ...c, messages: [...c.messages, { id: `l-${runId}`, role: "lumi", text: "", time: replyTime, runId, pending: true }] }
              : c,
          ),
        );
        setTimeout(() => {
          if (pendingRunIdRef.current === runId) {
            pendingRunIdRef.current = null;
            setSending(false);
            setConvos((prev) =>
              prev.map((c) =>
                c.id === targetId
                  ? { ...c, messages: c.messages.map((m) => m.runId === runId && m.pending ? { ...m, text: "⏱ no response", pending: false, error: true } : m) }
                  : c,
              ),
            );
          }
        }, 30_000);
      } else if (json.data?.handler === "local") {
        setSending(false);
        const localText = json.data?.response || "✓ handled locally";
        setConvos((prev) =>
          prev.map((c) =>
            c.id === targetId
              ? { ...c, messages: [...c.messages, { id: `l-local-${Date.now()}`, role: "lumi", text: localText, time: now }] }
              : c,
          ),
        );
      } else if (json.data?.handler === "dropped") {
        setSending(false);
        setConvos((prev) =>
          prev.map((c) =>
            c.id === targetId
              ? { ...c, messages: [...c.messages, { id: `l-drop-${Date.now()}`, role: "lumi", text: "⏸ busy — try again", time: now, error: true }] }
              : c,
          ),
        );
      } else {
        setSending(false);
        setConvos((prev) =>
          prev.map((c) =>
            c.id === targetId
              ? { ...c, messages: [...c.messages, { id: `l-err-${Date.now()}`, role: "lumi", text: json.message ?? "error", time: now, error: true }] }
              : c,
          ),
        );
      }
    } catch {
      setSending(false);
      setConvos((prev) =>
        prev.map((c) =>
          c.id === targetId
            ? { ...c, messages: [...c.messages, { id: `l-err-${Date.now()}`, role: "lumi", text: "connection error", time: now, error: true }] }
            : c,
        ),
      );
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  // ─── Date grouping for sidebar ──────────────────────────────────────────
  const grouped = groupConvosByDate(convos);

  return (
    <div style={{ display: "flex", height: "100%", gap: 0 }}>
      {/* Conversation list */}
      <div style={{
        width: 220, flexShrink: 0,
        borderRight: "1px solid var(--lm-border)",
        display: "flex", flexDirection: "column",
        background: "var(--lm-sidebar)",
      }}>
        <div style={{ padding: "12px 12px 8px" }}>
          <button
            onClick={newChat}
            style={{
              width: "100%", padding: "8px 12px", borderRadius: 8,
              background: "rgba(245,158,11,0.12)", border: "1px solid rgba(245,158,11,0.25)",
              color: "var(--lm-amber)", fontSize: 12, fontWeight: 600,
              cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
            }}
          >
            <span style={{ fontSize: 14 }}>+</span> New chat
          </button>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "4px 8px 12px" }}>
          {convos.length === 0 && (
            <div style={{ padding: 16, textAlign: "center", color: "var(--lm-text-muted)", fontSize: 11 }}>
              No conversations yet
            </div>
          )}
          {grouped.map(({ label, items }) => (
            <div key={label}>
              <div style={{ fontSize: 10, fontWeight: 600, color: "var(--lm-text-muted)", padding: "10px 6px 4px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                {label}
              </div>
              {items.map((c) => (
                <div
                  key={c.id}
                  onClick={() => switchTo(c.id)}
                  style={{
                    padding: "7px 8px", borderRadius: 6, cursor: "pointer",
                    background: c.id === activeId ? "rgba(245,158,11,0.1)" : "transparent",
                    border: c.id === activeId ? "1px solid rgba(245,158,11,0.2)" : "1px solid transparent",
                    marginBottom: 2, display: "flex", alignItems: "center", gap: 6,
                    transition: "background 0.15s",
                  }}
                  onMouseEnter={(e) => { if (c.id !== activeId) (e.currentTarget.style.background = "rgba(255,255,255,0.03)"); }}
                  onMouseLeave={(e) => { if (c.id !== activeId) (e.currentTarget.style.background = "transparent"); }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {editingId === c.id ? (
                      <input
                        autoFocus
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onBlur={commitRename}
                        onKeyDown={(e) => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") setEditingId(null); }}
                        onClick={(e) => e.stopPropagation()}
                        style={{
                          fontSize: 12, width: "100%", background: "var(--lm-surface)",
                          border: "1px solid var(--lm-amber)", borderRadius: 4,
                          color: "var(--lm-text)", padding: "1px 4px", outline: "none",
                        }}
                      />
                    ) : (
                      <div
                        onDoubleClick={(e) => { e.stopPropagation(); startRename(c); }}
                        title="Double-click to rename"
                        style={{
                          fontSize: 12, color: c.id === activeId ? "var(--lm-amber)" : "var(--lm-text)",
                          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                          fontWeight: c.id === activeId ? 600 : 400,
                        }}
                      >
                        {c.title}
                      </div>
                    )}
                    {c.messages.length > 0 && (
                      <div style={{
                        fontSize: 10.5, color: "var(--lm-text-muted)", marginTop: 2,
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                      }}>
                        {(() => {
                          const last = c.messages[c.messages.length - 1];
                          const prefix = last.role === "lumi" ? "✦ " : "";
                          const txt = last.text || "…";
                          return prefix + (txt.length > 40 ? txt.slice(0, 40) + "…" : txt);
                        })()}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteConvo(c.id); }}
                    style={{
                      background: "none", border: "none", cursor: "pointer",
                      color: "var(--lm-text-muted)", fontSize: 13, padding: "0 2px",
                      opacity: 0.5, lineHeight: 1,
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; e.currentTarget.style.color = "var(--lm-red)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.5"; e.currentTarget.style.color = "var(--lm-text-muted)"; }}
                    title="Delete conversation"
                  >×</button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
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
                  {msg.pending && !msg.text ? (
                    <span style={{ color: "var(--lm-text-muted)" }}>
                      <span className="lm-blink">●</span>
                      <span style={{ marginLeft: 4 }}>●</span>
                      <span style={{ marginLeft: 4 }}>●</span>
                    </span>
                  ) : msg.pending && msg.text ? (
                    <>
                      {msg.role === "lumi" ? renderMarkdown(msg.text) : msg.text}
                      <span style={{ color: "var(--lm-text-muted)", marginLeft: 4, fontSize: 10 }}>
                        <span className="lm-blink">●</span>
                      </span>
                    </>
                  ) : msg.role === "lumi" ? renderMarkdown(msg.text) : msg.text}
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
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function groupConvosByDate(convos: Conversation[]): { label: string; items: Conversation[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 86400_000;
  const weekAgo = today - 7 * 86400_000;

  const groups: Record<string, Conversation[]> = {};
  const order: string[] = [];

  for (const c of convos) {
    let label: string;
    if (c.createdAt >= today) label = "Today";
    else if (c.createdAt >= yesterday) label = "Yesterday";
    else if (c.createdAt >= weekAgo) label = "This week";
    else label = "Older";

    if (!groups[label]) { groups[label] = []; order.push(label); }
    groups[label].push(c);
  }

  return order.map((label) => ({ label, items: groups[label] }));
}
