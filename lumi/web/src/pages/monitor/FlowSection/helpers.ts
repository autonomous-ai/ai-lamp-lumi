import type { DisplayEvent } from "../types";
import type { ActiveFlowStage, Turn, NodeInfoMap } from "./types";
import { FLOW_NODES, TELEGRAM_FALLBACK_MESSAGE } from "./types";

// Derive active stage from most recent relevant events
export function deriveActiveStage(events: DisplayEvent[]): ActiveFlowStage {
  const recent = events.slice(-30);
  for (let i = recent.length - 1; i >= 0; i--) {
    const ev = recent[i];
    const key = ev.type === "flow_event" && ev.detail?.node
      ? `flow_event:${ev.detail.node}`
      : ev.type === "flow_enter" && ev.detail?.node
      ? `flow_enter:${ev.detail.node}`
      : ev.type === "flow_exit" && ev.detail?.node
      ? `flow_exit:${ev.detail.node}`
      : ev.type;
    for (const node of [...FLOW_NODES].reverse()) {
      if (node.triggers.includes(key)) return node.id;
    }
  }
  return "idle";
}

export function extractEventRunId(ev: DisplayEvent): string | undefined {
  if (ev.runId) return ev.runId;
  const detail = ev.detail as Record<string, any> | undefined;
  return detail?.run_id ?? detail?.runId ?? detail?.data?.run_id ?? detail?.data?.runId;
}

export function parseTelegramSummary(summary: string): string {
  const m = summary.match(/^\[telegram\]\s*(.*)/i);
  if (!m) return summary.trim();
  return (m[1] ?? "").trim();
}

export function turnHasOutput(turn: Turn): boolean {
  return turn.events.some((ev) =>
    ev.type === "tts" ||
    ev.type === "intent_match" ||
    (ev.type === "flow_event" && (ev.detail?.node === "tts_send" || ev.detail?.node === "intent_match")),
  );
}

export function turnHasRealTelegramInput(turn: Turn): boolean {
  return turn.events.some((ev) => {
    if (ev.type !== "chat_input") return false;
    const msg = parseTelegramSummary(ev.summary);
    return msg.length > 0;
  });
}

export function turnHasChatInputEvent(turn: Turn): boolean {
  return turn.events.some((ev) =>
    ev.type === "chat_input" ||
    (ev.type === "flow_event" && ev.detail?.node === "chat_input") ||
    (ev.type === "flow_enter" && ev.detail?.node === "chat_input") ||
    (ev.type === "flow_exit" && ev.detail?.node === "chat_input"),
  );
}

export function turnHasSensingInput(turn: Turn): boolean {
  return turn.events.some((ev) =>
    ev.type === "sensing_input" ||
    (ev.type === "flow_enter" && ev.detail?.node === "sensing_input"),
  );
}

/** Bracket label from "[voice] hello" / "[motion] ..." on sensing_input / flow_enter sensing_input. */
export function sensingInputBracketType(ev: DisplayEvent): string | null {
  if (ev.type !== "sensing_input" && !(ev.type === "flow_enter" && ev.detail?.node === "sensing_input")) {
    return null;
  }
  const m = ev.summary.match(/^\[([^\]]+)\]/);
  return m ? m[1] : null;
}

/**
 * Same run_id can include motion (camera) then voice in one session; merge keeps the first segment's type (often "motion").
 * For the turn badge, prefer voice / voice_command when any utterance is present — that is the user's intent.
 */
export function refineTurnTypeFromSensingInputs(turn: Turn): void {
  if (turn.type === "telegram" || turn.type.startsWith("ambient:") || turn.type === "schedule") {
    return;
  }
  let sawVoice = false;
  let sawVoiceCommand = false;
  for (const ev of turn.events) {
    const t = sensingInputBracketType(ev);
    if (t === "voice_command") sawVoiceCommand = true;
    else if (t === "voice") sawVoice = true;
  }
  if (sawVoiceCommand) turn.type = "voice_command";
  else if (sawVoice) turn.type = "voice";
}

