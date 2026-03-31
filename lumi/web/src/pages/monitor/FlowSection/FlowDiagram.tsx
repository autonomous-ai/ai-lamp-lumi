import { useCallback, useRef, useState } from "react";
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
  const VW = 920;
  const VH = 720;

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const svgRef = useRef<SVGSVGElement>(null);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    setZoom((z) => Math.min(4, Math.max(0.4, z + delta)));
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
    intent_check:      { x: 100, y: 100 },
    local_match:       { x: 240, y: 100 },
    schedule_trigger:  { x: 625, y: 100 },
    lumi_gate:         { x: 370, y: 560 },
    sensing:           { x: 100, y: 480 },
    hw_action:         { x: 240, y: 480 },
    tts_speak:         { x: 240, y: 630 },
    agent_call:        { x: 625, y: 350 },
    telegram_input:    { x: 775, y: 350 },
    tool_exec:         { x: 500, y: 480 },
    agent_thinking:    { x: 625, y: 480 },
    agent_response:    { x: 500, y: 630 },
  };

  const edges: [FlowStage, FlowStage][] = [
    ["sensing",           "intent_check"],
    ["intent_check",      "local_match"],
    ["local_match",       "tts_speak"],
    ["intent_check",      "agent_call"],
    ["telegram_input",    "agent_call"],
    ["schedule_trigger",  "agent_call"],
    ["agent_call",        "agent_thinking"],
    ["agent_thinking",    "tool_exec"],
    ["agent_thinking",    "agent_response"],
    ["tool_exec",         "hw_action"],
    ["tool_exec",         "lumi_gate"],
    ["agent_response",    "lumi_gate"],
    ["agent_response",    "tts_speak"],
    ["lumi_gate",         "tts_speak"],
  ];

  const nodeR = compact ? 28 : 38;
  const gateR = compact ? 22 : 30;

  function nodeColor(id: FlowStage) {
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

  return (
    <div style={{ position: "relative" }}>
      <svg
        ref={svgRef}
        viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
        style={{
          display: "block", width: "100%", height: "100%", minHeight: 360,
          cursor: dragging ? "grabbing" : "grab", userSelect: "none",
        }}
        onWheel={handleWheel}
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
          <rect x={50} y={50} width={730} height={160} rx={14}
            fill="var(--lm-teal)" fillOpacity={0.04} stroke="var(--lm-teal)" strokeWidth={1} opacity={0.25}
            strokeDasharray="4 4"
          />
          <rect x={320} y={190} width={110} height={430} rx={10}
            fill="var(--lm-teal)" fillOpacity={0.03} stroke="var(--lm-teal)" strokeWidth={1} opacity={0.2}
            strokeDasharray="3 3"
          />
          <text x={415} y={40} textAnchor="middle"
            fill="var(--lm-teal)" fontSize={11} fontWeight={700}
            fontFamily="monospace" opacity={0.6}
            style={{ letterSpacing: "0.08em" }}>
            Lumi Server
          </text>
        </g>
        <g>
          <rect x={30} y={395} width={280} height={300} rx={14}
            fill="var(--lm-amber)" fillOpacity={0.04} stroke="var(--lm-amber)" strokeWidth={1} opacity={0.3}
            strokeDasharray="4 4"
          />
          <text x={145} y={385} textAnchor="middle"
            fill="var(--lm-amber)" fontSize={11} fontWeight={700}
            fontFamily="monospace" opacity={0.6}
            style={{ letterSpacing: "0.08em" }}>
            LeLamp
          </text>
        </g>
        <g>
          <rect x={448} y={292} width={385} height={540} rx={14}
            fill="var(--lm-blue)" fillOpacity={0.04} stroke="var(--lm-blue)" strokeWidth={1} opacity={0.3}
            strokeDasharray="4 4"
          />
          <text x={641} y={282} textAnchor="middle"
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
          const dx = t.x - f.x, dy = t.y - f.y;
          const len = Math.sqrt(dx * dx + dy * dy) || 1;
          const x1 = f.x + (dx / len) * nodeR;
          const y1 = f.y + (dy / len) * nodeR;
          const x2 = t.x - (dx / len) * (nodeR + 4);
          const y2 = t.y - (dy / len) * (nodeR + 4);
          return (
            <line key={`${from}-${to}`} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={edgeColor(from, to)}
              strokeWidth={edgeOpacity(from, to) > 0.5 ? 2 : 1.5}
              markerEnd={`url(#arrow-${compact ? "c" : "f"})`}
              opacity={edgeOpacity(from, to)}
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
          const boxY = pos.y + nodeR + 18 + descLines * 10 + 6;
          return (
            <g key={node.id} opacity={opacity}>
              {isActive && (
                node.id === "lumi_gate" ? (
                  <rect x={pos.x - gateR - 6} y={pos.y - gateR - 6}
                    width={(gateR + 6) * 2} height={(gateR + 6) * 2} rx={12}
                    fill="none" stroke={color} strokeWidth={2}
                    opacity={0.35} style={{ filter: `url(#${glowId})` }}
                  />
                ) : (
                  <circle cx={pos.x} cy={pos.y} r={nodeR + 6}
                    fill="none" stroke={color} strokeWidth={2}
                    opacity={0.35} style={{ filter: `url(#${glowId})` }}
                  />
                )
              )}
              {node.id === "lumi_gate" ? (
                <rect x={pos.x - gateR} y={pos.y - gateR}
                  width={gateR * 2} height={gateR * 2} rx={10}
                  fill={color}
                  fillOpacity={isActive ? 0.25 : isVisited ? 0.18 : 0.12}
                  stroke={color} strokeWidth={isActive ? 2.5 : 1.5}
                  strokeOpacity={isActive ? 1 : isVisited ? 0.7 : 0.35}
                  style={isActive ? { filter: `url(#${glowId})` } : undefined}
                />
              ) : (
                <circle cx={pos.x} cy={pos.y} r={nodeR}
                  fill={color}
                  fillOpacity={isActive ? 0.25 : isVisited ? 0.18 : 0.12}
                  stroke={color} strokeWidth={isActive ? 2.5 : 1.5}
                  strokeOpacity={isActive ? 1 : isVisited ? 0.7 : 0.35}
                  style={isActive ? { filter: `url(#${glowId})` } : undefined}
                />
              )}
              <text x={pos.x} y={pos.y - 6} textAnchor="middle"
                fill={color} fontSize={9} fontWeight={isActive ? 700 : 600}>
                {node.icon} {node.short}
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
                const MAX_CHARS = 35;
                const wrapped: string[] = [];
                for (const line of lines.slice(0, 6)) {
                  if (line.length <= MAX_CHARS) { wrapped.push(line); }
                  else {
                    for (let j = 0; j < line.length; j += MAX_CHARS) {
                      wrapped.push(line.slice(j, j + MAX_CHARS));
                    }
                  }
                }
                const showLines = wrapped.slice(0, 8);
                const maxLen = Math.max(...showLines.map((l) => l.length));
                const boxW = Math.max(140, maxLen * 4 + 20);
                // Extract curl command per original line (before wrapping)
                const curlPerLine: Map<number, string> = new Map();
                let wrappedIdx = 0;
                for (const line of lines.slice(0, 6)) {
                  const firstWrappedIdx = wrappedIdx;
                  if (line.length <= MAX_CHARS) { wrappedIdx++; }
                  else { wrappedIdx += Math.ceil(line.length / MAX_CHARS); }
                  if (line.includes("curl ")) {
                    const m = line.match(/:\s*(curl\s.+)/);
                    curlPerLine.set(firstWrappedIdx, m ? m[1] : line.replace(/^⚙\s*\w+:\s*/, ""));
                  }
                }
                const boxH = showLines.length * 10 + 8;
                return (
                  <g>
                    <rect
                      x={pos.x - boxW / 2} y={boxY - 2}
                      width={boxW} height={boxH}
                      rx={4} ry={4}
                      fill="var(--lm-card)" stroke={color} strokeWidth={0.5}
                      opacity={0.92}
                    />
                    {showLines.map((line, i) => (
                      <text
                        key={i}
                        x={pos.x} y={boxY + 8 + i * 10}
                        textAnchor="middle"
                        fill={color} fontSize={5.5} opacity={0.9}
                        fontFamily="monospace"
                      >
                        {line}
                      </text>
                    ))}
                    {[...curlPerLine.entries()].map(([lineIdx, curl]) => (
                      <g
                        key={`cp-${lineIdx}`}
                        style={{ cursor: "pointer" }}
                        onClick={(e) => {
                          e.stopPropagation();
                          navigator.clipboard.writeText(curl).catch(() => {});
                        }}
                      >
                        <title>{curl}</title>
                        <rect
                          x={pos.x + boxW / 2 - 14} y={boxY + lineIdx * 10}
                          width={12} height={9}
                          rx={2} ry={2}
                          fill={color} fillOpacity={0.15}
                          stroke={color} strokeWidth={0.4} strokeOpacity={0.5}
                        />
                        <text
                          x={pos.x + boxW / 2 - 8} y={boxY + lineIdx * 10 + 7}
                          textAnchor="middle"
                          fill={color} fontSize={4.5}
                          opacity={0.8}
                        >
                          📋
                        </text>
                      </g>
                    ))}
                  </g>
                );
              })()}
            </g>
          );
        })}
      </svg>

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
