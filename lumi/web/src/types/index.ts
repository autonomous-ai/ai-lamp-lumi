/** Network item (from GET /api/network) */
export interface NetworkItem {
  bssid: string;
  ssid: string;
  mode: string;
  channel: number;
  rate: string;
  signal: number;
  security: string;
}

export type ChannelType = "telegram" | "slack" | "discord";

/** Request body for POST /api/device/setup */
export interface SetupRequest {
  ssid: string;
  password: string;
  channel: ChannelType;
  telegram_bot_token?: string;
  telegram_user_id?: string;
  slack_bot_token?: string;
  slack_app_token?: string;
  slack_user_id?: string;
  discord_bot_token?: string;
  discord_user_id?: string;
  llm_base_url: string;
  llm_api_key: string;
  llm_model: string;
  device_id?: string;
  /** MQTT (optional): empty endpoint means MQTT disabled, auto-fetched via ping */
  mqtt_endpoint?: string;
  mqtt_port?: number;
  mqtt_username?: string;
  mqtt_password?: string;
  fa_channel?: string;
  fd_channel?: string;
}
