import { useMemo } from "react";

export interface SetupUrlParams {
  teleToken: string;
  teleUserId: string;
  slackBotToken: string;
  slackAppToken: string;
  slackUserId: string;
  discordBotToken: string;
  discordGuildId: string;
  discordUserId: string;
  llmApiKey: string;
  llmUrl: string;
  llmModel: string;
  deepgramApiKey: string;
  ttsApiKey: string;
  ttsBaseUrl: string;
  deviceId: string;
  mqttEndpoint: string;
  mqttPort: string;
  mqttUsername: string;
  mqttPassword: string;
  faChannel: string;
  fdChannel: string;
  sttLanguage: string;
  ttsProvider: string;
  ttsVoice: string;
}

export function useSetupUrlParams(searchParams: URLSearchParams): SetupUrlParams {
  return useMemo(
    () => ({
      teleToken: searchParams.get("tele_token") ?? "",
      teleUserId: searchParams.get("tele_user_id") ?? "",
      slackBotToken: searchParams.get("slack_bot_token") ?? "",
      slackAppToken: searchParams.get("slack_app_token") ?? "",
      slackUserId: searchParams.get("slack_user_id") ?? "",
      discordBotToken: searchParams.get("discord_bot_token") ?? "",
      discordGuildId: searchParams.get("discord_guild_id") ?? "",
      discordUserId: searchParams.get("discord_user_id") ?? "",
      llmApiKey: searchParams.get("llm_api_key") ?? "",
      llmUrl: searchParams.get("llm_url") ?? "",
      llmModel: searchParams.get("llm_model") ?? "",
      deepgramApiKey: searchParams.get("deepgram_api_key") ?? "",
      ttsApiKey: searchParams.get("tts_api_key") ?? "",
      ttsBaseUrl: searchParams.get("tts_base_url") ?? "",
      deviceId: searchParams.get("device_id") ?? "",
      mqttEndpoint: searchParams.get("mqtt_endpoint") ?? "",
      mqttPort: searchParams.get("mqtt_port") ?? "",
      mqttUsername: searchParams.get("mqtt_username") ?? "",
      mqttPassword: searchParams.get("mqtt_password") ?? "",
      faChannel: searchParams.get("fa_channel") ?? "",
      fdChannel: searchParams.get("fd_channel") ?? "",
      sttLanguage: searchParams.get("stt_language") ?? "",
      ttsProvider: searchParams.get("tts_provider") ?? "",
      ttsVoice: searchParams.get("tts_voice") ?? "",
    }),
    [searchParams],
  );
}
