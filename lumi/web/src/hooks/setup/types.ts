// Shared types between Setup.tsx and its custom hooks.

export type SectionId =
  | "wifi" | "device" | "llm" | "language" | "deepgram"
  | "tts" | "channel" | "mqtt" | "voice" | "face";

export interface LlmLoadedState {
  apiKey: boolean;
  baseUrl: boolean;
  model: boolean;
}

export interface ChannelLoadedState {
  teleToken: boolean;
  teleUserId: boolean;
  slackBotToken: boolean;
  slackAppToken: boolean;
  slackUserId: boolean;
  discordBotToken: boolean;
  discordGuildId: boolean;
  discordUserId: boolean;
}
