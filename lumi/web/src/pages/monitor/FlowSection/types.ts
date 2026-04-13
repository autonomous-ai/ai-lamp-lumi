import type { DisplayEvent } from "../types";

// Maps a MonitorEvent type/node to a flow stage ID
export type FlowStage =
  | "mic_input" | "cam_input" | "telegram_input" | "intent_check" | "local_match"
  | "agent_call" | "agent_thinking" | "tool_exec" | "agent_response" | "tts_speak"
  | "schedule_trigger" | "lumi_gate" | "hw_led" | "hw_servo" | "hw_emotion" | "hw_audio" | "tg_out" | "tg_alert";

/** No pipeline node highlighted — e.g. no matching triggers in recent events */
export type ActiveFlowStage = FlowStage | "idle";

export type NodeShape = "circle" | "hexagon" | "diamond" | "square";

export interface FlowNodeDef {
  id: FlowStage;
  label: string;
  short: string;
  icon: string;
  color: string;
  desc: string;
  triggers: string[];
  path: "main" | "fast" | "agent";
  shape?: NodeShape; // default: circle
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
  path: "local" | "agent" | "dropped" | "unknown";
  status: "active" | "done" | "error";
  events: DisplayEvent[];
}

// Runtime detail lines
export type NodeInfoMap = Record<FlowStage, string[]> & { ambient: string[] };

export const FLOW_NODES: FlowNodeDef[] = [
  { id: "mic_input",
    label: "Mic Input", short: "MIC", icon: "🎤", color: "var(--lm-amber)", path: "main",
    shape: "hexagon",
    desc: "Voice / sound from microphone",
    triggers: [
      "flow_enter:voice_pipeline_start", "flow_event:voice_pipeline_start",
    ] },

  { id: "cam_input",
    label: "Cam Input", short: "CAM", icon: "👁", color: "var(--lm-amber)", path: "main",
    shape: "hexagon",
    desc: "Motion / presence / light from camera",
    triggers: [] },

  { id: "telegram_input",
    label: "Telegram In", short: "TG IN", icon: "💬", color: "#229ed9", path: "main",
    shape: "hexagon",
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
      "intent_match", "flow_event:intent_match",
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
      "flow_event:agent_thinking",
    ] },

  { id: "tool_exec",
    label: "Tool Exec", short: "TOOL", icon: "🔧", color: "#f59e0b", path: "agent",
    desc: "Agent invoked a tool · function call",
    triggers: [
      "tool_call",
      "flow_event:tool_call", "flow_enter:tool_call", "flow_exit:tool_call",
      "hw_call", "flow_event:hw_call",
    ] },

  { id: "agent_response",
    label: "Response", short: "RESP", icon: "💡", color: "var(--lm-green)", path: "agent",
    desc: "Agent turn ended · may respond or [no reply] (do nothing)",
    triggers: [
      "chat_response",
      "flow_event:lifecycle_end",
      "flow_event:no_reply",
      "hw_only_reply", "flow_event:hw_only_reply",
    ] },

  { id: "tts_speak",
    label: "TTS Speak", short: "TTS", icon: "🔊", color: "var(--lm-purple)", path: "agent",
    shape: "diamond",
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
    label: "Lumi Hook", short: "HOOK", icon: "🚦", color: "var(--lm-teal)", path: "agent",
    shape: "square",
    desc: "Lumi middleware · parse [HW:] markers · dispatch HW calls\n→ emotion / LED / servo / audio\n→ TTS (suppress if music)\n→ Telegram broadcast\n→ pause ambient if LED changed",
    triggers: [
      "led_set", "led_off", "ambient_pause", "ambient_resume",
      "flow_event:led_set", "flow_event:led_off",
      "flow_event:tts_suppressed",
      "hw_emotion", "flow_event:hw_emotion",
      "hw_led", "flow_event:hw_led",
      "hw_servo", "flow_event:hw_servo",
      "hw_audio", "flow_event:hw_audio",
      "flow_event:tts_send",
      "flow_event:no_reply",
      "flow_event:hw_only_reply",
      "flow_event:telegram_alert_broadcast",
    ] },

  { id: "tg_out",
    label: "Telegram Out", short: "TG OUT", icon: "💬", color: "#229ed9", path: "agent",
    shape: "diamond",
    desc: "OpenClaw delivers response to Telegram / Slack / Discord",
    triggers: [
      "flow_event:telegram_alert_broadcast",
    ] },

  { id: "tg_alert",
    label: "Broadcast", short: "BCAST", icon: "📢", color: "#e53935", path: "agent",
    shape: "diamond",
    desc: "Broadcast to all Telegram sessions (guard alerts, wellbeing reminders, music suggestions)",
    triggers: [
      "flow_event:telegram_alert_broadcast",
    ] },

  { id: "hw_led",
    label: "LED", short: "LED", icon: "🔆", color: "var(--lm-amber)", path: "agent",
    shape: "diamond",
    desc: "LED control · solid color / effect / scene / off",
    triggers: [
      "hw_led", "led_set", "led_off",
      "flow_event:hw_led", "flow_event:led_set", "flow_event:led_off",
    ] },

  { id: "hw_servo",
    label: "Servo", short: "SERVO", icon: "🤖", color: "#8b5cf6", path: "agent",
    shape: "diamond",
    desc: "Servo motor · aim direction / play animation",
    triggers: [
      "hw_servo",
      "flow_event:hw_servo",
    ] },

  { id: "hw_emotion",
    label: "Emotion", short: "EMO", icon: "😀", color: "#ec4899", path: "agent",
    shape: "diamond",
    desc: "Emotion expression · coordinated LED + servo + display eyes",
    triggers: [
      "hw_emotion", "emotion",
      "flow_event:hw_emotion", "flow_event:emotion",
    ] },

  { id: "hw_audio",
    label: "Audio", short: "AUDIO", icon: "🎵", color: "#a855f7", path: "agent",
    shape: "diamond",
    desc: "Music / audio playback · speaker output",
    triggers: [
      "hw_audio",
      "flow_event:hw_audio",
    ] },
];

// Source type → icon map
export const SOURCE_ICON: Record<string, string> = {
  voice: "🎤", sound: "🔊",
  motion: "👁", "motion.activity": "🏃", "presence.enter": "🙂", "presence.leave": "👋", "presence.away": "😴", "light.level": "🌡",
  "wellbeing.hydration": "💧", "wellbeing.break": "🧘", "wellbeing.music": "🎵",
  environment: "🌡", system: "⚙", unknown: "❓",
  telegram: "💬", schedule: "⏰",
  cron: "⏰", "cron:hydration": "💧", "cron:break": "🧘", "cron:music": "🎵",
  "ambient:breathing": "💨", "ambient:movement": "🤖", "ambient:mumble": "💭",
  "ambient:idle": "😴",
  "music.mood": "🎵",
};

export const TELEGRAM_FALLBACK_MESSAGE = "Message from telegram";
export const TURN_INPUT_FALLBACK = "Input not captured";
