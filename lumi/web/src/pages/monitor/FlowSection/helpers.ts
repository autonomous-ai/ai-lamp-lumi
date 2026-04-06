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

export function turnHasVoicePipeline(turn: Turn): boolean {
  return turn.events.some((ev) =>
    (ev.type === "flow_event" || ev.type === "flow_enter") && ev.detail?.node === "voice_pipeline_start",
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
  if (turn.type.startsWith("ambient:") || turn.type === "schedule") {
    return;
  }

  // Reclassify "telegram" turns that are actually sensing events routed via OpenClaw channel.
  // node-host is Lumi's own WebSocket identity in OpenClaw — it sends sensing events AND
  // voice commands via chat.send, so sender=node-host alone doesn't mean "system".
  if (turn.type === "telegram") {
    let hasRealUser = false;
    let sensingType: string | null = null;
    let hasSystemMsg = false;
    const systemPatterns = [/you just woke up/i, /\[sensing:[^\]]+\]/i];
    for (const ev of turn.events) {
      if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
        const d = ev.detail as Record<string, any> | undefined;
        const msg = d?.message ?? d?.data?.message ?? ev.summary ?? "";
        const sender = d?.sender ?? d?.data?.sender ?? "";
        if (sender && sender !== "node-host") hasRealUser = true;
        const sensM = msg.match(/\[sensing:([^\]]+)\]/i);
        if (sensM && !sensingType) sensingType = sensM[1];
        if (systemPatterns.some((p) => p.test(msg))) hasSystemMsg = true;
      }
    }
    if (hasRealUser) return; // keep as telegram
    if (sensingType) { turn.type = sensingType; return; }
    if (hasSystemMsg) { turn.type = "system"; return; }
    // node-host but normal message (e.g. voice command relayed via chat.send) — keep as telegram
    return;
  }

  // Voice/voice_command always wins — it's the user's actual intent even if mixed with passive sensing
  let sawVoice = false;
  let sawVoiceCommand = false;
  for (const ev of turn.events) {
    // Check bracket label [voice] / [voice_command]
    const t = sensingInputBracketType(ev);
    if (t === "voice_command") sawVoiceCommand = true;
    else if (t === "voice") sawVoice = true;
    // Also check data.type field (sensing_input / flow_enter events carry type in detail.data.type)
    if (ev.type === "sensing_input" || (ev.type === "flow_enter" && ev.detail?.node === "sensing_input")) {
      const d = ev.detail as Record<string, any> | undefined;
      const dtype = d?.data?.type ?? d?.type ?? "";
      if (dtype === "voice_command") sawVoiceCommand = true;
      else if (dtype === "voice") sawVoice = true;
    }
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
      // Check if message already available (resolved event) and is a sensing event
      const d = ev.detail as Record<string, any> | undefined;
      const msg = d?.message ?? d?.data?.message ?? ev.summary ?? "";
      const sensingMatch = msg.match(/\[sensing:([^\]]+)\]/i);
      if (sensingMatch) {
        return { type: sensingMatch[1], path: "agent", boundary: "chat" as const };
      }
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
      // If another turn already claimed this runId, suffix with seq to keep IDs unique.
      // This prevents duplicate-id bugs in selection (click turn A, turn B stays highlighted).
      let turnId = evRunId || `turn-${ev._seq}`;
      if (evRunId && turns.some((t) => t.id === evRunId)) {
        turnId = `${evRunId}:${ev._seq}`;
      }
      current = {
        id: turnId,
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

    // Split turn when a new lifecycle_start arrives after the turn already saw a lifecycle_end.
    // This handles multiple OpenClaw agent turns mapped to the same device run_id
    // (e.g. sensing + telegram arriving close together while trace is still active).
    const isLifecycleStart = (ev.type === "lifecycle" && ev.phase === "start") ||
      (ev.type === "flow_event" && ev.detail?.node === "lifecycle_start");
    const hasLifecycleEnd = current.events.some((e) =>
      (e.type === "lifecycle" && e.phase === "end") ||
      (e.type === "flow_event" && e.detail?.node === "lifecycle_end"));
    if (isLifecycleStart && hasLifecycleEnd) {
      turns.push(current);
      current = {
        id: evRunId || `turn-${ev._seq}`,
        runId: evRunId || current.runId,
        startTime: ev.time,
        type: "unknown",
        path: "agent",
        status: "active",
        events: [ev],
      };
      continue;
    }

    current.events.push(ev);
    // Classify unknown turns from chat_input events
    if (current.type === "unknown" && (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input"))) {
      const d = ev.detail as Record<string, any> | undefined;
      const msg = d?.message ?? d?.data?.message ?? ev.summary ?? "";
      const sensingMatch = msg.match(/\[sensing:([^\]]+)\]/i);
      current.type = sensingMatch ? sensingMatch[1] : "telegram";
    }
    if (!current.runId && evRunId) {
      current.runId = evRunId;
      current.id = evRunId;
    }
    // Re-check type on every event so sensing-via-channel turns reclassify immediately
    refineTurnTypeFromSensingInputs(current);

    if (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match")) {
      current.path = "local";
    } else if (current.path !== "local") {
      const belongsToTurn = !current.runId || !evRunId || evRunId === current.runId;
      if (belongsToTurn && (evRunId || ev.type === "lifecycle" || ev.type === "thinking")) {
        current.path = "agent";
      }
    }

    if ((ev.type === "lifecycle" && (ev.phase === "end" || ev.phase === "error")) ||
        (ev.type === "flow_event" && ev.detail?.node === "lifecycle_end")) {
      current.status = (ev.phase === "error" || ev.error) ? "error" : "done";
      current.endTime = ev.time;
    }
    if (ev.type === "intent_match") {
      current.status = "done";
      current.endTime = ev.time;
    }
    if (ev.type === "flow_event" && (ev.detail?.node === "tts_send" || ev.detail?.node === "no_reply")) {
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
    // Done turn with no recognizable input source → unknown
    if (turn.status === "done" && !turnHasSensingInput(turn) && !turnHasRealTelegramInput(turn) && !turnHasVoicePipeline(turn)) {
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
    mic_input: [], cam_input: [], telegram_input: [], intent_check: [], local_match: [],
    agent_call: [], agent_thinking: [], tool_exec: [],
    agent_response: [], tts_speak: [], schedule_trigger: [],
    lumi_gate: [], hw_led: [], hw_servo: [], hw_emotion: [], hw_audio: [], tg_out: [],
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

  // Sensing → lifecycle timing (used for agent_call node info below)
  let sensingEnterTs = 0;
  let lifecycleStartTs = 0;
  for (const ev of events) {
    const ts = new Date(ev.time).getTime();
    if (ev.type === "sensing_input" || (ev.type === "flow_enter" && ev.detail?.node === "sensing_input")
        || (ev.type === "flow_event" && ev.detail?.node === "sensing_input")) {
      if (!sensingEnterTs) sensingEnterTs = ts;
    }
    if (ev.type === "flow_event" && ev.detail?.node === "lifecycle_start") {
      if (!lifecycleStartTs) lifecycleStartTs = ts;
    }
  }
  for (const ev of events) {
    if (ev.type === "sensing_input") {
      const m = ev.summary.match(/^\[([^\]]+)\]\s*(.*)/);
      const sType = m?.[1] ?? "";
      const isCam = /motion|presence|light/i.test(sType);
      const target = isCam ? info.cam_input : info.mic_input;
      if (m) {
        target.push(`type: ${m[1]}`, `"${m[2]}"`);
      } else {
        target.push(ev.summary);
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
      const d = ev.detail as Record<string, any> | undefined;
      const msg = d?.data?.message ?? d?.message ?? "";
      const tts = d?.data?.tts ?? d?.tts ?? "";
      const rule = d?.data?.rule ?? d?.rule ?? "";
      const actions: string[] = d?.data?.actions ?? d?.actions ?? [];
      info.intent_check.push("⚡ local match");
      const parts = [`"${msg}" → ${tts}`];
      if (rule) parts.push(`rule: ${rule}`);
      for (const a of actions) {
        // Convert "POST /path {body}" to full curl command
        const m = a.match(/^(POST|GET|PUT|DELETE)\s+(\/\S+)\s*(.*)?$/);
        if (m) {
          const [, method, path, body] = m;
          let curl = `curl -s -X ${method} http://127.0.0.1:5001${path}`;
          if (body) curl += ` -H "Content-Type: application/json" -d '${body}'`;
          parts.push(`🔧 ${curl}`);
        } else {
          parts.push(`🔧 ${a}`);
        }
      }
      info.local_match.push(msg ? parts.join("\n") : ev.summary);
    }
    if (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send")) {
      info.intent_check.push("→ agent route");
      const d = ev.detail as Record<string, any> | undefined;
      const hasImage = d?.data?.has_image || d?.has_image;
      const imgBytes = Number(d?.data?.image_bytes ?? d?.image_bytes ?? 0);
      const chatMsg = d?.data?.message ?? d?.message ?? "";
      if (hasImage) info.agent_call.push(`📷 image attached (~${Math.round(imgBytes * 3 / 4 / 1024)}KB)`);
      if (chatMsg) {
        // Extract [snapshot: /path] if present
        const snapMatch = chatMsg.match(/\[snapshot:\s*([^\]]+)\]/);
        if (snapMatch) {
          info.agent_call.push(`🖼 snapshot: ${snapMatch[1].trim()}`);
        }
        // Replace any earlier 📩 from sensing_input with the exact text sent to OpenClaw
        const idx = info.agent_call.findIndex((l) => l.startsWith("📩"));
        if (idx >= 0) info.agent_call[idx] = `📩 ${chatMsg}`;
        else info.agent_call.push(`📩 ${chatMsg}`);
      }
    }
    // Show input message on agent_call node (fallback if chat_send hasn't fired yet)
    if (ev.type === "sensing_input" || (ev.type === "flow_enter" && ev.detail?.node === "sensing_input")) {
      const d = ev.detail as Record<string, any> | undefined;
      const msg = d?.data?.message ?? d?.message ?? ev.summary ?? "";
      if (msg && !info.agent_call.some((l) => l.startsWith("📩"))) {
        info.agent_call.push(`📩 ${msg}`);
      }
    }
    if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
      const d = ev.detail as Record<string, any> | undefined;
      const msg = d?.message ?? d?.data?.message ?? "";
      const sender = d?.sender ?? d?.data?.sender ?? "";
      if (msg && !info.agent_call.some((l) => l.startsWith("📩"))) {
        info.agent_call.push(`📩 ${sender ? `[${sender}] ` : ""}${msg}`);
      }
    }
    if (ev.type === "tool_call" || (ev.type === "flow_event" && ev.detail?.node === "tool_call")) {
      const d = ev.detail as Record<string, any> | undefined;
      const phase = d?.phase ?? d?.data?.phase ?? "";
      // Only show tool start (has args), skip update/result phases
      if (phase !== "start" && phase !== "") continue;
      const rawArgs = d?.args ?? d?.data?.args ?? "";
      let argsSummary = "";
      if (rawArgs) {
        try {
          const parsed = typeof rawArgs === "string" ? JSON.parse(rawArgs) : rawArgs;
          if (parsed?.command) {
            argsSummary = (parsed.command as string);
          } else {
            argsSummary = JSON.stringify(parsed);
          }
        } catch { argsSummary = String(rawArgs); }
      }
      if (argsSummary) {
        const entry = `🔧 ${argsSummary}`;
        if (!info.tool_exec.includes(entry)) info.tool_exec.push(entry);
        // Also surface emotion/led/servo tool calls in their HW nodes with LLM source label
        if (/\/emotion/.test(argsSummary)) pushUnique(info.hw_emotion, `🤖 LLM tool → ${argsSummary}`);
        else if (/\/led|\/scene/.test(argsSummary)) pushUnique(info.hw_led, `🤖 LLM tool → ${argsSummary}`);
        else if (/\/servo/.test(argsSummary)) pushUnique(info.hw_servo, `🤖 LLM tool → ${argsSummary}`);
      }
    }
    if (ev.type === "thinking" || (ev.type === "flow_event" && ev.detail?.node === "lifecycle_start")) {
      if (ev.type === "thinking" && ev.summary) {
        info.agent_thinking.push(`"${ev.summary}…"`);
      }
      if (ev.type === "flow_event" && info.agent_thinking.length === 0) {
        info.agent_thinking.push("reasoning…");
      }
    }
    // Thinking from chat.history (fallback when streaming too fast)
    if (ev.type === "flow_event" && ev.detail?.node === "agent_thinking") {
      const d = ev.detail as Record<string, any> | undefined;
      const text = d?.data?.text ?? d?.text ?? "";
      if (text && !info.agent_thinking.some((l) => l.startsWith("🧠"))) {
        info.agent_thinking.push(`🧠 ${text}`);
      }
    }
    if (ev.type === "flow_event" && ev.detail?.node === "no_reply") {
      pushAgentResponse("🚫 [no reply] — agent decided to do nothing");
    }
    if (ev.type === "chat_response" || (ev.type === "flow_event" && ev.detail?.node === "lifecycle_end")) {
      const d = ev.detail as Record<string, any> | undefined;
      if (d?.message && !info.agent_response.some((l) => l.startsWith('"'))) {
        info.agent_response.push(`"${d.message}"`);
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
      if (text && !info.agent_response.some((l) => l.startsWith('"'))) {
        info.agent_response.push(`"${text}"`);
      }
    }
    if (ev.type === "lifecycle") {
      if (ev.phase === "start") info.agent_call.push(`run: ${ev.runId ?? "?"}`);
      if (ev.phase === "error") {
        pushAgentResponse(`❌ ${ev.error ?? ev.summary ?? "error"}`);
      }
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
      // Effective (billed) tokens: cache read costs 10% of input price
      const billed = inTok + cacheWrite + Math.round(cacheRead * 0.1) + outTok;
      if (billed) pushLLMTokens(`billed: ~${fmtToken(billed)}`);
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
    if (ev.type === "hw_emotion" || (ev.type === "flow_event" && ev.detail?.node === "hw_emotion")) {
      const body = ev.summary ?? (ev.detail as Record<string, any> | undefined)?.args ?? "";
      if (body) {
        const curl = `curl -s -X POST http://127.0.0.1:5001/emotion -H "Content-Type: application/json" -d '${body}'`;
        pushUnique(info.hw_emotion, `⚡ HW marker → ${curl}`);
      }
    }
    if (ev.type === "hw_led" || (ev.type === "flow_event" && ev.detail?.node === "hw_led")) {
      const body = ev.summary ?? (ev.detail as Record<string, any> | undefined)?.args ?? "";
      if (body) pushUnique(info.hw_led, `⚡ HW marker → curl -s -X POST http://127.0.0.1:5001/led -d '${body}'`);
    }
    if (ev.type === "hw_servo" || (ev.type === "flow_event" && ev.detail?.node === "hw_servo")) {
      const body = ev.summary ?? (ev.detail as Record<string, any> | undefined)?.args ?? "";
      if (body) pushUnique(info.hw_servo, `⚡ HW marker → curl -s -X POST http://127.0.0.1:5001/servo/play -d '${body}'`);
    }
  }
  // After processing all events: if lifecycle_end was seen but no response/no_reply, mark silent
  const hasLifecycleEnd = events.some((e) =>
    (e.type === "lifecycle" && e.phase === "end") ||
    (e.type === "flow_event" && e.detail?.node === "lifecycle_end"));
  const hasNoReply = events.some((e) => e.type === "flow_event" && e.detail?.node === "no_reply");
  if (hasLifecycleEnd && info.agent_response.length === 0 && !hasNoReply) {
    info.agent_response.push("💤 no output — processed silently");
  }

  // --- Per-node duration from timestamp deltas ---
  const fmtDur = (ms: number) => ms >= 60_000 ? `${(ms / 60_000).toFixed(1)}m`
    : ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;

  let nSensingTs = 0, nChatSendTs = 0, nChatInputTs = 0;
  let nLifecycleStartTs = 0, nLifecycleEndTs = 0, nTtsTs = 0;
  let nFirstToolTs = 0, nLastToolResultTs = 0;
  let nToolTotalMs = 0, nToolStartTs = 0;
  let nIntentMatchTs = 0;
  let nSensingExitDur = 0; // duration_ms from flow_exit:sensing_input
  let nLastBatchResultTs = 0, nInterToolMs = 0; // inter-tool LLM thinking

  for (const ev of events) {
    const ts = new Date(ev.time).getTime();
    if (ev.type === "sensing_input" || (ev.type === "flow_enter" && ev.detail?.node === "sensing_input")
        || (ev.type === "flow_event" && ev.detail?.node === "sensing_input")) {
      if (!nSensingTs) nSensingTs = ts;
    }
    if (ev.type === "flow_exit" && ev.detail?.node === "sensing_input") {
      const dataObj = typeof ev.detail?.data === "string" ? (() => { try { return JSON.parse(ev.detail!.data); } catch { return null; } })() : null;
      const dur = Number(ev.detail?.dur_ms ?? dataObj?.dur_ms ?? 0);
      if (dur > 0) nSensingExitDur = dur;
    }
    if (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match")) {
      if (!nIntentMatchTs) nIntentMatchTs = ts;
    }
    if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
      if (!nChatInputTs) nChatInputTs = ts;
    }
    if (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send")) {
      if (!nChatSendTs) nChatSendTs = ts;
    }
    if (ev.type === "flow_event" && ev.detail?.node === "lifecycle_start") {
      if (!nLifecycleStartTs) nLifecycleStartTs = ts;
    }
    if (ev.type === "flow_event" && ev.detail?.node === "lifecycle_end") {
      nLifecycleEndTs = ts;
    }
    if (ev.type === "tts" || (ev.type === "flow_event" && ev.detail?.node === "tts_send")) {
      if (!nTtsTs) nTtsTs = ts;
    }
    const isToolCall = ev.type === "tool_call" || (ev.type === "flow_event" && ev.detail?.node === "tool_call");
    if (isToolCall) {
      const d = ev.detail as Record<string, any> | undefined;
      const phase = d?.data?.phase ?? d?.phase ?? "";
      if (phase === "start") {
        if (!nFirstToolTs) nFirstToolTs = ts;
        if (nLastBatchResultTs && ts > nLastBatchResultTs) {
          nInterToolMs += ts - nLastBatchResultTs;
          nLastBatchResultTs = 0;
        }
        nToolStartTs = ts;
      }
      if (phase === "result") {
        nLastToolResultTs = ts;
        nLastBatchResultTs = ts;
        if (nToolStartTs) { nToolTotalMs += ts - nToolStartTs; nToolStartTs = 0; }
      }
    }
  }

  // sensing_input exit duration → mic/cam input node
  if (nSensingExitDur > 0) {
    const dur = fmtDur(nSensingExitDur);
    if (info.mic_input.length > 0) info.mic_input.unshift(`⏱ ${dur}`);
    else if (info.cam_input.length > 0) info.cam_input.unshift(`⏱ ${dur}`);
  }

  // intent_check: sensing → chat_send or intent_match (whichever comes first)
  if (nSensingTs || nChatInputTs) {
    const from = nSensingTs || nChatInputTs;
    const to = nIntentMatchTs || nChatSendTs;
    if (to && to > from) {
      const ms = to - from;
      info.intent_check.unshift(`⏱ ${fmtDur(ms)}`);
    }
  }

  // local_match: intent_match duration (instant, but show if > 0)
  // (local_match is triggered by intent_match, timing is included in intent_check)

  // agent_call: chat_send → lifecycle_start
  if (nChatSendTs && nLifecycleStartTs) {
    const ms = nLifecycleStartTs - nChatSendTs;
    if (ms > 0) info.agent_call.unshift(`⏱ ${fmtDur(ms)}`);
  } else if (nChatInputTs && nLifecycleStartTs) {
    const ms = nLifecycleStartTs - nChatInputTs;
    if (ms > 0) info.agent_call.unshift(`⏱ ${fmtDur(ms)}`);
  }

  // agent_thinking: lifecycle_start → first tool_call (TTFT) + inter-tool thinking
  if (nLifecycleStartTs) {
    const to = nFirstToolTs || nLifecycleEndTs;
    if (to && to > nLifecycleStartTs) {
      const ttft = to - nLifecycleStartTs;
      const totalThinking = ttft + nInterToolMs;
      if (nInterToolMs > 0) {
        info.agent_thinking.unshift(`⏱ ${fmtDur(totalThinking)} (first ${fmtDur(ttft)} + between tools ${fmtDur(nInterToolMs)})`);
      } else {
        info.agent_thinking.unshift(`⏱ ${fmtDur(ttft)}`);
      }
    }
  }

  // tool_exec: total tool execution time
  if (nToolTotalMs > 0) {
    info.tool_exec.unshift(`⏱ ${fmtDur(nToolTotalMs)}`);
  }

  // agent_response: last tool_result → lifecycle_end (or lifecycle_start → lifecycle_end if no tools)
  if (nLastToolResultTs && nLifecycleEndTs && nLifecycleEndTs > nLastToolResultTs) {
    const ms = nLifecycleEndTs - nLastToolResultTs;
    if (ms > 0) info.agent_response.unshift(`⏱ ${fmtDur(ms)}`);
  }

  // tts_speak: lifecycle_end → tts_send
  if (nLifecycleEndTs && nTtsTs) {
    const ms = nTtsTs - nLifecycleEndTs;
    if (ms > 0 && ms < 30_000) info.tts_speak.unshift(`⏱ ${fmtDur(ms)}`);
  } else if (nIntentMatchTs && nTtsTs) {
    // Local path: intent_match → tts
    const ms = nTtsTs - nIntentMatchTs;
    if (ms > 0 && ms < 30_000) info.tts_speak.unshift(`⏱ ${fmtDur(ms)}`);
  }

  return info;
}

// Timing breakdown for a turn — displayed as a summary bar above the pipeline
export interface TurnTiming {
  total: number;       // start → end (ms)
  segments: { label: string; ms: number; color: string; from?: string; to?: string }[];
}

export function extractTurnTiming(events: DisplayEvent[], startTime?: string, endTime?: string): TurnTiming | null {
  if (!startTime || !endTime) return null;
  const totalMs = new Date(endTime).getTime() - new Date(startTime).getTime();
  if (!Number.isFinite(totalMs) || totalMs <= 0) return null;

  const fmtDur = (ms: number) => ms >= 60_000 ? `${(ms / 60_000).toFixed(1)}m`
    : ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;

  let sensingTs = 0, chatSendTs = 0, chatInputTs = 0;
  let lifecycleStartTs = 0, lifecycleEndTs = 0, ttsTs = 0;
  let firstToolCallTs = 0, lastToolResultTs = 0;
  let toolTotalMs = 0, toolStartTs = 0;
  // Track inter-tool LLM thinking: time between a batch of tool results and the next tool start.
  let lastBatchResultTs = 0, interToolMs = 0;

  for (const ev of events) {
    const ts = new Date(ev.time).getTime();
    if (ev.type === "sensing_input" || (ev.type === "flow_enter" && ev.detail?.node === "sensing_input")
        || (ev.type === "flow_event" && ev.detail?.node === "sensing_input")) {
      if (!sensingTs) sensingTs = ts;
    }
    if (ev.type === "chat_input" || (ev.type === "flow_event" && ev.detail?.node === "chat_input")) {
      if (!chatInputTs) chatInputTs = ts;
    }
    if (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send")) {
      if (!chatSendTs) chatSendTs = ts;
    }
    if (ev.type === "flow_event" && ev.detail?.node === "lifecycle_start") {
      if (!lifecycleStartTs) lifecycleStartTs = ts;
    }
    if (ev.type === "flow_event" && ev.detail?.node === "lifecycle_end") {
      lifecycleEndTs = ts;
    }
    if (ev.type === "tts" || (ev.type === "flow_event" && ev.detail?.node === "tts_send")) {
      if (!ttsTs) ttsTs = ts;
    }
    const isToolCall = ev.type === "tool_call" || (ev.type === "flow_event" && ev.detail?.node === "tool_call");
    if (isToolCall) {
      const d = ev.detail as Record<string, any> | undefined;
      const phase = d?.data?.phase ?? d?.phase ?? "";
      if (phase === "start") {
        if (!firstToolCallTs) firstToolCallTs = ts;
        // If a previous batch finished, the gap is LLM thinking between rounds.
        if (lastBatchResultTs && ts > lastBatchResultTs) {
          interToolMs += ts - lastBatchResultTs;
          lastBatchResultTs = 0;
        }
        toolStartTs = ts;
      }
      if (phase === "result") {
        lastToolResultTs = ts;
        lastBatchResultTs = ts;
        if (toolStartTs) { toolTotalMs += ts - toolStartTs; toolStartTs = 0; }
      }
    }
  }

  const segments: TurnTiming["segments"] = [];
  // Sensing / input processing — typically <5ms, only show if notable (>50ms)
  if (sensingTs && chatSendTs) {
    const ms = chatSendTs - sensingTs;
    if (ms > 50) segments.push({ label: `lelamp detect ${fmtDur(ms)}`, ms, color: "var(--lm-amber)", from: "sensing_input (lumi)", to: "chat_send (lumi)" });
  }

  // Queue → OpenClaw start
  const callTs = chatSendTs || chatInputTs;
  if (callTs && lifecycleStartTs) {
    const ms = lifecycleStartTs - callTs;
    if (ms > 0) segments.push({ label: `openclaw init ${fmtDur(ms)}`, ms, color: "var(--lm-blue)", from: "chat_send (lumi)", to: "lifecycle_start (openclaw)" });
  }

  // Thinking (TTFT)
  if (lifecycleStartTs && firstToolCallTs) {
    const ms = firstToolCallTs - lifecycleStartTs;
    segments.push({ label: `llm thinking ${fmtDur(ms)}`, ms, color: "var(--lm-purple)", from: "lifecycle_start (openclaw)", to: "first tool_call (openclaw)" });
  } else if (lifecycleStartTs && lifecycleEndTs && !firstToolCallTs) {
    const ms = lifecycleEndTs - lifecycleStartTs;
    segments.push({ label: `llm processing ${fmtDur(ms)}`, ms, color: "var(--lm-purple)", from: "lifecycle_start (openclaw)", to: "lifecycle_end (openclaw)" });
  }

  // Tool exec
  if (toolTotalMs > 0) {
    segments.push({ label: `tool exec ${fmtDur(toolTotalMs)}`, ms: toolTotalMs, color: "#f59e0b", from: "tool_call start (openclaw)", to: "tool_call result (lumi)" });
  }

  // Inter-tool LLM thinking (between tool call batches)
  if (interToolMs > 0) {
    segments.push({ label: `llm thinking ${fmtDur(interToolMs)}`, ms: interToolMs, color: "var(--lm-purple)", from: "tool_call result (batch N)", to: "tool_call start (batch N+1)" });
  }

  // Response gen (last tool result → lifecycle_end)
  if (lastToolResultTs && lifecycleEndTs) {
    const ms = lifecycleEndTs - lastToolResultTs;
    if (ms > 0) segments.push({ label: `llm response ${fmtDur(ms)}`, ms, color: "var(--lm-green)", from: "last tool_call result (lumi)", to: "lifecycle_end (openclaw)" });
  }

  // TTS latency
  if (lifecycleEndTs && ttsTs) {
    const ms = ttsTs - lifecycleEndTs;
    if (ms > 0 && ms < 30_000) segments.push({ label: `tts send ${fmtDur(ms)}`, ms, color: "#ec4899", from: "lifecycle_end (openclaw)", to: "tts_send (lumi)" });
  }

  return { total: totalMs, segments };
}

// Extract total duration (ms) from a turn's start/end times.
export function turnDurationMs(turn: Turn): number {
  if (!turn.startTime || !turn.endTime) return 0;
  const ms = new Date(turn.endTime).getTime() - new Date(turn.startTime).getTime();
  return ms > 0 ? ms : 0;
}

// Extract billed tokens from a turn's token_usage event.
// Billed = input + cache_write + ceil(cache_read * 0.1) + output.
export function turnBilledTokens(turn: Turn): number {
  for (const ev of turn.events) {
    if (ev.type === "flow_event" && ev.detail?.node === "token_usage") {
      const u = (ev.detail as Record<string, any>)?.data;
      const inTok = Number(u?.input_tokens ?? 0);
      const outTok = Number(u?.output_tokens ?? 0);
      const cacheRead = Number(u?.cache_read_tokens ?? 0);
      const cacheWrite = Number(u?.cache_write_tokens ?? 0);
      return inTok + cacheWrite + Math.round(cacheRead * 0.1) + outTok;
    }
  }
  return 0;
}

// Extract input/output summary from a turn
export function turnIO(turn: Turn): { input: string; output: string; hwOutput: string; snapshotUrl: string } {
  let input = "";
  let output = "";
  let outputFromIntent = false;
  let hwOutput = "";
  let snapshotUrl = "";
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
    if (ev.type === "chat_send" || (ev.type === "flow_event" && ev.detail?.node === "chat_send")) {
      const d = ev.detail as Record<string, any> | undefined;
      const raw = (d?.data?.message ?? d?.message ?? ev.summary ?? "").trim();
      // Extract snapshot path → convert to API URL
      const snap = raw.match(/\[snapshot:\s*\/tmp\/lumi-sensing-snapshots\/(sensing_[^\]]+\.jpg)\]/);
      if (snap && !snapshotUrl) {
        snapshotUrl = `/api/sensing/snapshot/${snap[1]}`;
      }
      if (!input) {
        const m = raw.match(/^\[sensing:[^\]]+\]\s*(.*)$/is);
        const extracted = (m?.[1] ?? "").replace(/\n?\[snapshot:[^\]]+\]/, "").trim();
        if (extracted) input = extracted;
      }
    }
    if (sameRun && (ev.type === "intent_match" || (ev.type === "flow_event" && ev.detail?.node === "intent_match"))) {
      const d = ev.detail as Record<string, any> | undefined;
      output = d?.data?.tts ?? d?.tts ?? ev.summary ?? output;
      outputFromIntent = true;
      const actions: string[] = d?.data?.actions ?? d?.actions ?? [];
      for (const a of actions) {
        const m = a.match(/^(?:POST|GET|PUT|DELETE)\s+(\/\S+)/);
        if (m && !hwOutput.includes(m[1])) {
          hwOutput += (hwOutput ? ", " : "") + m[1];
        }
      }
    }
    if (!outputFromIntent && sameRun && (ev.type === "tts" || (ev.type === "flow_event" && ev.detail?.node === "tts_send"))) {
      const d = ev.detail as Record<string, any> | undefined;
      output = d?.data?.text ?? d?.text ?? ev.summary ?? output;
    }
    if (!output && sameRun && ev.type === "chat_response" && ev.state === "final") {
      const d = ev.detail as Record<string, any> | undefined;
      output = d?.message ?? ev.summary ?? "";
    }
    // Detect no_reply from flow event (persisted in JSONL, unlike SSE chat_response)
    if (!output && sameRun && ev.type === "flow_event" && ev.detail?.node === "no_reply") {
      output = "[no reply]";
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
  return { input, output, hwOutput, snapshotUrl };
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
