export const API = "/api";
export const HW  = "/hw";
export const HISTORY_LEN = 60;
export const FLOW_EVENTS_MAX = 5000;

// ─── Types ──────────────────────────────────────────────────────────────────

export interface SystemInfo {
  cpuLoad: number;
  memTotal: number;
  memUsed: number;
  memPercent: number;
  cpuTemp: number;
  uptime: number;
  goRoutines: number;
  version: string;
  deviceId: string;
  diskTotal: number;
  diskUsed: number;
  diskPercent: number;
}
export interface NetworkInfo {
  ssid: string;
  ip: string;
  publicIp: string;
  signal: number;
  internet: boolean;
}
export interface HWHealth {
  status: string;
  servo: boolean;
  led: boolean;
  camera: boolean;
  audio: boolean;
  sensing: boolean;
  voice: boolean;
  tts: boolean;
  display: boolean;
}
export interface OCStatus {
  name: string;
  connected: boolean;
  sessionKey: boolean;
  emotion?: string;
}
export interface PresenceInfo {
  state: string;
  enabled: boolean;
  seconds_since_motion: number;
}
export interface VoiceStatus {
  voice_available: boolean;
  voice_listening: boolean;
  tts_available: boolean;
  tts_speaking: boolean;
}
export interface ServoState {
  available_recordings: string[];
  current: string | null;
  bus_connected?: boolean;
  robot_connected?: boolean;
}
export interface DisplayState {
  mode: string;
  hardware: boolean;
  available_expressions: string[];
}
export interface AudioVolume {
  control: string;
  volume: number;
}
export interface LEDColor {
  led_count: number;
  on: boolean;
  color: [number, number, number];
  hex: string;
  brightness: number;
  effect: string | null;
  scene: string | null;
}
export interface SceneInfo {
  scenes: string[];
  active?: string;
}
export interface MonitorEvent {
  id: string;
  time: string;
  type: string;
  summary: string;
  detail?: Record<string, string> | null;
  runId?: string;
  phase?: string;
  state?: string;
  error?: string;
}
// UI-augmented version with local seq id
export interface DisplayEvent extends MonitorEvent {
  _seq: number;
}

export type Section = "overview" | "system" | "flow" | "camera" | "servo" | "analytics" | "logs";

export const NAV: { id: Section; label: string; icon: string }[] = [
  { id: "overview",   label: "Overview",   icon: "◈" },
  { id: "system",     label: "System",     icon: "⬡" },
  { id: "flow",       label: "Flow",       icon: "⬢" },
  { id: "camera",     label: "Camera",     icon: "⬟" },
  { id: "servo",      label: "Servo",      icon: "⚙" },
  { id: "analytics",  label: "Analytics",  icon: "◉" },
  { id: "logs",       label: "Logs",       icon: "☰" },
];
