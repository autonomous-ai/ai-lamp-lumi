import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

// Real interactive shell — opens a WebSocket to /api/system/shell which pipes
// stdin/stdout/stderr from a /bin/bash PTY. xterm.js handles ANSI escape codes,
// cursor movement, color, line editing, history, tab-complete (from bash), etc.
// Use this for top, vim, nano, less, htop, etc. — anything that needs a TTY.
export function CliSection() {
  const termHostRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const [status, setStatus] = useState<"connecting" | "open" | "closed">("connecting");

  useEffect(() => {
    if (!termHostRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
      fontSize: 12.5,
      lineHeight: 1.2,
      convertEol: true,
      scrollback: 5000,
      theme: {
        // Mirror Lumi monitor palette so the terminal blends with the surrounding UI.
        background: "#0c0b09",
        foreground: "#dad6cd",
        cursor: "#f59e0b",
        cursorAccent: "#0c0b09",
        selectionBackground: "rgba(245,158,11,0.35)",
        black: "#1f1b16", red: "#ef4444", green: "#34d399", yellow: "#f59e0b",
        blue: "#60a5fa", magenta: "#c084fc", cyan: "#2dd4bf", white: "#dad6cd",
        brightBlack: "#504a3c", brightRed: "#fca5a5", brightGreen: "#6ee7b7",
        brightYellow: "#fcd34d", brightBlue: "#93c5fd", brightMagenta: "#d8b4fe",
        brightCyan: "#5eead4", brightWhite: "#f5f5f5",
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(termHostRef.current);
    fit.fit();

    termRef.current = term;
    fitRef.current = fit;

    // Re-fit when the container resizes (sidebar toggle, window resize).
    const ro = new ResizeObserver(() => {
      try { fit.fit(); } catch {}
      sendResize();
    });
    ro.observe(termHostRef.current);

    // Build WebSocket URL respecting current protocol so it works behind
    // either http or https serving Lumi.
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/api/system/shell`);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    const sendResize = () => {
      if (ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: "resize", rows: term.rows, cols: term.cols }));
    };

    ws.onopen = () => {
      setStatus("open");
      sendResize();
      term.focus();
    };
    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(e.data));
      } else if (typeof e.data === "string") {
        term.write(e.data);
      }
    };
    ws.onclose = () => {
      setStatus("closed");
      term.write("\r\n\x1b[90m[shell closed]\x1b[0m\r\n");
    };
    ws.onerror = () => {
      term.write("\r\n\x1b[31m[shell connection error]\x1b[0m\r\n");
    };

    // Forward every keystroke to the PTY. xterm gives us bytes that include
    // arrow keys (ESC sequences), Ctrl combos, etc. — exactly what bash wants.
    const dataDisposable = term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    });

    // xterm's internal fit relies on the container having a stable size, so
    // also re-fit when the window resizes.
    const onWinResize = () => {
      try { fit.fit(); } catch {}
      sendResize();
    };
    window.addEventListener("resize", onWinResize);

    return () => {
      window.removeEventListener("resize", onWinResize);
      ro.disconnect();
      dataDisposable.dispose();
      try { ws.close(); } catch {}
      term.dispose();
      termRef.current = null;
      wsRef.current = null;
      fitRef.current = null;
    };
  }, []);

  const reconnect = () => {
    if (wsRef.current && wsRef.current.readyState <= 1) {
      wsRef.current.close();
    }
    // Trigger re-mount of the effect by toggling status — simpler than tearing
    // down xterm manually. Force unmount/mount via key would also work; this
    // page only has one CLI tab so we just reload the section.
    location.reload();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 8 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10, flexShrink: 0,
        fontSize: 11, color: "var(--lm-text-muted)",
      }}>
        <span>Shell — Pi (interactive PTY)</span>
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          padding: "2px 7px", borderRadius: 4,
          background:
            status === "open"       ? "rgba(52,211,153,0.15)"
            : status === "closed"   ? "rgba(248,113,113,0.15)"
            :                         "rgba(245,158,11,0.15)",
          color:
            status === "open"       ? "var(--lm-green)"
            : status === "closed"   ? "var(--lm-red)"
            :                         "var(--lm-amber)",
          fontWeight: 700, fontSize: 9.5, letterSpacing: "0.05em",
        }}>
          <span style={{
            width: 6, height: 6, borderRadius: "50%",
            background: "currentColor",
            boxShadow: "0 0 4px currentColor",
          }} />
          {status.toUpperCase()}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 9.5, fontFamily: "monospace" }}>
          Ctrl+C/Z · arrows · tab-complete
        </span>
        {status === "closed" && (
          <button
            onClick={reconnect}
            style={{
              fontSize: 10, padding: "3px 10px", borderRadius: 5,
              background: "var(--lm-amber)", border: "none",
              color: "#0C0B09", cursor: "pointer", fontWeight: 600,
            }}
          >Reconnect</button>
        )}
      </div>

      <div
        ref={termHostRef}
        style={{
          flex: 1, minHeight: 0, width: "100%",
          background: "#0c0b09",
          border: "1px solid var(--lm-border)",
          borderRadius: 10,
          padding: "8px 10px",
          overflow: "hidden",
        }}
      />
    </div>
  );
}