export function groupIntoTurns(events: DisplayEvent[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;

  function isTurnStart(ev: DisplayEvent): { type: string; path: Turn["path"]; forceNewTurn?: boolean; boundary?: Turn["boundary"] } | null {
    if (ev.type === "sensing_input" || (ev.type === "flow_enter" && ev.detail?.node === "sensing_input")) {
      const m = ev.summary.match(/^\[([^\]]+)\]/);
      const t = m ? m[1] : "unknown";
      return {
        type: t,
        path: "unknown",
        forceNewTurn: t === "voice" || t === "voice_command",
        boundary: t === "voice" || t === "voice_command" ? "mic" : undefined,
      };
    }
    if ((ev.type === "flow_event" || ev.type === "flow_enter") && ev.detail?.node === "voice_pipeline_start") {
      return { type: "voice", path: "unknown", forceNewTurn: true, boundary: "mic" };
    }
    if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
      return { type: "telegram", path: "agent", boundary: "chat" };
    }
    const ambientNode = ev.detail?.node ?? "";
    const isAmbientTurn = ev.type === "ambient_action" ||
      ((ev.type === "flow_event" || ev.type === "flow_enter") &&
       ambientNode.startsWith("ambient_") &&
       ambientNode !== "ambient_pause" && ambientNode !== "ambient_resume");
    if (isAmbientTurn) {
      const sub = ambientNode.replace("ambient_", "") || "idle";
      return { type: `ambient:${sub}`, path: "local" };
    }
    if (ev.type === "schedule_trigger" || ev.type === "cron_fire" ||
        (ev.type === "flow_event" && (ev.detail?.node === "schedule_trigger" || ev.detail?.node === "cron_fire"))) {
      return { type: "schedule", path: "agent" };
    }
    return null;
  }

  for (const ev of events) {
    const evRunId = extractEventRunId(ev);
    const start = isTurnStart(ev);
    if (start) {
      const shouldForceSplit = Boolean(start.forceNewTurn);
      if (!shouldForceSplit && current && current.runId && evRunId && current.runId === evRunId) {
        current.events.push(ev);
        continue;
      }
      if (current) turns.push(current);
      current = {
        id: evRunId || `turn-${ev._seq}`,
        runId: evRunId,
        startTime: ev.time,
        type: start.type,
        path: start.path,
        boundary: start.boundary,
        boundaryInstanceSeq: start.boundary ? ev._seq : undefined,
        status: "active",
        events: [ev],
      };
      continue;
    }

    if (current && current.runId && evRunId && current.runId !== evRunId) {
      const inferredType: Turn["type"] = current.type !== "unknown" ? current.type : "agent";
      const inferredPath: Turn["path"] = current.path !== "unknown" ? current.path : "agent";
      turns.push(current);
      current = {
        id: evRunId,
        runId: evRunId,
        startTime: ev.time,
        type: inferredType,
        path: inferredPath,
        status: "active",
        events: [ev],
      };
      continue;
    }

    if (!current) {
      continue;
    }
    current.events.push(ev);
    if (!current.runId && evRunId) {
      current.runId = evRunId;
      current.id = evRunId;
    }

    if (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match")) {
      current.path = "local";
    } else if (current.path !== "local") {
      const belongsToTurn = !current.runId || !evRunId || evRunId === current.runId;
      if (belongsToTurn && (evRunId || ev.type === "lifecycle" || ev.type === "thinking")) {
        current.path = "agent";
      }
    }

    if (ev.type === "lifecycle" && ev.phase === "end") {
      current.status = ev.error ? "error" : "done";
      current.endTime = ev.time;
    }
    if (ev.type === "intent_match") {
      current.status = "done";
      current.endTime = ev.time;
    }
    if (ev.type === "flow_event" && ev.detail?.node === "tts_send") {
      current.status = "done";
      current.endTime = ev.time;
    }
    if (current.type.startsWith("ambient:") && ev.type === "flow_exit" && ev.detail?.node?.startsWith("ambient_")) {
      current.status = "done";
      current.endTime = ev.time;
    }
  }
  if (current) turns.push(current);

  // Merge fragmented segments that share the same run_id
  const merged: Turn[] = [];
  const runIndex = new Map<string, number>();
  for (const turn of turns) {
    if (!turn.runId) {
      merged.push(turn);
      continue;
    }
    const idx = runIndex.get(turn.runId);
    if (idx === undefined) {
      runIndex.set(turn.runId, merged.length);
      merged.push(turn);
      continue;
    }
    if (turn.boundaryInstanceSeq !== undefined) {
      merged.push(turn);
      runIndex.set(turn.runId, merged.length - 1);
      continue;
    }

    const base = merged[idx];
    base.events.push(...turn.events);
    if (base.status !== "error" && turn.status === "error") base.status = "error";
    else if (base.status === "active" && turn.status === "done") base.status = "done";
    if (!base.endTime && turn.endTime) base.endTime = turn.endTime;
    else if (base.endTime && turn.endTime && turn.endTime > base.endTime) base.endTime = turn.endTime;
    if (base.path !== "agent" && turn.path === "agent") base.path = "agent";
    if (base.type === "unknown" && turn.type !== "unknown") base.type = turn.type;
  }
  for (const turn of merged) {
    turn.events.sort((a, b) => a._seq - b._seq);
  }

  // Merge adjacent Telegram fallback + agent output fragments
  const stitched: Turn[] = [];
  for (const turn of merged) {
    const prev = stitched[stitched.length - 1];
    if (!prev) {
      stitched.push(turn);
      continue;
    }
    const prevHasNoOutput = !turnHasOutput(prev);
    const currLooksAgentReply = turn.path === "agent" && turnHasOutput(turn);
    const prevTs = new Date(prev.endTime || prev.startTime).getTime();
    const currTs = new Date(turn.startTime).getTime();
    const closeInTime = Number.isFinite(prevTs) && Number.isFinite(currTs) && (currTs - prevTs) <= 30_000;

    const prevIsTelegramFallback = prev.type === "telegram" && !turnHasRealTelegramInput(prev);
    if (prevIsTelegramFallback && prevHasNoOutput && currLooksAgentReply && closeInTime) {
      if (turn.runId && /^lumi-(chat|sensing)-/i.test(turn.runId)) {
        stitched.push(turn);
        continue;
      }
      prev.events.push(...turn.events);
      prev.events.sort((a, b) => a._seq - b._seq);
      prev.status = turn.status === "error" ? "error" : turn.status;
      prev.endTime = turn.endTime || prev.endTime;
      prev.path = "agent";
      continue;
    }

    const prevIsSensingNoOutput = turnHasSensingInput(prev) && prevHasNoOutput;
    const currIsOrphanOutput = !turnHasSensingInput(turn) && !turnHasRealTelegramInput(turn) && turnHasOutput(turn);
    if (prevIsSensingNoOutput && currIsOrphanOutput && closeInTime) {
      prev.events.push(...turn.events);
      prev.events.sort((a, b) => a._seq - b._seq);
      prev.status = turn.status === "error" ? "error" : turn.status;
      prev.endTime = turn.endTime || prev.endTime;
      prev.path = "agent";
      continue;
    }

    stitched.push(turn);
  }

  for (const turn of stitched) {
    refineTurnTypeFromSensingInputs(turn);
    if (turn.type === "telegram" && (!turnHasChatInputEvent(turn))) {
      turn.type = "unknown";
    }
    if (turn.type === "telegram" && turnHasChatInputEvent(turn) && !turnHasRealTelegramInput(turn) && !turnHasOutput(turn)) {
      turn.type = "unknown";
    }
  }

  // Detect session breaks
  for (let i = 1; i < stitched.length; i++) {
    const prev = stitched[i - 1];
    const curr = stitched[i];
    const prevEnd = new Date(prev.endTime || prev.startTime).getTime();
    const currStart = new Date(curr.startTime).getTime();
    if (currStart - prevEnd > 60_000) {
      curr.sessionBreak = true;
    }
  }

  return stitched.slice(-100).reverse();
}

