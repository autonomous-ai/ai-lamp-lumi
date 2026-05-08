import camelcaseKeys from "camelcase-keys";
import type { NetworkItem, SetupRequest } from "@/types";

const API_BASE =
  import.meta.env.VITE_API_BASE ??
  import.meta.env.VITE_NETWORK_API ??
  import.meta.env.VITE_API_URL ??
  "";

/** 0 = error, 1 = success (matches backend JSONReponseStatus) */
export type JSONResponseStatus = 0 | 1;

export interface JSONResponse<T = unknown> {
  status: JSONResponseStatus;
  message: string | null;
  data: T;
}

async function apiRequest<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  const json = (await res.json()) as JSONResponse<T>;
  if (json.status !== 1) {
    const msg =
      typeof json.message === "string" ? json.message : res.ok ? "Request failed" : res.statusText;
    throw new Error(msg);
  }
  return json.data;
}

/**
 * Converts object keys from snake_case to camelCase (uses camelcase-keys).
 * Use for API responses that return snake_case keys.
 */
export function parseSnakeToCamel<T = Record<string, unknown>>(
  raw: Record<string, unknown>,
  options?: { deep?: boolean }
): T {
  return camelcaseKeys(raw as Record<string, unknown>, { deep: options?.deep ?? false }) as T;
}

export async function getNetworks(): Promise<NetworkItem[]> {
  return apiRequest<NetworkItem[]>(`${API_BASE}/api/network`);
}

export async function setupNetwork(ssid: string, password: string): Promise<string> {
  return apiRequest<string>(`${API_BASE}/api/network/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ssid, password }),
  });
}

export async function setupDevice(body: SetupRequest): Promise<boolean> {
  return apiRequest<boolean>(`${API_BASE}/api/device/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export interface SetupStatus {
  phase: "idle" | "connecting" | "connected" | "failed";
  lan_ip: string;
  error: string;
}

/** Polled by Setup.tsx during the AP→STA transition. Returns the device's
 *  current setup phase plus the LAN IP once Wi-Fi is associated, so the web
 *  client can redirect the user to the new URL. */
export async function getSetupStatus(): Promise<SetupStatus> {
  return apiRequest<SetupStatus>(`${API_BASE}/api/device/setup/status`);
}

export async function checkInternet(): Promise<boolean> {
  return apiRequest<boolean>(`${API_BASE}/api/network/check-internet`);
}


export async function getSetup(): Promise<boolean> {
  return apiRequest<boolean>(`${API_BASE}/api/setup`);
}

export interface DeviceConfig {
  channel: string;
  telegram_bot_token: string;
  telegram_user_id: string;
  slack_bot_token: string;
  slack_app_token: string;
  slack_user_id: string;
  discord_bot_token: string;
  discord_guild_id: string;
  discord_user_id: string;
  llm_api_key: string;
  llm_model: string;
  llm_base_url: string;
  llm_disable_thinking: boolean;
  deepgram_api_key: string;
  stt_api_key: string;
  tts_api_key: string;
  stt_base_url: string;
  tts_base_url: string;
  stt_language: string;
  stt_model: string;
  tts_provider: string;
  tts_voice: string;
  device_id: string;
  network_ssid: string;
  network_password: string;
  mqtt_endpoint: string;
  mqtt_username: string;
  mqtt_password: string;
  mqtt_port: number;
  fa_channel: string;
  fd_channel: string;
}

export async function getTTSVoices(provider?: string): Promise<string[]> {
  const params = provider ? `?provider=${provider}` : "";
  return apiRequest<string[]>(`${API_BASE}/api/device/voices${params}`);
}

export async function getTTSProviders(): Promise<string[]> {
  return apiRequest<string[]>(`${API_BASE}/api/device/tts-providers`);
}

export interface TestTTSOptions {
  text?: string;
  provider?: string;
  ttsApiKey?: string;
  ttsBaseUrl?: string;
  llmApiKey?: string;
  llmBaseUrl?: string;
}

export async function testTTSVoice(voice: string, opts: TestTTSOptions = {}): Promise<void> {
  const apiKey = (opts.ttsApiKey && opts.ttsApiKey.trim()) || opts.llmApiKey || "";
  const baseUrl = (opts.ttsBaseUrl && opts.ttsBaseUrl.trim()) || opts.llmBaseUrl || "";
  await fetch("/hw/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: opts.text || "[laugh] Hey! How are you doing today?",
      voice,
      provider: opts.provider || undefined,
      tts_api_key: apiKey || undefined,
      tts_base_url: baseUrl || undefined,
    }),
  });
}

export async function getDeviceConfig(): Promise<DeviceConfig> {
  return apiRequest<DeviceConfig>(`${API_BASE}/api/device/config`);
}

export async function updateDeviceConfig(body: Partial<DeviceConfig> & { password?: string; ssid?: string }): Promise<boolean> {
  return apiRequest<boolean>(`${API_BASE}/api/device/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}