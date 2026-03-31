import type { DisplayEvent } from "../types";

// Maps a MonitorEvent type/node to a flow stage ID
export type FlowStage =
  | "sensing" | "telegram_input" | "intent_check" | "local_match"
  | "agent_call" | "agent_thinking" | "tool_exec" | "agent_response" | "tts_speak"
  | "schedule_trigger" | "lumi_gate" | "hw_action";

/** No pipeline node highlighted — e.g. no matching triggers in recent events */
export type ActiveFlowStage = FlowStage | "idle";

export interface FlowNodeDef {
  id: FlowStage;
  label: string;
  short: string;
  icon: string;
  color: string;
  desc: string;
  triggers: string[];
  path: "main" | "fast" | "agent";
}

// Group events into turns by runId
export interface Turn {
  id: string;
  runId?: string;
  boundary?: "mic" | "chat";
  boundaryInstanceSeq?: number;
  startTime: string;
  sessionBreak?: boolean;
  endTime?: string;
  type: string;
  path: "local" | "agent" | "unknown";
  status: "active" | "done" | "error";
  events: DisplayEvent[];
}

// Runtime detail lines
export type NodeInfoMap = Record<FlowStage, string[]> & { ambient: string[] };

export const FLOW_NODES: FlowNodeDef[] = [
  { id: "sensing",
    label: "Sensing", short: "SENSE", icon: "📡", color: "var(--lm-amber)", path: "main",
    desc: "POST /sensing/event · voice / motion / sound",
    triggers: [
      "sensing_input",
      "flow_enter:sensing_input", "flow_exit:sensing_input", "flow_event:sensing_input",
      "flow_enter:voice_pipeline_start", "flow_event:voice_pipeline_start",
    ] },

  { id: "telegram_input",
    label: "Telegram In", short: "TG IN", icon: "💬", color: "#229ed9", path: "main",
    desc: "Inbound message via Telegram / Slack / Discord",
    triggers: [
      "chat_input",
      "flow_event:chat_input",
    ] },

  { id: "intent_check",
    label: "Intent Check", short: "INTENT", icon: "🔀", color: "var(--lm-teal)", path: "main",
    desc: "Route to local match or agent call",
    triggers: [
      "chat_send",
      "flow_event:chat_send", "flow_enter:chat_send", "flow_exit:chat_send",
      "flow_event:agent_call",
    ] },

  { id: "local_match",
    label: "Local Intent", short: "LOCAL", icon: "⚡", color: "var(--lm-green)", path: "fast",
    desc: "Fast path ~50ms · regex match → instant TTS · bypasses agent",
    triggers: [
      "intent_match",
      "flow_event:intent_match", "flow_enter:intent_match", "flow_exit:intent_match",
    ] },

  { id: "agent_call",
    label: "Agent Call", short: "AGENT", icon: "🤖", color: "var(--lm-blue)", path: "agent",
    desc: "WebSocket chat.send RPC to OpenClaw",
    triggers: [
      "flow_event:agent_call", "flow_enter:agent_call", "flow_exit:agent_call",
      "flow_event:lifecycle_start",
    ] },

  { id: "agent_thinking",
    label: "Thinking", short: "THINK", icon: "🧠", color: "var(--lm-purple)", path: "agent",
    desc: "LLM reasoning · streaming thinking tokens",
    triggers: [
      "thinking",
      "flow_event:lifecycle_start",
    ] },

  { id: "tool_exec",
    label: "Tool Exec", short: "TOOL", icon: "🔧", color: "#f59e0b", path: "agent",
    desc: "Agent invoked a tool · function call",
    triggers: [
      "tool_call",
      "flow_event:tool_call", "flow_enter:tool_call", "flow_exit:tool_call",
    ] },

  { id: "agent_response",
    label: "Response", short: "RESP", icon: "💡", color: "var(--lm-green)", path: "agent",
    desc: "Agent turn ended · response accumulated",
    triggers: [
      "chat_response",
      "flow_event:lifecycle_end",
    ] },

  { id: "tts_speak",
    label: "TTS Speak", short: "TTS", icon: "🔊", color: "var(--lm-purple)", path: "agent",
    desc: "POST /voice/speak · text-to-speech output",
    triggers: [
      "tts",
      "flow_event:tts_send", "flow_enter:tts_send", "flow_exit:tts_send",
      "intent_match", "flow_event:intent_match",
      "flow_event:voice_pipeline_start",
    ] },

  { id: "schedule_trigger",
    label: "Schedule", short: "CRON", icon: "⏰", color: "#f97316", path: "main",
    desc: "Cron/timer fired · agent turn triggered by schedule",
    triggers: [
      "schedule_trigger", "flow_event:schedule_trigger",
      "flow_enter:schedule_trigger", "flow_exit:schedule_trigger",
      "flow_event:cron_fire", "cron_fire",
    ] },

  { id: "lumi_gate",
    label: "Lumi Gate", short: "GATE", icon: "🚦", color: "var(--lm-teal)", path: "agent",
    desc: "WS listener · suppress TTS if music · pause ambient if LED",
    triggers: [
      "led_set", "led_off", "ambient_pause", "ambient_resume",
      "flow_event:led_set", "flow_event:led_off",
    ] },

  { id: "hw_action",
    label: "Hardware", short: "HARDWARE", icon: "💡", color: "var(--lm-amber)", path: "agent",
    desc: "LeLamp hardware · LED / servo / audio · called directly by OpenClaw tool",
    triggers: [
      "led_set", "led_off",
      "flow_event:led_set", "flow_event:led_off",
      "tool_call",
      "flow_event:tool_call",
    ] },
];

// Source type → icon map
export const SOURCE_ICON: Record<string, string> = {
  voice: "🎤", motion: "👁", sound: "🔊", environment: "🌡", system: "⚙", unknown: "❓",
  telegram: "💬", schedule: "⏰",
  "ambient:breathing": "💨", "ambient:movement": "🤖", "ambient:mumble": "💭",
  "ambient:idle": "😴",
};

export const TELEGRAM_FALLBACK_MESSAGE = "Message from telegram";
export const TURN_INPUT_FALLBACK = "Input not captured";
