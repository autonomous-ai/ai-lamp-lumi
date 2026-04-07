import { useCallback, useEffect, useRef, useState } from "react";
import type { DisplayEvent } from "../types";
import type { FlowStage, ActiveFlowStage } from "./types";
import { FLOW_NODES } from "./types";
import { extractNodeInfo } from "./helpers";

export function FlowDiagram({
  activeStage,
  visitedStages,
  compact = false,
  turnEvents = [],
}: {
  activeStage: ActiveFlowStage;
  visitedStages: Set<FlowStage>;
  compact?: boolean;
  turnEvents?: DisplayEvent[];
}) {
  const VW = 1200;
  const VH = 1080;

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const svgRef = useRef<SVGSVGElement>(null);

  // Use native wheel listener with { passive: false } so preventDefault actually works
  // and stops scroll from bubbling to parent (Turns list).
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      setZoom((z) => Math.min(4, Math.max(0.4, z + delta)));
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
  }, [pan]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    setPan({ x: dragStart.current.panX + dx / zoom, y: dragStart.current.panY + dy / zoom });
  }, [dragging, zoom]);

  const handleMouseUp = useCallback(() => setDragging(false), []);

  const resetView = useCallback(() => { setZoom(1); setPan({ x: 0, y: 0 }); }, []);

  const vbW = VW / zoom;
  const vbH = VH / zoom;
  const vbX = (VW - vbW) / 2 - pan.x;
  const vbY = (VH - vbH) / 2 - pan.y;

  const positions: Record<FlowStage, { x: number; y: number }> = {
    // Lumi — top row
    intent_check:      { x: 80, y: 50 },
    local_match:       { x: 200, y: 50 },
    schedule_trigger:  { x: 800, y: 50 },
    lumi_gate:         { x: 467, y: 570 },
    // LeLamp — input row (MIC/CAM)
    mic_input:         { x: -40, y: 240 },
    cam_input:         { x: 80, y: 240 },
    // LeLamp — output column (stacked vertically, same x, gap=135)
    hw_emotion:        { x: 200, y: 390 },
    hw_led:            { x: 200, y: 525 },
    hw_servo:          { x: 200, y: 660 },
    hw_audio:          { x: 200, y: 795 },
    tts_speak:         { x: 200, y: 930 },
    // OpenClaw — right (spread out)
    agent_call:        { x: 800, y: 240 },
    telegram_input:    { x: 1000, y: 240 },
    tool_exec:         { x: 600, y: 390 },
    agent_thinking:    { x: 800, y: 390 },
    agent_response:    { x: 600, y: 570 },
    tg_out:            { x: 1000, y: 570 },
  };

  const edges: [FlowStage, FlowStage][] = [
    ["mic_input",         "intent_check"],
    ["cam_input",         "intent_check"],
    ["intent_check",      "local_match"],
    ["local_match",       "hw_emotion"],
    ["local_match",       "hw_led"],
    ["local_match",       "hw_servo"],
    ["local_match",       "tts_speak"],
    ["intent_check",      "agent_call"],
    ["telegram_input",    "agent_call"],
    ["schedule_trigger",  "agent_call"],
    ["agent_call",        "agent_thinking"],
    ["agent_thinking",    "tool_exec"],
    ["agent_thinking",    "agent_response"],
    ["tool_exec",         "hw_led"],
    ["tool_exec",         "hw_servo"],
    ["tool_exec",         "hw_emotion"],
    ["tool_exec",         "hw_audio"],
    ["tool_exec",         "lumi_gate"],
    ["agent_response",    "hw_emotion"],
    ["agent_response",    "hw_led"],
    ["agent_response",    "hw_servo"],
    ["agent_response",    "hw_audio"],
    ["agent_response",    "lumi_gate"],
    ["agent_response",    "tts_speak"],
    ["agent_response",    "tg_out"],
    ["agent_call",        "tg_out"],
    ["lumi_gate",         "tts_speak"],
  ];

  const nodeR = compact ? 28 : 38;
  const gateR = compact ? 22 : 30;

  const ttsSuppressed = turnEvents.some((ev) =>
    ev.type === "flow_event" && (ev.detail as Record<string, any>)?.node === "tts_suppressed"
  );

  function nodeColor(id: FlowStage) {
    if (id === "tts_speak" && ttsSuppressed) return "#ef4444";
    if (id === activeStage || visitedStages.has(id)) {
      return FLOW_NODES.find((n) => n.id === id)?.color ?? "var(--lm-text-muted)";
    }
    return "var(--lm-text-muted)";
  }
  function nodeOpacity(id: FlowStage) {
    if (id === activeStage) return 1;
    if (visitedStages.has(id)) return 1;
    return 1;
  }
  function edgeColor(from: FlowStage, to: FlowStage) {
    const fromVisited = visitedStages.has(from) || from === activeStage;
    const toVisited = visitedStages.has(to) || to === activeStage;
    if (fromVisited && toVisited) return nodeColor(to);
    if (fromVisited || toVisited) return "var(--lm-border-hi)";
    return "var(--lm-border)";
  }
  function edgeOpacity(from: FlowStage, to: FlowStage) {
    const fromVisited = visitedStages.has(from) || from === activeStage;
    const toVisited = visitedStages.has(to) || to === activeStage;
    if (fromVisited && toVisited) return 0.98;
    if (fromVisited || toVisited) return 0.8;
    return 0.45;
  }

  const glowId = compact ? "flow-glow-c" : "flow-glow";

  const nodeInfo = extractNodeInfo(turnEvents);

  // Extract snapshot URL from agent_call lines
  const snapshotLine = (nodeInfo.agent_call ?? []).find((l) => l.startsWith("🖼"));
  const snapshotFile = snapshotLine?.match(/snapshot:\s*\/tmp\/lumi-sensing-snapshots\/(sensing_[^\s]+\.jpg)/)?.[1];
  const snapshotUrl = snapshotFile ? `/api/sensing/snapshot/${snapshotFile}` : null;

  return (
    <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <svg
        ref={svgRef}
        viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
        style={{
          display: "block", width: "100%", flex: 1, minHeight: 0,
          cursor: dragging ? "grabbing" : "grab", userSelect: dragging ? "none" : "auto",
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <defs>
          <filter id={glowId}>
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <marker id={`arrow-${compact ? "c" : "f"}`} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="context-stroke" />
          </marker>
        </defs>

        {/* Cluster group backgrounds */}
        <g>
          <rect x={-100} y={0} width={1200} height={110} rx={14}
            fill="var(--lm-teal)" fillOpacity={0.04} stroke="var(--lm-teal)" strokeWidth={1} opacity={0.25}
            strokeDasharray="4 4"
          />
          <rect x={417} y={100} width={110} height={520} rx={10}
            fill="var(--lm-teal)" fillOpacity={0.03} stroke="var(--lm-teal)" strokeWidth={1} opacity={0.2}
            strokeDasharray="3 3"
          />
          <text x={467} y={-8} textAnchor="middle"
            fill="var(--lm-teal)" fontSize={11} fontWeight={700}
            fontFamily="monospace" opacity={0.6}
            style={{ letterSpacing: "0.08em" }}>
            Lumi Server
          </text>
        </g>
        <g>
          <rect x={-100} y={185} width={360} height={805} rx={14}
            fill="var(--lm-amber)" fillOpacity={0.04} stroke="var(--lm-amber)" strokeWidth={1} opacity={0.3}
            strokeDasharray="4 4"
          />
          <text x={80} y={175} textAnchor="middle"
            fill="var(--lm-amber)" fontSize={11} fontWeight={700}
            fontFamily="monospace" opacity={0.6}
            style={{ letterSpacing: "0.08em" }}>
            LeLamp
          </text>
        </g>
        <g>
          <rect x={540} y={185} width={520} height={445} rx={14}
            fill="var(--lm-blue)" fillOpacity={0.04} stroke="var(--lm-blue)" strokeWidth={1} opacity={0.3}
            strokeDasharray="4 4"
          />
          <text x={800} y={175} textAnchor="middle"
            fill="var(--lm-blue)" fontSize={11} fontWeight={700}
            fontFamily="monospace" opacity={0.6}
            style={{ letterSpacing: "0.08em" }}>
            OpenClaw
          </text>
        </g>

        {/* Edges */}
        {edges.map(([from, to]) => {
          const f = positions[from];
          const t = positions[to];
          const color = edgeColor(from, to);
          const sw = edgeOpacity(from, to) > 0.5 ? 2 : 1.5;
          const op = edgeOpacity(from, to);
          const marker = `url(#arrow-${compact ? "c" : "f"})`;

          // Elbow edges: LOCAL → output nodes (bypass intermediate nodes)
          // Route: go right from LOCAL, then down, then left into target node
          if (from === "local_match" && (to === "hw_led" || to === "hw_servo" || to === "tts_speak" || to === "hw_emotion" || to === "hw_audio")) {
            const elbowX = t.x - 80; // offset left of target
            const startY = f.y + nodeR;
            const endY = t.y;
            const endX = t.x - nodeR - 4; // enter from left side
            return (
              <path key={`${from}-${to}`}
                d={`M ${f.x - nodeR * 0.7} ${f.y + nodeR * 0.7} L ${elbowX} ${startY + 20} L ${elbowX} ${endY} L ${endX} ${endY}`}
                stroke={color} strokeWidth={sw} fill="none"
                markerEnd={marker} opacity={op}
              />
            );
          }

          const isGateEdge = from === "lumi_gate" || to === "lumi_gate";
          // HW marker path: agent_response fires inline markers — shown as dashed to distinguish from LLM tool path
          const isHWMarkerEdge = from === "agent_response" && (to === "hw_emotion" || to === "hw_led" || to === "hw_servo" || to === "hw_audio");
          const dx = t.x - f.x, dy = t.y - f.y;
          const len = Math.sqrt(dx * dx + dy * dy) || 1;
          const x1 = f.x + (dx / len) * nodeR;
          const y1 = f.y + (dy / len) * nodeR;
          const x2 = t.x - (dx / len) * (nodeR + 4);
          const y2 = t.y - (dy / len) * (nodeR + 4);
          const dashArray = isGateEdge || isHWMarkerEdge ? "6 4" : undefined;
          return (
            <line key={`${from}-${to}`} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={color} strokeWidth={sw}
              markerEnd={marker} opacity={op}
              {...(dashArray ? { strokeDasharray: dashArray } : {})}
            />
          );
        })}

        {/* Nodes */}
        {FLOW_NODES.map((node) => {
          const pos = positions[node.id];
          const isActive = node.id === activeStage;
          const isVisited = visitedStages.has(node.id);
          const color = nodeColor(node.id);
          const opacity = nodeOpacity(node.id);
          const lines = nodeInfo[node.id] ?? [];
          const hasInfo = lines.length > 0 && (isActive || isVisited);
          const descLines = node.desc.split(" · ").length;
          const boxAbove = node.id === "tool_exec";
          const boxY = boxAbove ? pos.y - nodeR - 4 : pos.y + nodeR + 14 + descLines * 10;
          return (
            <g key={node.id} opacity={opacity}>
              {/* Node shape based on node.shape */}
              {(() => {
                const shape = node.shape ?? "circle";
                const r = shape === "square" ? gateR : nodeR;
                const fOpacity = isActive ? 0.25 : isVisited ? 0.18 : 0.12;
                const sOpacity = isActive ? 1 : isVisited ? 0.7 : 0.35;
                const sWidth = isActive ? 2.5 : 1.5;
                const glow = isActive ? { filter: `url(#${glowId})` } : undefined;
                const glowR = r + 6;
                const props = { fill: color, fillOpacity: fOpacity, stroke: color, strokeWidth: sWidth, strokeOpacity: sOpacity, style: glow };
                const glowProps = { fill: "none" as const, stroke: color, strokeWidth: 2, opacity: 0.35, style: { filter: `url(#${glowId})` } };

                const hexPoints = (cx: number, cy: number, rad: number) =>
                  Array.from({ length: 6 }, (_, i) => {
                    const angle = (Math.PI / 3) * i - Math.PI / 6;
                    return `${cx + rad * Math.cos(angle)},${cy + rad * Math.sin(angle)}`;
                  }).join(" ");

                const diamondPoints = (cx: number, cy: number, rad: number) =>
                  `${cx},${cy - rad} ${cx + rad},${cy} ${cx},${cy + rad} ${cx - rad},${cy}`;

                switch (shape) {
                  case "hexagon":
                    return (<>
                      {isActive && <polygon points={hexPoints(pos.x, pos.y, glowR)} {...glowProps} />}
                      <polygon points={hexPoints(pos.x, pos.y, r)} {...props} />
                    </>);
                  case "diamond":
                    return (<>
                      {isActive && <polygon points={diamondPoints(pos.x, pos.y, glowR)} {...glowProps} />}
                      <polygon points={diamondPoints(pos.x, pos.y, r)} {...props} />
                    </>);
                  case "square":
                    return (<>
                      {isActive && <rect x={pos.x - glowR} y={pos.y - glowR} width={glowR * 2} height={glowR * 2} rx={12} {...glowProps} />}
                      <rect x={pos.x - r} y={pos.y - r} width={r * 2} height={r * 2} rx={10} {...props} />
                    </>);
                  default:
                    return (<>
                      {isActive && <circle cx={pos.x} cy={pos.y} r={glowR} {...glowProps} />}
                      <circle cx={pos.x} cy={pos.y} r={r} {...props} />
                    </>);
                }
              })()}
              <text x={pos.x} y={pos.y - 6} textAnchor="middle"
                fill={color} fontSize={9} fontWeight={isActive ? 700 : 600}>
                {node.id === "agent_response" && lines.some((l) => l.includes("no reply")) ? "🚫"
                  : node.id === "agent_response" && lines.some((l) => l.includes("no output")) ? "💤"
                  : node.id === "agent_response" && lines.some((l) => l.startsWith('"')) ? "💬"
                  : node.icon} {node.short}
              </text>
              <text x={pos.x} y={pos.y + 6} textAnchor="middle"
                fill={color} fontSize={7} opacity={0.9}>
                {node.label}
              </text>
              {node.desc.split(" · ").map((part, i) => (
                <text key={`d${i}`} x={pos.x} y={pos.y + nodeR + 14 + i * 10} textAnchor="middle"
                  fill={color} fontSize={5.5} opacity={0.6}>
                  {part}
                </text>
              ))}

              {hasInfo && (() => {
                const textLines = lines.filter((l) => !l.startsWith("🖼"));
                const boxW = 190;
                return (
                  <foreignObject
                    x={boxAbove ? pos.x + nodeR - boxW : pos.x - boxW / 2} y={boxY - 2}
                    width={boxW} height={1}
                    overflow="visible"
                  >
                    <div
                      // @ts-expect-error xmlns required for foreignObject HTML
                      xmlns="http://www.w3.org/1999/xhtml"
                      onMouseDown={(e: React.MouseEvent) => e.stopPropagation()}
                      style={{
                        background: "color-mix(in srgb, var(--lm-card) 70%, transparent)",
                        border: `1px solid color-mix(in srgb, ${color} 40%, transparent)`,
                        borderRadius: 4,
                        padding: "4px 6px",
                        fontFamily: "monospace",
                        fontSize: 5.5,
                        lineHeight: 1.7,
                        color: color,
                        opacity: 0.95,
                        ...(boxAbove ? { transform: "translateY(-100%)" } : {}),
                        userSelect: "text",
                        WebkitUserSelect: "text",
                        cursor: "text",
                        wordBreak: "break-all" as const,
                        whiteSpace: "pre-wrap" as const,
                        maxWidth: boxW,
                      }}
                    >
                      {textLines.map((line, i) => (
                        <div key={i} style={{
                          color: line.startsWith("⏱") ? "#fbbf24" : color,
                          fontWeight: line.startsWith("⏱") ? 700 : 400,
                        }}>
                          {line}
                        </div>
                      ))}
                    </div>
                  </foreignObject>
                );
              })()}
            </g>
          );
        })}

        {/* Snapshot image — same column as TG IN, same row as THINK */}
        {snapshotUrl && (() => {
          const snapX = 1000;
          const snapY = 390;
          const agentX = 800;
          const agentY = 240;
          const imgW = 100;
          const imgH = 75;
          return (
            <g>
              {/* Dashed arrow from snapshot to AGENT */}
              <line
                x1={snapX} y1={snapY - imgH / 2 - 4}
                x2={agentX + nodeR + 2} y2={agentY + nodeR / 2}
                stroke="#fbbf24" strokeWidth={1.2} strokeDasharray="4 3"
                opacity={0.7}
                markerEnd="url(#snap-arrow)"
              />
              <defs>
                <marker id="snap-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#fbbf24" opacity={0.7} />
                </marker>
              </defs>
              {/* Image border */}
              <rect
                x={snapX - imgW / 2} y={snapY - imgH / 2}
                width={imgW} height={imgH}
                rx={6} ry={6}
                fill="var(--lm-card)" stroke="#fbbf24" strokeWidth={1}
                opacity={0.9}
              />
              {/* The image */}
              <image
                href={snapshotUrl}
                x={snapX - imgW / 2 + 2} y={snapY - imgH / 2 + 2}
                width={imgW - 4} height={imgH - 4}
                preserveAspectRatio="xMidYMid meet"
                clipPath={`inset(0 round 4px)`}
              />
              <text
                x={snapX} y={snapY + imgH / 2 + 10}
                textAnchor="middle"
                fill="#fbbf24" fontSize={6} fontWeight={600}
              >
                📷 Snapshot
              </text>
            </g>
          );
        })()}
      </svg>

      {/* Shape legend */}
      <div style={{
        display: "flex", gap: 16, justifyContent: "center", alignItems: "center",
        fontSize: 10, color: "var(--lm-text-muted)", padding: "8px 0 4px",
      }}>
        {([
          { label: "Input", color: "var(--lm-amber)", shape: (c: string) => (
            <svg width="16" height="16" viewBox="-8 -8 16 16" style={{ verticalAlign: "middle" }}>
              <polygon points={Array.from({ length: 6 }, (_, i) => {
                const a = (Math.PI / 3) * i - Math.PI / 6;
                return `${6 * Math.cos(a)},${6 * Math.sin(a)}`;
              }).join(" ")} fill={c} fillOpacity={0.2} stroke={c} strokeWidth="1.5" />
            </svg>
          )},
          { label: "Process", color: "var(--lm-blue)", shape: (c: string) => (
            <svg width="16" height="16" viewBox="-8 -8 16 16" style={{ verticalAlign: "middle" }}>
              <circle r="6" fill={c} fillOpacity={0.2} stroke={c} strokeWidth="1.5" />
            </svg>
          )},
          { label: "Output", color: "var(--lm-purple)", shape: (c: string) => (
            <svg width="16" height="16" viewBox="-8 -8 16 16" style={{ verticalAlign: "middle" }}>
              <polygon points="0,-7 7,0 0,7 -7,0" fill={c} fillOpacity={0.2} stroke={c} strokeWidth="1.5" />
            </svg>
          )},
          { label: "Gate", color: "var(--lm-teal)", shape: (c: string) => (
            <svg width="16" height="16" viewBox="-8 -8 16 16" style={{ verticalAlign: "middle" }}>
              <rect x="-5.5" y="-5.5" width="11" height="11" rx="2.5" fill={c} fillOpacity={0.2} stroke={c} strokeWidth="1.5" />
            </svg>
          )},
        ] as const).map((item) => (
          <span key={item.label} style={{ display: "inline-flex", alignItems: "center", gap: 4, color: item.color }}>
            {item.shape(item.color)} {item.label}
          </span>
        ))}
      </div>

      {/* Zoom controls overlay */}
      <div style={{
        position: "absolute", bottom: 6, right: 6,
        display: "flex", gap: 4, alignItems: "center",
      }}>
        <span style={{ fontSize: 9, color: "var(--lm-text-muted)", marginRight: 4 }}>
          {Math.round(zoom * 100)}%
        </span>
        {[
          { label: "−", action: () => setZoom((z) => Math.max(0.4, z - 0.2)) },
          { label: "⟳", action: resetView },
          { label: "+", action: () => setZoom((z) => Math.min(4, z + 0.2)) },
        ].map((btn) => (
          <button key={btn.label} onClick={btn.action} style={{
            width: 22, height: 22, borderRadius: 5, border: "1px solid var(--lm-border)",
            background: "var(--lm-surface)", color: "var(--lm-text-dim)",
            cursor: "pointer", fontSize: 12, lineHeight: 1, padding: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>{btn.label}</button>
        ))}
      </div>
    </div>
  );
}