// Extract runtime info for each node from turn events
export function extractNodeInfo(events: DisplayEvent[]): NodeInfoMap {
  const info: NodeInfoMap = {
    sensing: [], telegram_input: [], intent_check: [], local_match: [],
    agent_call: [], agent_thinking: [], tool_exec: [],
    agent_response: [], tts_speak: [], schedule_trigger: [],
    lumi_gate: [], hw_action: [],
    ambient: [],
  };
  const fmtToken = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);
  const pushUnique = (arr: string[], line: string) => {
    if (!line) return;
    if (!arr.includes(line)) arr.push(line);
  };
  const pushAgentResponse = (line: string) => pushUnique(info.agent_response, line);
  const pushLLMTokens = (line: string) => {
    pushUnique(info.agent_call, line);
    pushUnique(info.agent_thinking, line);
    pushUnique(info.agent_response, line);
  };

  for (const ev of events) {
    if (ev.type === "sensing_input") {
      const m = ev.summary.match(/^\[([^\]]+)\]\s*(.*)/);
      if (m) {
        info.sensing.push(`type: ${m[1]}`, `"${m[2]}"`);
      } else {
        info.sensing.push(ev.summary);
      }
    }
    {
      const aNode = ev.detail?.node ?? "";
      const isAmbientInfo = ev.type === "ambient_action" ||
        ((ev.type === "flow_event" || ev.type === "flow_enter" || ev.type === "flow_exit") &&
         aNode.startsWith("ambient_") && aNode !== "ambient_pause" && aNode !== "ambient_resume");
      if (isAmbientInfo) {
        const sub = aNode.replace("ambient_", "") || ev.summary || "";
        if (info.ambient.length < 3) info.ambient.push(`${sub}: ${ev.summary || "active"}`);
      }
    }
    if (ev.type === "schedule_trigger" || ev.type === "cron_fire" ||
        (ev.type === "flow_event" && (ev.detail?.node === "schedule_trigger" || ev.detail?.node === "cron_fire"))) {
      const d = ev.detail as Record<string, string> | undefined;
      info.schedule_trigger.push(d?.name ?? ev.summary ?? "cron fired");
    }
    if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
      const msg = parseTelegramSummary(ev.summary);
      info.telegram_input.push(`"${msg || TELEGRAM_FALLBACK_MESSAGE}"`);
    }
    if (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match")) {
      info.local_match.push(ev.summary);
    }
    if (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send")) {
      info.intent_check.push("→ agent route");
      info.agent_call.push(`msg: "${ev.summary}"`);
    }
    if (ev.type === "tool_call" || (ev.type === "flow_event" && ev.detail?.node === "tool_call")) {
      const d = ev.detail as Record<string, any> | undefined;
      const toolName = d?.tool ?? d?.data?.tool ?? "unknown";
      const rawArgs = d?.args ?? d?.data?.args ?? "";
      let argsSummary = "";
      if (rawArgs) {
        try {
          const parsed = typeof rawArgs === "string" ? JSON.parse(rawArgs) : rawArgs;
          if (parsed?.command) {
            const match = (parsed.command as string).match(/(?:POST|GET|PUT|DELETE)\s+(http\S+)/i);
            argsSummary = match ? match[1].replace(/^https?:\/\/127\.0\.0\.1:\d+/, "") : (parsed.command as string).slice(0, 60);
          } else {
            argsSummary = JSON.stringify(parsed).slice(0, 60);
          }
        } catch { argsSummary = String(rawArgs).slice(0, 60); }
      }
      const entry = `⚙ ${toolName}${argsSummary ? `: ${argsSummary}` : ""}`;
      if (!info.tool_exec.includes(entry)) info.tool_exec.push(entry);
    }
    if (ev.type === "thinking" || (ev.type === "flow_event" && ev.detail?.node === "lifecycle_start")) {
      if (ev.type === "thinking" && ev.summary && info.agent_thinking.length < 2) {
        info.agent_thinking.push(`"${ev.summary}…"`);
      }
      if (ev.type === "flow_event" && info.agent_thinking.length === 0) {
        info.agent_thinking.push("reasoning…");
      }
    }
    if (ev.type === "chat_response" || (ev.type === "flow_event" && ev.detail?.node === "lifecycle_end")) {
      const d = ev.detail as Record<string, any> | undefined;
      if (d?.message && info.agent_response.length < 2) {
        info.agent_response.push(`"${d.message}…"`);
      }
      const dataErr = d?.data?.error;
      if (dataErr && info.agent_response.length < 2) {
        info.agent_response.push(`❌ ${dataErr}`);
      }
    }
    if (ev.type === "tts" || (ev.type === "flow_event" && ev.detail?.node === "tts_send")) {
      const d = ev.detail as Record<string, any> | undefined;
      const text = d?.data?.text ?? d?.text ?? "";
      if (text && info.tts_speak.length < 2) {
        info.tts_speak.push(`🔊 "${text}"`);
      }
      if (text && info.agent_response.length < 2) {
        const preview = text.length > 80 ? text.slice(0, 80) + "…" : text;
        info.agent_response.push(`"${preview}"`);
      }
    }
    if (ev.type === "lifecycle") {
      if (ev.phase === "start") info.agent_call.push(`run: ${ev.runId ?? "?"}`);
      if (ev.phase === "end") {
        pushAgentResponse(ev.error ? `❌ ${ev.error}` : "✓ done");
        const d = ev.detail as Record<string, string> | undefined;
        if (d?.inputTokens) {
          const inp = parseInt(d.inputTokens, 10);
          const out = parseInt(d.outputTokens ?? "0", 10);
          pushLLMTokens(`tokens: ${fmtToken(inp)} in / ${fmtToken(out)} out`);
        }
      }
    }
    if (ev.type === "flow_event" && ev.detail?.node === "token_usage") {
      const d = ev.detail as Record<string, any> | undefined;
      const u = d?.data;
      const inTok = Number(u?.input_tokens ?? 0);
      const outTok = Number(u?.output_tokens ?? 0);
      const cacheRead = Number(u?.cache_read_tokens ?? 0);
      const cacheWrite = Number(u?.cache_write_tokens ?? 0);
      const total = Number(u?.total_tokens ?? 0);
      if (inTok || outTok) pushLLMTokens(`tokens: ${fmtToken(inTok)} in / ${fmtToken(outTok)} out`);
      if (cacheRead || cacheWrite) pushLLMTokens(`cache: ${fmtToken(cacheRead)} read / ${fmtToken(cacheWrite)} write`);
      if (total) pushLLMTokens(`total: ${fmtToken(total)}`);
    }
    if (ev.type === "flow_event" && ev.detail?.node === "lifecycle_end") {
      const d = ev.detail as Record<string, any> | undefined;
      const err = d?.data?.error;
      if (err) info.agent_response.push(`❌ ${err}`);
    }
    if (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match")) {
      const d = ev.detail as Record<string, any> | undefined;
      const tts = d?.data?.tts ?? d?.tts ?? "";
      if (tts && info.tts_speak.length < 3) info.tts_speak.push(`💡 ${tts}`);
    }
  }
  return info;
}

