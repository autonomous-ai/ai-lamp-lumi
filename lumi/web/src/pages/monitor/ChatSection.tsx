import { useEffect, useRef, useState, useCallback, type ReactNode } from "react";
import { API } from "./types";
import type { DisplayEvent, MonitorEvent } from "./types";

// ─── Markdown ───────────────────────────────────────────────────────────────

// Inline: **bold**, *italic*, `code`, URLs
function renderInline(line: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const re = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`|(https?:\/\/[^\s<>)"]+))/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(line)) !== null) {
    if (match.index > last) parts.push(line.slice(last, match.index));
    const k = `${keyPrefix}-${match.index}`;
    if (match[2]) parts.push(<strong key={k}>{match[2]}</strong>);
    else if (match[3]) parts.push(<em key={k}>{match[3]}</em>);
    else if (match[4]) parts.push(<code key={k} style={{ background: "rgba(255,255,255,0.06)", padding: "1px 5px", borderRadius: 3, fontSize: "0.9em" }}>{match[4]}</code>);
    else if (match[5]) parts.push(<a key={k} href={match[5]} target="_blank" rel="noopener noreferrer" style={{ color: "var(--lm-teal)", textDecoration: "underline" }}>{match[5].length > 50 ? match[5].slice(0, 50) + "…" : match[5]}</a>);
    last = match.index + match[0].length;
  }
  if (last < line.length) parts.push(line.slice(last));
  return parts;
}

function renderMarkdown(text: string): ReactNode {
  const lines = text.split("\n");
  const result: ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    // Code block: ```
    if (lines[i].startsWith("```")) {
      const codeLines: string[] = [];
      i++; // skip opening ```
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++; // skip closing ```
      result.push(
        <pre key={`cb-${i}`} style={{
          background: "rgba(0,0,0,0.3)", padding: "8px 12px", borderRadius: 6,
          fontSize: "0.85em", overflowX: "auto", margin: "4px 0",
          border: "1px solid var(--lm-border)", whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}>
          <code>{codeLines.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    // Unordered list: - item or * item
    if (/^[\-\*]\s/.test(lines[i])) {
      const items: ReactNode[] = [];
      while (i < lines.length && /^[\-\*]\s/.test(lines[i])) {
        items.push(<li key={`li-${i}`}>{renderInline(lines[i].replace(/^[\-\*]\s/, ""), `ul-${i}`)}</li>);
        i++;
      }
      result.push(<ul key={`ul-${i}`} style={{ margin: "4px 0", paddingLeft: 20 }}>{items}</ul>);
      continue;
    }

    // Ordered list: 1. item
    if (/^\d+\.\s/.test(lines[i])) {
      const items: ReactNode[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(<li key={`oli-${i}`}>{renderInline(lines[i].replace(/^\d+\.\s/, ""), `ol-${i}`)}</li>);
        i++;
      }
      result.push(<ol key={`ol-${i}`} style={{ margin: "4px 0", paddingLeft: 20 }}>{items}</ol>);
      continue;
    }

    // Regular line
    const inline = renderInline(lines[i], `l-${i}`);
    result.push(
      <span key={`s-${i}`}>
        {i > 0 && result.length > 0 && <br />}
        {inline.length > 0 ? inline : ""}
      </span>,
    );
    i++;
  }

  return result;
}

// Strip inline HW control markers like [HW:/emotion:{"emotion":"curious","intensity":0.7}]
function stripHWMarkers(text: string): string {
  return text.replace(/\[HW:\/[^\]]*\]/g, "").trim();
}

// ─── Tool call parsing ──────────────────────────────────────────────────────

interface ToolChip {
  id: string;       // dedup key
  icon: string;
  label: string;
}

const TOOL_EVENT_TYPES = new Set(["tool_call", "hw_emotion", "hw_led", "hw_audio", "hw_servo", "led_set", "led_off"]);

function parseToolChip(ev: { type: string; summary: string; id: string }): ToolChip | null {
  const s = ev.summary;
  switch (ev.type) {
    case "hw_emotion": {
      const m = s.match(/"emotion"\s*:\s*"([^"]+)"/);
      return { id: ev.id, icon: "🎭", label: m ? m[1] : "emotion" };
    }
    case "hw_led": {
      if (s.includes("/scene/")) {
        const m = s.match(/\/scene\/(\w+)/);
        return { id: ev.id, icon: "🎨", label: m ? `scene: ${m[1]}` : "LED scene" };
      }
      if (s.includes("/led/off")) return { id: ev.id, icon: "💡", label: "LED off" };
      const m = s.match(/"hex"\s*:\s*"([^"]+)"/);
      return { id: ev.id, icon: "💡", label: m ? `LED ${m[1]}` : "LED" };
    }
    case "led_off": return { id: ev.id, icon: "💡", label: "LED off" };
    case "led_set": return null; // redundant with hw_led/hw_emotion
    case "hw_audio": return { id: ev.id, icon: "🎵", label: "music" };
    case "hw_servo": {
      if (s.includes("/aim")) return { id: ev.id, icon: "⚙", label: "servo aim" };
      if (s.includes("/play")) {
        const m = s.match(/\/play\/(\w+)/);
        return { id: ev.id, icon: "⚙", label: m ? `servo: ${m[1]}` : "servo play" };
      }
      return { id: ev.id, icon: "⚙", label: "servo" };
    }
    case "tool_call": {
      // Generic tool_call — extract tool name from summary "toolName(phase)"
      const m = s.match(/^(\w+)/);
      const name = m ? m[1] : "tool";
      // Skip if already covered by hw_* events
      if (["set_emotion", "set_led", "play_music", "move_servo"].includes(name)) return null;
      return { id: ev.id, icon: "🔧", label: name };
    }
    default: return null;
  }
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
  date?: string;       // YYYY-MM-DD for date separators
  imageUrl?: string;   // data: URL for attached images (not persisted to save space)
  fileName?: string;   // original filename for non-image files
  fileSize?: number;   // bytes
  runId?: string;
  pending?: boolean;
  error?: boolean;
  tools?: ToolChip[];  // tool calls made during this response
  tokenUsage?: { input: number; output: number; cacheRead?: number; cacheWrite?: number; total: number };
}

interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  messages: ChatMessage[];
  manualTitle?: boolean;
  pinned?: boolean;
}

function loadConvos(): Conversation[] {
  try {
    const raw = localStorage.getItem(CONVOS_KEY);
    if (!raw) {
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
      // Strip large data from localStorage (imageUrl data: URLs are too large)
      messages: c.messages.slice(-MAX_MESSAGES).map(({ imageUrl: _, ...m }) => m),
      // fileName/fileSize are kept — they're small strings/numbers
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

// ─── Clipboard helper ───────────────────────────────────────────────────────

function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) return navigator.clipboard.writeText(text);
  // Fallback for older browsers / non-HTTPS
  return new Promise((resolve) => {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    resolve();
  });
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
  const [search, setSearch] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [filePreview, setFilePreview] = useState<string | null>(null);    // data: URL (images only)
  const [fileBase64, setFileBase64] = useState<string | null>(null);      // raw base64 for API
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileSize, setFileSize] = useState<number>(0);
  const [fileIsImage, setFileIsImage] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [dragging, setDragging] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pendingRunIdRef = useRef<string | null>(null);
  const resolvedIds = useRef<Set<string>>(new Set());
  const deltaBufRef = useRef<Map<string, string>>(new Map()); // runId → accumulated delta text
  const thinkingBufRef = useRef<Map<string, string>>(new Map()); // runId → accumulated thinking text
  const rafRef = useRef<number | null>(null); // requestAnimationFrame handle for batched rendering
  const dirtyRef = useRef(false); // whether there are pending delta/thinking updates to flush
  const [thinkingText, setThinkingText] = useState<string | null>(null); // current thinking display
  const [toolChips, setToolChips] = useState<ToolChip[]>([]); // tool calls for current pending response

  const active = convos.find((c) => c.id === activeId) ?? null;
  const messages = active?.messages ?? [];

  // Persist
  useEffect(() => { saveConvos(convos); }, [convos]);
  useEffect(() => { saveActiveId(activeId); }, [activeId]);

  // Keyboard shortcut: Cmd/Ctrl+N for new chat
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "n") {
        e.preventDefault();
        newChat();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
  }, [input]);

  // Scroll detection for scroll-to-bottom button
  const onScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setShowScrollBtn(!nearBottom);
  }, []);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  // Update messages helper
  const updateMessages = useCallback((fn: (prev: ChatMessage[]) => ChatMessage[]) => {
    setConvos((prev) =>
      prev.map((c) => {
        if (c.id !== activeId) return c;
        const updated = fn(c.messages);
        const autoTitle = !c.manualTitle ? titleFromMessages(updated) : c.title;
        return { ...c, messages: updated, title: autoTitle };
      }),
    );
  }, [activeId]);

  // Real-time monitor bus SSE — streaming deltas, thinking, tool calls
  // Uses /api/openclaw/events (live bus) instead of flow-stream (file-based JSONL)
  const toolChipsRef = useRef<Map<string, ToolChip>>(new Map()); // key → chip for dedup
  const tokenUsageRef = useRef<ChatMessage["tokenUsage"]>(undefined); // token usage for current run

  useEffect(() => {
    const es = new EventSource(`${API}/openclaw/events`);

    // Batch delta/thinking updates into a single render per animation frame
    const scheduleFlush = () => {
      if (rafRef.current != null) return; // already scheduled
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        if (!dirtyRef.current) return;
        dirtyRef.current = false;
        const p = pendingRunIdRef.current;
        if (!p) return;
        // Flush thinking
        setThinkingText(thinkingBufRef.current.get(p) ?? null);
        // Flush assistant text
        const buf = deltaBufRef.current.get(p);
        if (buf) {
          const cleaned = stripHWMarkers(buf);
          updateMessages((prev) =>
            prev.map((m) =>
              m.runId === p && m.role === "lumi" && m.pending
                ? { ...m, text: cleaned }
                : m,
            ),
          );
        }
      });
    };

    const resolveRun = (runId: string) => {
      const buf = deltaBufRef.current.get(runId) ?? "";
      const text = stripHWMarkers(buf || "…");
      deltaBufRef.current.delete(runId);
      thinkingBufRef.current.delete(runId);
      resolvedIds.current.add(runId);
      pendingRunIdRef.current = null;
      setSending(false);
      setThinkingText(null);
      const chips = Array.from(toolChipsRef.current.values());
      const savedChips = chips.length > 0 ? chips : undefined;
      toolChipsRef.current.clear();
      setToolChips([]);
      const usage = tokenUsageRef.current;
      tokenUsageRef.current = undefined;
      return { text, savedChips, usage };
    };

    es.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data) as MonitorEvent;
        if (!ev.type) return;
        const pending = pendingRunIdRef.current;
        if (!pending || resolvedIds.current.has(pending)) return;

        const evRunId = ev.runId ?? (ev.detail as any)?.run_id ?? (ev.detail as any)?.runId;
        if (!evRunId || evRunId !== pending) return;

        // Tool call chips
        if (TOOL_EVENT_TYPES.has(ev.type)) {
          const chip = parseToolChip({ type: ev.type, summary: ev.summary, id: ev.id });
          if (chip) {
            const key = chip.icon + chip.label;
            if (!toolChipsRef.current.has(key)) {
              toolChipsRef.current.set(key, chip);
              setToolChips(Array.from(toolChipsRef.current.values()));
            }
          }
        }

        // Token usage — save for attaching to message on finalize
        if (ev.type === "token_usage") {
          const d = ev.detail as Record<string, string> | undefined;
          if (d) {
            tokenUsageRef.current = {
              input: parseInt(d.input_tokens ?? "0", 10),
              output: parseInt(d.output_tokens ?? "0", 10),
              cacheRead: parseInt(d.cache_read_tokens ?? "0", 10) || undefined,
              cacheWrite: parseInt(d.cache_write_tokens ?? "0", 10) || undefined,
              total: parseInt(d.total_tokens ?? "0", 10),
            };
          }
          return;
        }

        // Thinking deltas — accumulate, flush on next animation frame
        if (ev.type === "thinking") {
          const delta = ev.summary ?? "";
          if (delta) {
            const buf = thinkingBufRef.current.get(pending) ?? "";
            thinkingBufRef.current.set(pending, buf + delta);
            dirtyRef.current = true;
            scheduleFlush();
          }
          return;
        }

        // Assistant streaming deltas — accumulate, flush on next animation frame
        if (ev.type === "assistant_delta") {
          const delta = ev.summary ?? "";
          if (delta) {
            const buf = deltaBufRef.current.get(pending) ?? "";
            deltaBufRef.current.set(pending, buf + delta);
            dirtyRef.current = true;
            scheduleFlush();
          }
          return;
        }

        // Chat response (partial or final) from "chat" event path
        if (ev.type === "chat_response") {
          const d = ev.detail as Record<string, any> | undefined;
          const chatMsg = d?.message ?? ev.summary ?? "";

          if (chatMsg === "[no reply]") {
            const { text, savedChips, usage } = resolveRun(pending);
            updateMessages((prev) =>
              prev.map((m) =>
                m.runId === pending && m.role === "lumi" && m.pending
                  ? { ...m, text: text === "…" ? "…" : text, pending: false, tools: savedChips, tokenUsage: usage }
                  : m,
              ),
            );
            return;
          }

          if (ev.state === "complete" || ev.state === "final") {
            const { savedChips, usage } = resolveRun(pending);
            const finalText = stripHWMarkers(chatMsg || deltaBufRef.current.get(pending) || "…");
            updateMessages((prev) =>
              prev.map((m) =>
                m.runId === pending && m.role === "lumi" && m.pending
                  ? { ...m, text: finalText, pending: false, tools: savedChips, tokenUsage: usage }
                  : m,
              ),
            );
            return;
          }

          if (ev.state === "error") return; // error handled separately

          // Partial (non-delta path)
          if (chatMsg && !deltaBufRef.current.has(pending)) {
            const cleaned = stripHWMarkers(chatMsg);
            updateMessages((prev) =>
              prev.map((m) =>
                m.runId === pending && m.role === "lumi" && m.pending
                  ? { ...m, text: cleaned }
                  : m,
              ),
            );
          }
        }
      } catch {
        // ignore malformed SSE data
      }
    };

    return () => {
      es.close();
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [updateMessages]);

  // Watch flow events for final response (tts_send, no_reply from JSONL)
  // This catches responses that only appear in flow logs, not on the live bus
  useEffect(() => {
    const pending = pendingRunIdRef.current;
    if (!pending || resolvedIds.current.has(pending)) return;

    for (const ev of [...events].reverse()) {
      const evRunId: string | undefined =
        ev.runId ??
        (ev.detail as any)?.run_id ??
        (ev.detail as any)?.runId ??
        (ev.detail as any)?.data?.run_id;
      if (!evRunId || evRunId !== pending) continue;

      const d = ev.detail as Record<string, any> | undefined;
      if (ev.type === "flow_event" && d?.node === "tts_send") {
        const text: string = d?.data?.text ?? d?.text ?? "";
        if (text) {
          resolvedIds.current.add(pending);
          pendingRunIdRef.current = null;
          setSending(false);
          setThinkingText(null);
          const chips = Array.from(toolChipsRef.current.values());
          const savedChips = chips.length > 0 ? chips : undefined;
          toolChipsRef.current.clear();
          setToolChips([]);
          const usage = tokenUsageRef.current;
          tokenUsageRef.current = undefined;
          const cleaned = stripHWMarkers(text);
          updateMessages((prev) =>
            prev.map((m) =>
              m.runId === pending && m.role === "lumi" && m.pending
                ? { ...m, text: cleaned, pending: false, tools: savedChips, tokenUsage: usage }
                : m,
            ),
          );
          return;
        }
      }
      if (ev.type === "flow_event" && d?.node === "no_reply") {
        resolvedIds.current.add(pending);
        pendingRunIdRef.current = null;
        setSending(false);
        setThinkingText(null);
        toolChipsRef.current.clear();
        setToolChips([]);
        tokenUsageRef.current = undefined;
        updateMessages((prev) =>
          prev.map((m) =>
            m.runId === pending && m.role === "lumi" && m.pending
              ? { ...m, text: "…", pending: false }
              : m,
          ),
        );
        return;
      }
    }
  }, [events, updateMessages]);

  // Auto-scroll on new messages
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (nearBottom) scrollToBottom();
  }, [messages, scrollToBottom]);

  // ─── Actions ────────────────────────────────────────────────────────────

  const newChat = useCallback(() => {
    if (active && active.messages.length === 0) return;
    const id = `c-${Date.now()}`;
    const convo: Conversation = { id, title: "New chat", createdAt: Date.now(), messages: [] };
    setConvos((prev) => [convo, ...prev]);
    setActiveId(id);
    setSending(false);
    pendingRunIdRef.current = null;
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, [active]);

  const switchTo = (id: string) => {
    if (id === activeId) return;
    setActiveId(id);
    setSending(false);
    pendingRunIdRef.current = null;
  };

  const deleteConvo = (id: string) => {
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id);
      setTimeout(() => setConfirmDeleteId((prev) => prev === id ? null : prev), 3000);
      return;
    }
    setConvos((prev) => prev.filter((c) => c.id !== id));
    if (activeId === id) setActiveId(null);
    setConfirmDeleteId(null);
  };

  const togglePin = (id: string) => {
    setConvos((prev) => prev.map((c) => c.id === id ? { ...c, pinned: !c.pinned } : c));
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

  const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

  const attachFile = useCallback((file: File) => {
    if (file.size > MAX_FILE_SIZE) {
      alert(`File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Max 10 MB.`);
      return;
    }
    const isImage = file.type.startsWith("image/");
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      setFileBase64(dataUrl.split(",")[1] ?? null);
      setFileName(file.name);
      setFileSize(file.size);
      setFileIsImage(isImage);
      setFilePreview(isImage ? dataUrl : null);
    };
    reader.readAsDataURL(file);
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) attachFile(file);
    e.target.value = "";
  };

  const clearFile = () => {
    setFilePreview(null);
    setFileBase64(null);
    setFileName(null);
    setFileSize(0);
    setFileIsImage(false);
  };

  // Drag & drop
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  }, []);
  const onDragLeave = useCallback((e: React.DragEvent) => {
    // Only leave when exiting the container (not children)
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setDragging(false);
  }, []);
  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) attachFile(file);
  }, [attachFile]);

  // Paste image from clipboard
  const onPaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith("image/")) {
        const file = items[i].getAsFile();
        if (file) {
          e.preventDefault();
          attachFile(file);
          return;
        }
      }
    }
  }, [attachFile]);

  const exportConversation = () => {
    if (!active || active.messages.length === 0) return;
    const lines = active.messages.map((m) => {
      const role = m.role === "user" ? "You" : "Lumi";
      return `[${m.time}] ${role}: ${m.text}`;
    });
    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `lumi-chat-${active.id}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copyMessage = (msg: ChatMessage) => {
    copyToClipboard(msg.text).then(() => {
      setCopiedId(msg.id);
      setTimeout(() => setCopiedId((prev) => prev === msg.id ? null : prev), 1500);
    });
  };

  const retryMessage = (errorMsg: ChatMessage) => {
    // Find the user message right before this error
    const idx = messages.findIndex((m) => m.id === errorMsg.id);
    if (idx < 1) return;
    const userMsg = messages[idx - 1];
    if (userMsg.role !== "user") return;

    // Remove the error message and resend
    updateMessages((prev) => prev.filter((m) => m.id !== errorMsg.id));
    setInput(userMsg.text);
    // Remove the user message too, send() will re-add it
    setTimeout(() => {
      updateMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
      // Trigger send with the text
      sendText(userMsg.text);
    }, 50);
  };

  // ─── Send logic ─────────────────────────────────────────────────────────

  const sendText = useCallback(async (text: string, attachedImage?: string | null) => {
    if (!text || sending) return;

    let targetId = activeId;
    if (!targetId) {
      const id = `c-${Date.now()}`;
      const convo: Conversation = { id, title: "New chat", createdAt: Date.now(), messages: [] };
      setConvos((prev) => [convo, ...prev]);
      setActiveId(id);
      targetId = id;
    }

    const nowDate = new Date();
    const now = nowDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const dateStr = nowDate.toISOString().slice(0, 10);
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`, role: "user", text, time: now, date: dateStr,
      imageUrl: filePreview ?? undefined,
      fileName: (!fileIsImage && fileName) ? fileName : undefined,
      fileSize: (!fileIsImage && fileSize) ? fileSize : undefined,
    };

    setConvos((prev) =>
      prev.map((c) => {
        if (c.id !== targetId) return c;
        const msgs = [...c.messages, userMsg];
        const title = !c.manualTitle ? titleFromMessages(msgs) : c.title;
        return { ...c, messages: msgs, title };
      }),
    );
    setInput("");
    clearFile();
    setSending(true);

    const sendImage = attachedImage ?? fileBase64;

    try {
      const body: Record<string, string> = { type: "voice", message: text };
      if (sendImage) body.image = sendImage;
      const res = await fetch(`${API}/sensing/event`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
            setThinkingText(null);
            setToolChips([]);
            const streamed = deltaBufRef.current.get(runId);
            deltaBufRef.current.delete(runId);
            thinkingBufRef.current.delete(runId);
            toolChipsRef.current.clear();
            setConvos((prev) =>
              prev.map((c) =>
                c.id === targetId
                  ? { ...c, messages: c.messages.map((m) => m.runId === runId && m.pending
                      ? { ...m, text: streamed || "⏱ no response", pending: false, error: !streamed }
                      : m) }
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
  }, [activeId, sending, updateMessages]);

  const send = () => { sendText(input.trim(), fileBase64); };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  // ─── Filtered conversations ─────────────────────────────────────────────
  const filtered = search.trim()
    ? convos.filter((c) => {
        const q = search.toLowerCase();
        if (c.title.toLowerCase().includes(q)) return true;
        return c.messages.some((m) => m.text.toLowerCase().includes(q));
      })
    : convos;
  const grouped = groupConvosByDate(filtered);

  // ─── Render ─────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", height: "100%", gap: 0 }}>
      {/* ── Sidebar ── */}
      {sidebarOpen && (
      <div style={{
        width: 230, flexShrink: 0,
        borderRight: "1px solid var(--lm-border)",
        display: "flex", flexDirection: "column",
        background: "var(--lm-sidebar)",
        transition: "width 0.2s",
      }}>
        <div style={{ padding: "12px 12px 4px", display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              onClick={newChat}
              title="Ctrl+N"
              style={{
                flex: 1, padding: "8px 12px", borderRadius: 8,
                background: "rgba(245,158,11,0.12)", border: "1px solid rgba(245,158,11,0.25)",
                color: "var(--lm-amber)", fontSize: 12, fontWeight: 600,
                cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
              }}
            >
              <span style={{ fontSize: 14 }}>+</span> New chat
            </button>
            <button
              onClick={() => setSidebarOpen(false)}
              style={{
                padding: "8px 8px", borderRadius: 8,
                background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                color: "var(--lm-text-muted)", fontSize: 12,
                cursor: "pointer", flexShrink: 0,
              }}
              title="Collapse sidebar"
            >◀</button>
          </div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search chats…"
            style={{
              width: "100%", padding: "6px 10px", borderRadius: 6,
              background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
              color: "var(--lm-text)", fontSize: 11, outline: "none",
            }}
          />
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "4px 8px 12px" }}>
          {filtered.length === 0 && (
            <div style={{ padding: 16, textAlign: "center", color: "var(--lm-text-muted)", fontSize: 11 }}>
              {search ? "No matches" : "No conversations yet"}
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
                  <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
                    <button
                      onClick={(e) => { e.stopPropagation(); togglePin(c.id); }}
                      style={{
                        background: "none", border: "none", cursor: "pointer",
                        color: c.pinned ? "var(--lm-amber)" : "var(--lm-text-muted)",
                        fontSize: 10, padding: "0 2px", opacity: c.pinned ? 0.9 : 0.4,
                        lineHeight: 1, transition: "opacity 0.15s",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.opacity = c.pinned ? "0.9" : "0.4"; }}
                      title={c.pinned ? "Unpin" : "Pin to top"}
                    >{c.pinned ? "◆" : "◇"}</button>
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteConvo(c.id); }}
                      style={{
                        background: "none", border: "none", cursor: "pointer",
                        color: confirmDeleteId === c.id ? "var(--lm-red)" : "var(--lm-text-muted)",
                        fontSize: confirmDeleteId === c.id ? 10 : 13,
                        padding: "0 2px", opacity: confirmDeleteId === c.id ? 1 : 0.5,
                        lineHeight: 1, fontWeight: confirmDeleteId === c.id ? 600 : 400,
                        transition: "all 0.15s",
                      }}
                      onMouseEnter={(e) => { if (confirmDeleteId !== c.id) { e.currentTarget.style.opacity = "1"; e.currentTarget.style.color = "var(--lm-red)"; } }}
                      onMouseLeave={(e) => { if (confirmDeleteId !== c.id) { e.currentTarget.style.opacity = "0.5"; e.currentTarget.style.color = "var(--lm-text-muted)"; } }}
                      title={confirmDeleteId === c.id ? "Click again to confirm" : "Delete conversation"}
                    >{confirmDeleteId === c.id ? "del?" : "×"}</button>
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
        {convos.length > 1 && (
          <div style={{ padding: "8px 12px", borderTop: "1px solid var(--lm-border)" }}>
            <button
              onClick={() => {
                if (confirm(`Delete all ${convos.filter((c) => !c.pinned).length} unpinned conversations?`)) {
                  setConvos((prev) => prev.filter((c) => c.pinned));
                  setActiveId(null);
                }
              }}
              style={{
                width: "100%", padding: "5px 0", borderRadius: 6,
                background: "none", border: "1px solid var(--lm-border)",
                color: "var(--lm-text-muted)", fontSize: 10, cursor: "pointer",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = "var(--lm-red)"; e.currentTarget.style.borderColor = "var(--lm-red)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = "var(--lm-text-muted)"; e.currentTarget.style.borderColor = "var(--lm-border)"; }}
            >Clear all unpinned</button>
          </div>
        )}
      </div>
      )}

      {/* ── Chat area ── */}
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}
      >
        {/* Drop overlay */}
        {dragging && (
          <div style={{
            position: "absolute", inset: 0, zIndex: 10,
            background: "rgba(245,158,11,0.08)",
            border: "2px dashed var(--lm-amber)",
            borderRadius: 8,
            display: "flex", alignItems: "center", justifyContent: "center",
            pointerEvents: "none",
          }}>
            <span style={{ fontSize: 14, color: "var(--lm-amber)", fontWeight: 600 }}>
              Drop file here
            </span>
          </div>
        )}
        {/* Chat header bar */}
        <div style={{
          padding: "6px 12px", borderBottom: "1px solid var(--lm-border)",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: "var(--lm-sidebar)", minHeight: 36,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {!sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: "var(--lm-text-muted)", fontSize: 12, padding: "2px 4px",
                }}
                title="Show sidebar"
              >▶</button>
            )}
            <span style={{ fontSize: 12, color: "var(--lm-text-dim)", fontWeight: 500 }}>
              {active ? active.title : "Select or start a chat"}
            </span>
          </div>
          {active && active.messages.length > 0 && (
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={exportConversation}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  fontSize: 10, color: "var(--lm-text-muted)", padding: "2px 6px",
                }}
                title="Export as text"
              >↓ export</button>
            </div>
          )}
        </div>
        {/* Messages */}
        <div
          ref={scrollContainerRef}
          onScroll={onScroll}
          style={{ flex: 1, overflowY: "auto", padding: "20px 16px 8px", display: "flex", flexDirection: "column", gap: 12 }}
        >
          {messages.length === 0 && (
            <div style={{ margin: "auto", textAlign: "center", color: "var(--lm-text-muted)", fontSize: 13, lineHeight: 1.8 }}>
              <div style={{ fontSize: 28, marginBottom: 10 }}>✦</div>
              <div>Chat with Lumi</div>
              <div style={{ fontSize: 11, marginTop: 4 }}>Type a message or press Shift+Enter for multi-line</div>
            </div>
          )}
          {messages.map((msg, i) => {
            // Date separator
            const prevDate = i > 0 ? messages[i - 1].date : null;
            const showDate = msg.date && msg.date !== prevDate;
            return (
            <div key={msg.id}>
              {showDate && (
                <div style={{
                  textAlign: "center", fontSize: 10, color: "var(--lm-text-muted)",
                  padding: "8px 0 4px", fontWeight: 500,
                }}>
                  {formatDateLabel(msg.date!)}
                </div>
              )}
              <div
                className="lm-chat-msg"
                style={{ display: "flex", flexDirection: msg.role === "user" ? "row-reverse" : "row", alignItems: "flex-end", gap: 8 }}
              >
              {msg.role === "lumi" && (
                <div style={{
                  width: 28, height: 28, borderRadius: "50%",
                  background: "var(--lm-amber-dim)", border: "1px solid rgba(245,158,11,0.3)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 12, flexShrink: 0, color: "var(--lm-amber)",
                }}>✦</div>
              )}
              <div style={{ maxWidth: "72%", display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start", gap: 3 }}>
                {/* Thinking indicator — shown only for the active pending message */}
                {msg.pending && msg.role === "lumi" && msg.runId === pendingRunIdRef.current && thinkingText && (
                  <ThinkingBlock text={thinkingText} />
                )}
                {/* Tool call chips — live during pending, persisted after finalize */}
                {msg.role === "lumi" && (() => {
                  const isActivePending = msg.pending && msg.runId === pendingRunIdRef.current;
                  const chips = isActivePending ? toolChips : msg.tools;
                  if (!chips || chips.length === 0) return null;
                  return (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 2 }}>
                      {chips.map((c) => (
                        <span key={c.id} style={{
                          display: "inline-flex", alignItems: "center", gap: 3,
                          padding: "2px 8px", borderRadius: 10, fontSize: 10,
                          background: "rgba(20,184,166,0.1)", border: "1px solid rgba(20,184,166,0.2)",
                          color: "rgba(20,184,166,0.85)",
                        }}>
                          <span>{c.icon}</span>{c.label}
                        </span>
                      ))}
                    </div>
                  );
                })()}
                <div style={{
                  padding: "9px 13px",
                  borderRadius: msg.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
                  background: msg.role === "user" ? "rgba(245,158,11,0.15)" : "var(--lm-surface)",
                  border: `1px solid ${msg.role === "user" ? "rgba(245,158,11,0.25)" : "var(--lm-border)"}`,
                  color: msg.error ? "var(--lm-red)" : "var(--lm-text)",
                  fontSize: 13, lineHeight: 1.55, wordBreak: "break-word",
                  minWidth: 40, minHeight: 36, position: "relative",
                }}>
                  {msg.imageUrl && (
                    <img
                      src={msg.imageUrl}
                      alt="attached"
                      style={{
                        maxWidth: 200, maxHeight: 150, borderRadius: 6,
                        marginBottom: msg.text ? 6 : 0,
                      }}
                    />
                  )}
                  {msg.fileName && (
                    <div style={{
                      display: "flex", alignItems: "center", gap: 6,
                      padding: "4px 8px", borderRadius: 6,
                      background: "rgba(255,255,255,0.04)", border: "1px solid var(--lm-border)",
                      marginBottom: msg.text ? 6 : 0, fontSize: 11,
                    }}>
                      <span>📎</span>
                      <span style={{ color: "var(--lm-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 160 }}>
                        {msg.fileName}
                      </span>
                      {msg.fileSize != null && (
                        <span style={{ color: "var(--lm-text-muted)", fontSize: 10, flexShrink: 0 }}>
                          {msg.fileSize < 1024 ? `${msg.fileSize} B`
                            : msg.fileSize < 1024 * 1024 ? `${(msg.fileSize / 1024).toFixed(0)} KB`
                            : `${(msg.fileSize / 1024 / 1024).toFixed(1)} MB`}
                        </span>
                      )}
                    </div>
                  )}
                  {msg.pending && !msg.text ? (
                    <span style={{ color: "var(--lm-text-muted)" }}>
                      <span className="lm-blink">●</span>
                      <span style={{ marginLeft: 4 }}>●</span>
                      <span style={{ marginLeft: 4 }}>●</span>
                    </span>
                  ) : msg.pending && msg.text ? (
                    <>
                      {msg.role === "lumi" ? renderMarkdown(msg.text) : msg.text}
                      <span className="lm-cursor" style={{
                        display: "inline-block", width: 2, height: "1em",
                        background: "var(--lm-amber)", marginLeft: 2,
                        verticalAlign: "text-bottom", borderRadius: 1,
                      }} />
                    </>
                  ) : msg.role === "lumi" ? renderMarkdown(msg.text) : msg.text}
                </div>
                {/* Action bar: time + copy + retry */}
                <div style={{ display: "flex", alignItems: "center", gap: 6, paddingInline: 4 }}>
                  <span style={{ fontSize: 10, color: "var(--lm-text-muted)" }}>{msg.time}</span>
                  {!msg.pending && msg.text && msg.text !== "…" && (
                    <button
                      onClick={() => copyMessage(msg)}
                      style={{
                        background: "none", border: "none", cursor: "pointer",
                        fontSize: 10, color: copiedId === msg.id ? "var(--lm-green)" : "var(--lm-text-muted)",
                        padding: 0, opacity: 0.6, transition: "opacity 0.15s",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.6"; }}
                      title="Copy"
                    >{copiedId === msg.id ? "✓" : "⎘"}</button>
                  )}
                  {msg.error && msg.role === "lumi" && (
                    <button
                      onClick={() => retryMessage(msg)}
                      style={{
                        background: "none", border: "none", cursor: "pointer",
                        fontSize: 10, color: "var(--lm-amber)", padding: 0,
                        opacity: 0.7, transition: "opacity 0.15s",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.7"; }}
                      title="Retry"
                    >↻ retry</button>
                  )}
                  {msg.tokenUsage && msg.role === "lumi" && (
                    <span style={{ fontSize: 9, color: "var(--lm-text-muted)", opacity: 0.5 }}
                      title={`in: ${msg.tokenUsage.input} / out: ${msg.tokenUsage.output}${msg.tokenUsage.cacheRead ? ` / cache read: ${msg.tokenUsage.cacheRead}` : ""}${msg.tokenUsage.cacheWrite ? ` / cache write: ${msg.tokenUsage.cacheWrite}` : ""} / total: ${msg.tokenUsage.total}`}
                    >
                      {msg.tokenUsage.input}↓ {msg.tokenUsage.output}↑
                    </span>
                  )}
                </div>
              </div>
            </div>
            </div>
            );
          })}
          <div ref={bottomRef} />
        </div>

        {/* Scroll to bottom */}
        {showScrollBtn && (
          <button
            onClick={scrollToBottom}
            style={{
              position: "absolute", bottom: 80, right: 20,
              width: 32, height: 32, borderRadius: "50%",
              background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
              color: "var(--lm-text-muted)", fontSize: 14,
              cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: "0 2px 8px rgba(0,0,0,0.3)", transition: "opacity 0.2s",
            }}
            title="Scroll to bottom"
          >↓</button>
        )}

        {/* File preview */}
        {fileName && (
          <div style={{
            padding: "8px 16px 0", borderTop: "1px solid var(--lm-border)",
            background: "var(--lm-sidebar)", display: "flex", alignItems: "center", gap: 8,
          }}>
            {filePreview ? (
              <img src={filePreview} alt="preview" style={{ height: 48, borderRadius: 6, border: "1px solid var(--lm-border)" }} />
            ) : (
              <div style={{
                height: 48, width: 48, borderRadius: 6, border: "1px solid var(--lm-border)",
                background: "var(--lm-surface)", display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 18,
              }}>📎</div>
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 11, color: "var(--lm-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{fileName}</div>
              <div style={{ fontSize: 10, color: "var(--lm-text-muted)" }}>
                {fileSize < 1024 ? `${fileSize} B` : fileSize < 1024 * 1024 ? `${(fileSize / 1024).toFixed(0)} KB` : `${(fileSize / 1024 / 1024).toFixed(1)} MB`}
              </div>
            </div>
            <button
              onClick={clearFile}
              style={{
                background: "none", border: "none", cursor: "pointer",
                color: "var(--lm-text-muted)", fontSize: 14, padding: "0 4px",
              }}
              title="Remove file"
            >×</button>
          </div>
        )}

        {/* Input */}
        <div style={{ padding: "12px 16px", borderTop: fileName ? "none" : "1px solid var(--lm-border)", display: "flex", gap: 8, alignItems: "flex-end", background: "var(--lm-sidebar)" }}>
          <input ref={fileInputRef} type="file" style={{ display: "none" }} onChange={handleFileSelect} />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={sending}
            style={{
              background: "none", border: "1px solid var(--lm-border)", borderRadius: 8,
              cursor: sending ? "default" : "pointer", padding: "8px 10px",
              color: "var(--lm-text-muted)", fontSize: 14, flexShrink: 0,
              opacity: sending ? 0.5 : 0.7, transition: "opacity 0.15s",
            }}
            onMouseEnter={(e) => { if (!sending) e.currentTarget.style.opacity = "1"; }}
            onMouseLeave={(e) => { e.currentTarget.style.opacity = sending ? "0.5" : "0.7"; }}
            title="Attach file (max 10 MB)"
          >📎</button>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            disabled={sending}
            placeholder="Send a message to Lumi… (Shift+Enter for new line)"
            rows={1}
            style={{
              flex: 1, background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
              borderRadius: 8, padding: "9px 13px", color: "var(--lm-text)", fontSize: 13,
              outline: "none", opacity: sending ? 0.6 : 1,
              resize: "none", lineHeight: 1.5, fontFamily: "inherit",
              maxHeight: 120, overflow: "auto",
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
              transition: "all 0.15s", marginBottom: 1,
            }}
          >{sending ? "…" : "Send"}</button>
        </div>
      </div>
    </div>
  );
}

// ─── Thinking Block ──────────────────────────────────────────────────────────

function ThinkingBlock({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const preview = text.length > 80 ? text.slice(0, 80) + "…" : text;

  return (
    <div style={{
      fontSize: 11, lineHeight: 1.5, borderRadius: 8,
      border: "1px solid rgba(168,85,247,0.2)",
      background: "rgba(168,85,247,0.06)",
      overflow: "hidden",
    }}>
      <button
        onClick={() => setExpanded((p) => !p)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          width: "100%", padding: "6px 10px",
          background: "none", border: "none", cursor: "pointer",
          color: "rgba(168,85,247,0.8)", fontSize: 11, fontWeight: 600,
          textAlign: "left",
        }}
      >
        <span className="lm-blink" style={{ fontSize: 8 }}>●</span>
        <span>Thinking</span>
        <span style={{ fontSize: 9, opacity: 0.6 }}>{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded ? (
        <div style={{
          padding: "0 10px 8px", color: "var(--lm-text-muted)",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          maxHeight: 200, overflowY: "auto",
        }}>
          {text}
        </div>
      ) : (
        <div style={{
          padding: "0 10px 6px", color: "var(--lm-text-muted)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {preview}
        </div>
      )}
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDateLabel(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = today.getTime() - d.getTime();
  if (diff <= 0) return "Today";
  if (diff <= 86400_000) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function groupConvosByDate(convos: Conversation[]): { label: string; items: Conversation[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 86400_000;
  const weekAgo = today - 7 * 86400_000;

  // Pinned first
  const pinned = convos.filter((c) => c.pinned);
  const unpinned = convos.filter((c) => !c.pinned);

  const groups: Record<string, Conversation[]> = {};
  const order: string[] = [];

  if (pinned.length > 0) {
    groups["Pinned"] = pinned;
    order.push("Pinned");
  }

  for (const c of unpinned) {
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
