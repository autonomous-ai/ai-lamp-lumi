import { useCallback, useEffect, useRef, useState } from "react";
import { API } from "./types";

interface CliEntry {
  id: number;
  cmd: string;
  stdout: string;
  stderr: string;
  exitCode: number | null; // null = running
  ts: string;
}

let _entryId = 0;

export function CliSection() {
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState<CliEntry[]>([]);
  const [running, setRunning] = useState(false);
  const [histIdx, setHistIdx] = useState(-1);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const history = useRef<string[]>([]);

  // Auto-scroll on new output
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries]);

  const runCmd = useCallback(async (cmd: string) => {
    const trimmed = cmd.trim();
    if (!trimmed) return;

    // Push to history
    history.current = [trimmed, ...history.current.slice(0, 199)];
    setHistIdx(-1);

    const id = ++_entryId;
    const ts = new Date().toLocaleTimeString();
    setEntries((prev) => [...prev, { id, cmd: trimmed, stdout: "", stderr: "", exitCode: null, ts }]);
    setInput("");
    setRunning(true);

    try {
      const resp = await fetch(`${API}/system/exec`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cmd: trimmed }),
      });
      const r = await resp.json();
      const d = r?.data ?? {};
      setEntries((prev) =>
        prev.map((e) =>
          e.id === id
            ? { ...e, stdout: d.stdout ?? "", stderr: d.stderr ?? "", exitCode: d.exit_code ?? 0 }
            : e,
        ),
      );
    } catch (err) {
      setEntries((prev) =>
        prev.map((e) =>
          e.id === id
            ? { ...e, stderr: err instanceof Error ? err.message : String(err), exitCode: -1 }
            : e,
        ),
      );
    } finally {
      setRunning(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, []);

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runCmd(input);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const next = Math.min(histIdx + 1, history.current.length - 1);
      setHistIdx(next);
      setInput(history.current[next] ?? "");
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = histIdx - 1;
      if (next < 0) {
        setHistIdx(-1);
        setInput("");
      } else {
        setHistIdx(next);
        setInput(history.current[next] ?? "");
      }
    } else if (e.key === "l" && e.ctrlKey) {
      e.preventDefault();
      setEntries([]);
    }
  };

  const btnStyle: React.CSSProperties = {
    fontSize: 10, padding: "3px 9px", borderRadius: 5,
    background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
    color: "var(--lm-text-dim)", cursor: "pointer",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 0 }}>
      {/* Toolbar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "0 0 8px 0", flexShrink: 0,
      }}>
        <span style={{ fontSize: 11, color: "var(--lm-text-muted)" }}>
          Shell — Pi (30s timeout)
        </span>
        <button onClick={() => setEntries([])} style={btnStyle}>Clear</button>
      </div>

      {/* Output area */}
      <div
        ref={scrollRef}
        onClick={() => inputRef.current?.focus()}
        style={{
          flex: 1, minHeight: 0, overflowY: "auto",
          background: "var(--lm-card)", border: "1px solid var(--lm-border)",
          borderRadius: 10, padding: "10px 14px",
          fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
          fontSize: 11, lineHeight: 1.6, cursor: "text",
        }}
        className="lm-hide-scroll"
      >
        {entries.length === 0 && (
          <div style={{ color: "var(--lm-text-muted)", fontSize: 10.5 }}>
            Type a command below. ↑↓ for history. Ctrl+L to clear.
          </div>
        )}
        {entries.map((entry) => (
          <div key={entry.id} style={{ marginBottom: 10 }}>
            {/* Command line */}
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 2 }}>
              <span style={{ color: "var(--lm-amber)", userSelect: "none", flexShrink: 0 }}>
                pi@lumi ~$
              </span>
              <span style={{ color: "var(--lm-text)" }}>{entry.cmd}</span>
              <span style={{ marginLeft: "auto", fontSize: 9, color: "var(--lm-text-muted)", flexShrink: 0 }}>
                {entry.ts}
              </span>
            </div>
            {/* Running indicator */}
            {entry.exitCode === null && (
              <div style={{ color: "var(--lm-text-muted)", fontSize: 10 }}>running…</div>
            )}
            {/* Stdout */}
            {entry.stdout && (
              <pre style={{
                margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all",
                color: "var(--lm-text-dim)", fontSize: 11,
              }}>
                {entry.stdout}
              </pre>
            )}
            {/* Stderr */}
            {entry.stderr && (
              <pre style={{
                margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all",
                color: "var(--lm-red)", fontSize: 11,
              }}>
                {entry.stderr}
              </pre>
            )}
            {/* Non-zero exit */}
            {entry.exitCode !== null && entry.exitCode !== 0 && (
              <div style={{ fontSize: 9, color: "var(--lm-red)", marginTop: 2 }}>
                exit {entry.exitCode}
              </div>
            )}
          </div>
        ))}

        {/* Inline current prompt when running */}
        {running && (
          <div style={{ color: "var(--lm-text-muted)", fontSize: 10 }}>…</div>
        )}
      </div>

      {/* Input */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginTop: 8, flexShrink: 0,
        background: "var(--lm-card)", border: "1px solid var(--lm-border)",
        borderRadius: 8, padding: "6px 10px",
      }}>
        <span style={{
          color: "var(--lm-amber)", fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11, flexShrink: 0, userSelect: "none",
        }}>
          pi@lumi ~$
        </span>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={running}
          autoFocus
          autoComplete="off"
          spellCheck={false}
          placeholder={running ? "running…" : "command"}
          style={{
            flex: 1, background: "none", border: "none", outline: "none",
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            fontSize: 11, color: "var(--lm-text)",
            opacity: running ? 0.4 : 1,
          }}
        />
        <button
          onClick={() => runCmd(input)}
          disabled={running || !input.trim()}
          style={{
            ...btnStyle,
            background: running || !input.trim() ? "var(--lm-surface)" : "var(--lm-amber)",
            color: running || !input.trim() ? "var(--lm-text-muted)" : "#0C0B09",
            border: "none", fontWeight: 600,
            opacity: running || !input.trim() ? 0.5 : 1,
          }}
        >
          ↵
        </button>
      </div>
    </div>
  );
}