// Extract input/output summary from a turn
export function turnIO(turn: Turn): { input: string; output: string; hwOutput: string } {
  let input = "";
  let output = "";
  let outputFromIntent = false;
  let hwOutput = "";
  const turnRunId = turn.runId;
  for (const ev of turn.events) {
    const evRunId = extractEventRunId(ev);
    const sameRun = !turnRunId || !evRunId || evRunId === turnRunId;
    if (!input && (ev.type === "sensing_input" || (ev.type === "flow_enter" && ev.detail?.node === "sensing_input")
        || (ev.type === "flow_event" && ev.detail?.node === "sensing_input"))) {
      const d = ev.detail as Record<string, any> | undefined;
      const dataMsg = d?.data?.message ?? d?.message;
      const m = ev.summary.match(/^\[([^\]]+)\]\s*(.*)/);
      input = dataMsg || (m ? m[2] : "") || ev.summary;
    }
    if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
      const d = ev.detail as Record<string, any> | undefined;
      const fullMsg = d?.message ?? d?.data?.message;
      const sender = d?.sender ?? d?.data?.sender;
      const msg = fullMsg || parseTelegramSummary(ev.summary);
      if (msg) {
        input = sender ? `[${sender}] ${msg}` : msg;
      } else if (!input) {
        input = TELEGRAM_FALLBACK_MESSAGE;
      }
    }
    if (!input && turn.type.startsWith("ambient:")) {
      input = turn.type.replace("ambient:", "") + " behavior";
    }
    if (!input && (ev.type === "schedule_trigger" || ev.type === "cron_fire")) {
      const d = ev.detail as Record<string, any> | undefined;
      input = d?.name ?? d?.data?.name ?? ev.summary ?? "scheduled task";
    }
    if (!input && (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send"))) {
      const d = ev.detail as Record<string, any> | undefined;
      const raw = (d?.message ?? ev.summary ?? "").trim();
      const m = raw.match(/^\[sensing:[^\]]+\]\s*(.*)$/i);
      const extracted = (m?.[1] ?? "").trim();
      if (extracted) input = extracted;
    }
    if (sameRun && (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match"))) {
      const d = ev.detail as Record<string, any> | undefined;
      output = d?.data?.tts ?? d?.tts ?? ev.summary ?? output;
      outputFromIntent = true;
    }
    if (!outputFromIntent && sameRun && (ev.type === "tts" || (ev.type === "flow_event" && ev.detail?.node === "tts_send"))) {
      const d = ev.detail as Record<string, any> | undefined;
      output = d?.data?.text ?? d?.text ?? ev.summary ?? output;
    }
    if (!output && sameRun && ev.type === "chat_response" && ev.state === "final") {
      const d = ev.detail as Record<string, any> | undefined;
      output = d?.message ?? ev.summary ?? "";
    }
    if (turn.type.startsWith("ambient:") && ev.type === "flow_exit" && ev.detail?.node?.startsWith("ambient_")) {
      output = ev.summary || "done";
    }
    if (ev.type === "tool_call" || (ev.type === "flow_event" && ev.detail?.node === "tool_call")) {
      const d = ev.detail as Record<string, any> | undefined;
      const args = d?.args ?? d?.data?.args ?? "";
      if (args) {
        const argsStr = typeof args === "string" ? args : JSON.stringify(args);
        const m = argsStr.match(/(?:POST|GET|PUT|DELETE)\s+(http\S+)/i);
        if (m) {
          const endpoint = m[1].replace(/^https?:\/\/127\.0\.0\.1:\d+/, "");
          if (endpoint && !hwOutput.includes(endpoint)) {
            hwOutput += (hwOutput ? ", " : "") + endpoint;
          }
        }
      }
    }
  }
  return { input, output, hwOutput };
}

export function turnTokenStats(turn: Turn): { inTok: number; outTok: number; cacheRead: number; cacheWrite: number; total: number } | null {
  let inTok = 0;
  let outTok = 0;
  let cacheRead = 0;
  let cacheWrite = 0;
  let total = 0;

  for (const ev of turn.events) {
    if (ev.type === "flow_event" && ev.detail?.node === "token_usage") {
      const d = ev.detail as Record<string, any> | undefined;
      const u = d?.data ?? {};
      inTok = Math.max(inTok, Number(u.input_tokens ?? 0));
      outTok = Math.max(outTok, Number(u.output_tokens ?? 0));
      cacheRead = Math.max(cacheRead, Number(u.cache_read_tokens ?? 0));
      cacheWrite = Math.max(cacheWrite, Number(u.cache_write_tokens ?? 0));
      total = Math.max(total, Number(u.total_tokens ?? 0));
      continue;
    }

    if (ev.type === "lifecycle" && ev.phase === "end" && ev.detail) {
      const d = ev.detail as Record<string, any>;
      inTok = Math.max(inTok, Number(d.inputTokens ?? 0));
      outTok = Math.max(outTok, Number(d.outputTokens ?? 0));
      cacheRead = Math.max(cacheRead, Number(d.cacheRead ?? 0));
      cacheWrite = Math.max(cacheWrite, Number(d.cacheWrite ?? 0));
      total = Math.max(total, Number(d.totalTokens ?? 0));
    }
  }

  if (!inTok && !outTok && !cacheRead && !cacheWrite && !total) return null;
  if (!total && (inTok || outTok || cacheRead || cacheWrite)) {
    total = inTok + outTok + cacheRead + cacheWrite;
  }
  return { inTok, outTok, cacheRead, cacheWrite, total };
}
