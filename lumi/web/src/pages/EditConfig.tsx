import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { getDeviceConfig, updateDeviceConfig } from "@/lib/api";
import type { DeviceConfig } from "@/lib/api";
import type { ChannelType } from "@/types";

// ── inline style helpers matching monitor design system ──────────────────────

const S = {
  root: {
    display: "flex",
    height: "100vh",
    background: "var(--lm-bg)",
    color: "var(--lm-text)",
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
    fontSize: 13,
  } as React.CSSProperties,
  topbar: {
    padding: "10px 20px",
    borderBottom: "1px solid var(--lm-border)",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexShrink: 0,
  } as React.CSSProperties,
  content: {
    flex: 1,
    minHeight: 0,
    overflowY: "auto" as const,
    padding: "20px",
  },
  main: {
    flex: 1,
    minWidth: 0,
    display: "flex",
    flexDirection: "column" as const,
    overflow: "hidden",
  },
  card: {
    background: "var(--lm-card)",
    border: "1px solid var(--lm-border)",
    borderRadius: 12,
    padding: 16,
    marginBottom: 14,
  } as React.CSSProperties,
  cardLabel: {
    fontSize: 10,
    fontWeight: 600,
    color: "var(--lm-text-dim)",
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
    marginBottom: 14,
  },
  label: {
    display: "block",
    fontSize: 11,
    color: "var(--lm-text-dim)",
    marginBottom: 4,
    marginTop: 10,
  } as React.CSSProperties,
  input: {
    width: "100%",
    background: "var(--lm-surface)",
    border: "1px solid var(--lm-border)",
    borderRadius: 6,
    padding: "7px 10px",
    fontSize: 12.5,
    color: "var(--lm-text)",
    outline: "none",
    boxSizing: "border-box" as const,
    transition: "border-color 0.15s",
  } as React.CSSProperties,
  inputFocus: {
    borderColor: "var(--lm-amber)",
  } as React.CSSProperties,
  select: {
    width: "100%",
    background: "var(--lm-surface)",
    border: "1px solid var(--lm-border)",
    borderRadius: 6,
    padding: "7px 10px",
    fontSize: 12.5,
    color: "var(--lm-text)",
    outline: "none",
    cursor: "pointer",
    boxSizing: "border-box" as const,
    appearance: "none" as const,
  } as React.CSSProperties,
  checkRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginTop: 12,
    cursor: "pointer",
  } as React.CSSProperties,
  btn: (disabled: boolean) => ({
    padding: "8px 20px",
    borderRadius: 8,
    fontSize: 12.5,
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    border: "none",
    background: disabled ? "var(--lm-surface)" : "var(--lm-amber)",
    color: disabled ? "var(--lm-text-muted)" : "#0C0B09",
    transition: "all 0.15s",
    opacity: disabled ? 0.6 : 1,
  } as React.CSSProperties),
  backLink: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    color: "var(--lm-text-dim)",
    textDecoration: "none",
    fontSize: 12.5,
    transition: "color 0.15s",
  } as React.CSSProperties,
  error: {
    background: "rgba(248,113,113,0.08)",
    border: "1px solid rgba(248,113,113,0.25)",
    borderRadius: 8,
    padding: "10px 14px",
    fontSize: 12,
    color: "var(--lm-red)",
    marginBottom: 14,
  } as React.CSSProperties,
  info: {
    background: "rgba(245,158,11,0.07)",
    border: "1px solid rgba(245,158,11,0.2)",
    borderRadius: 8,
    padding: "10px 14px",
    fontSize: 11.5,
    color: "var(--lm-text-dim)",
    marginBottom: 14,
    lineHeight: 1.5,
  } as React.CSSProperties,
};

// ── small reusable field ──────────────────────────────────────────────────────

function Field({
  label, id, value, onChange, placeholder, type = "text", autoComplete = "off",
}: {
  label: string; id: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string; autoComplete?: string;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <div>
      <label htmlFor={id} style={S.label}>{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{ ...S.input, ...(focused ? S.inputFocus : {}) }}
      />
    </div>
  );
}

function PasswordField({
  label, id, value, onChange, placeholder,
}: {
  label: string; id: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  const [focused, setFocused] = useState(false);
  return (
    <div>
      <label htmlFor={id} style={S.label}>{label}</label>
      <div style={{ position: "relative" }}>
        <input
          id={id}
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          style={{ ...S.input, paddingRight: 36, ...(focused ? S.inputFocus : {}) }}
        />
        <button
          type="button"
          onClick={() => setShow((v) => !v)}
          tabIndex={-1}
          style={{
            position: "absolute", right: 0, top: 0, height: "100%",
            padding: "0 10px", background: "none", border: "none",
            color: "var(--lm-text-muted)", cursor: "pointer", fontSize: 11,
          }}
        >
          {show ? "hide" : "show"}
        </button>
      </div>
    </div>
  );
}

// ── skeleton loader ───────────────────────────────────────────────────────────

function Skeleton({ w = "100%", h = 10 }: { w?: string | number; h?: number }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: 6,
      background: "var(--lm-surface)",
      animation: "lm-fade-in 1s ease-in-out infinite alternate",
    }} />
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function EditConfig() {
  const [loadingCfg, setLoadingCfg] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [deviceId, setDeviceId] = useState("");

  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmUrl, setLlmUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmDisableThinking, setLlmDisableThinking] = useState(false);

  const [deepgramApiKey, setDeepgramApiKey] = useState("");

  const [channel, setChannel] = useState<ChannelType>("telegram");
  const [teleToken, setTeleToken] = useState("");
  const [teleUserId, setTeleUserId] = useState("");
  const [slackBotToken, setSlackBotToken] = useState("");
  const [slackAppToken, setSlackAppToken] = useState("");
  const [slackUserId, setSlackUserId] = useState("");
  const [discordBotToken, setDiscordBotToken] = useState("");
  const [discordGuildId, setDiscordGuildId] = useState("");
  const [discordUserId, setDiscordUserId] = useState("");

  const [mqttEndpoint, setMqttEndpoint] = useState("");
  const [mqttPort, setMqttPort] = useState("");
  const [mqttUsername, setMqttUsername] = useState("");
  const [mqttPassword, setMqttPassword] = useState("");
  const [faChannel, setFaChannel] = useState("");
  const [fdChannel, setFdChannel] = useState("");

  useEffect(() => {
    getDeviceConfig()
      .then((cfg: DeviceConfig) => {
        setSsid(cfg.network_ssid ?? "");
        setDeviceId(cfg.device_id ?? "");
        setLlmApiKey(cfg.llm_api_key ?? "");
        setLlmUrl(cfg.llm_base_url ?? "");
        setLlmModel(cfg.llm_model ?? "");
        setLlmDisableThinking(cfg.llm_disable_thinking ?? false);
        setDeepgramApiKey(cfg.deepgram_api_key ?? "");
        setChannel((cfg.channel as ChannelType) || "telegram");
        setTeleToken(cfg.telegram_bot_token ?? "");
        setTeleUserId(cfg.telegram_user_id ?? "");
        setSlackBotToken(cfg.slack_bot_token ?? "");
        setSlackAppToken(cfg.slack_app_token ?? "");
        setSlackUserId(cfg.slack_user_id ?? "");
        setDiscordBotToken(cfg.discord_bot_token ?? "");
        setDiscordGuildId(cfg.discord_guild_id ?? "");
        setDiscordUserId(cfg.discord_user_id ?? "");
        setMqttEndpoint(cfg.mqtt_endpoint ?? "");
        setMqttPort(cfg.mqtt_port ? String(cfg.mqtt_port) : "");
        setMqttUsername(cfg.mqtt_username ?? "");
        setMqttPassword(cfg.mqtt_password ?? "");
        setFaChannel(cfg.fa_channel ?? "");
        setFdChannel(cfg.fd_channel ?? "");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingCfg(false));
  }, []);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      let channelCreds: Record<string, string> = {};
      if (channel === "telegram") {
        channelCreds = { telegram_bot_token: teleToken, telegram_user_id: teleUserId };
      } else if (channel === "slack") {
        channelCreds = { slack_bot_token: slackBotToken, slack_app_token: slackAppToken, slack_user_id: slackUserId };
      } else {
        channelCreds = { discord_bot_token: discordBotToken, discord_guild_id: discordGuildId, discord_user_id: discordUserId };
      }
      await updateDeviceConfig({
        ssid: ssid.trim(),
        ...(password ? { password } : {}),
        channel,
        ...channelCreds,
        llm_base_url: llmUrl,
        llm_api_key: llmApiKey,
        llm_model: llmModel,
        llm_disable_thinking: llmDisableThinking,
        deepgram_api_key: deepgramApiKey,
        device_id: deviceId,
        mqtt_endpoint: mqttEndpoint,
        mqtt_username: mqttUsername,
        mqtt_password: mqttPassword,
        mqtt_port: mqttPort ? parseInt(mqttPort, 10) : 0,
        fa_channel: faChannel,
        fd_channel: fdChannel,
      } as Parameters<typeof updateDeviceConfig>[0]);
      toast.success("Config saved — restart Lumi for changes to take effect.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    }
    setSaving(false);
  }, [
    channel, teleToken, teleUserId, slackBotToken, slackAppToken, slackUserId,
    discordBotToken, discordGuildId, discordUserId, ssid, password, llmUrl,
    llmApiKey, llmModel, llmDisableThinking, deepgramApiKey, deviceId,
    mqttEndpoint, mqttUsername, mqttPassword, mqttPort, faChannel, fdChannel,
  ]);

  return (
    <div className="lm-root" style={S.root}>
      <main style={S.main}>
        {/* Topbar */}
        <div style={S.topbar}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--lm-text)" }}>⚙ Settings</span>
          <a href="/monitor" style={S.backLink}>
            ← Monitor
          </a>
        </div>

        {/* Content */}
        <div style={S.content} className="lm-fade-in">
          <div style={{ maxWidth: 520 }}>

            {loadingCfg ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {[1, 2, 3].map((i) => (
                  <div key={i} style={S.card}>
                    <Skeleton h={8} w={80} />
                    <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
                      <Skeleton h={30} />
                      <Skeleton h={30} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <form onSubmit={handleSubmit}>
                {error && <div style={S.error}>{error}</div>}
                <div style={S.info}>
                  ↻ &nbsp;Restart Lumi after saving for LLM and channel changes to take effect.
                </div>

                {/* Wi-Fi */}
                <div style={S.card}>
                  <div style={S.cardLabel}>Wi-Fi</div>
                  <Field label="SSID" id="ssid" value={ssid} onChange={setSsid} placeholder="Network name" />
                  <PasswordField label="Password" id="password" value={password} onChange={setPassword} placeholder="Leave blank to keep current" />
                </div>

                {/* Device */}
                <div style={S.card}>
                  <div style={S.cardLabel}>Device</div>
                  <Field label="Device ID" id="device_id" value={deviceId} onChange={setDeviceId} placeholder="lumi-001" />
                </div>

                {/* LLM */}
                <div style={S.card}>
                  <div style={S.cardLabel}>LLM</div>
                  <Field label="API Key" id="llm_api_key" value={llmApiKey} onChange={setLlmApiKey} placeholder="sk-..." />
                  <Field label="Base URL" id="llm_url" value={llmUrl} onChange={setLlmUrl} placeholder="https://api.openai.com/v1" />
                  <Field label="Model" id="llm_model" value={llmModel} onChange={setLlmModel} placeholder="gpt-4o-mini" />
                  <label style={S.checkRow}>
                    <input
                      type="checkbox"
                      checked={llmDisableThinking}
                      onChange={(e) => setLlmDisableThinking(e.target.checked)}
                      style={{ accentColor: "var(--lm-amber)", width: 14, height: 14 }}
                    />
                    <span style={{ color: "var(--lm-text-dim)", fontSize: 12 }}>Disable extended thinking (faster responses)</span>
                  </label>
                </div>

                {/* Deepgram */}
                <div style={S.card}>
                  <div style={S.cardLabel}>Deepgram STT</div>
                  <Field label="API Key" id="deepgram_api_key" value={deepgramApiKey} onChange={setDeepgramApiKey} placeholder="dg-..." />
                </div>

                {/* Channel */}
                <div style={S.card}>
                  <div style={S.cardLabel}>Messaging Channel</div>
                  <label style={S.label}>Channel</label>
                  <select
                    value={channel}
                    onChange={(e) => setChannel(e.target.value as ChannelType)}
                    style={S.select}
                  >
                    <option value="telegram">Telegram</option>
                    <option value="slack">Slack</option>
                    <option value="discord">Discord</option>
                  </select>

                  {channel === "telegram" && (
                    <>
                      <Field label="Bot Token" id="tele_token" value={teleToken} onChange={setTeleToken} placeholder="123456:ABC-DEF..." />
                      <Field label="User ID" id="tele_user_id" value={teleUserId} onChange={setTeleUserId} placeholder="123456789" />
                    </>
                  )}
                  {channel === "slack" && (
                    <>
                      <Field label="Bot Token" id="slack_bot_token" value={slackBotToken} onChange={setSlackBotToken} placeholder="xoxb-..." />
                      <Field label="App Token" id="slack_app_token" value={slackAppToken} onChange={setSlackAppToken} placeholder="xapp-..." />
                      <Field label="User ID" id="slack_user_id" value={slackUserId} onChange={setSlackUserId} placeholder="U0123456789" />
                    </>
                  )}
                  {channel === "discord" && (
                    <>
                      <Field label="Bot Token" id="discord_bot_token" value={discordBotToken} onChange={setDiscordBotToken} placeholder="Bot token" />
                      <Field label="Guild ID" id="discord_guild_id" value={discordGuildId} onChange={setDiscordGuildId} placeholder="123456789" />
                      <Field label="User ID" id="discord_user_id" value={discordUserId} onChange={setDiscordUserId} placeholder="123456789" />
                    </>
                  )}
                </div>

                {/* MQTT */}
                <details style={{ marginBottom: 14 }}>
                  <summary style={{
                    cursor: "pointer", fontSize: 10, fontWeight: 600,
                    color: "var(--lm-text-muted)", textTransform: "uppercase",
                    letterSpacing: "0.08em", padding: "4px 0", userSelect: "none",
                  }}>
                    MQTT (optional)
                  </summary>
                  <div style={{ ...S.card, marginTop: 8, marginBottom: 0 }}>
                    <Field label="Endpoint" id="mqtt_endpoint" value={mqttEndpoint} onChange={setMqttEndpoint} placeholder="mqtt.example.com" />
                    <Field label="Port" id="mqtt_port" value={mqttPort} onChange={setMqttPort} placeholder="1883" type="number" />
                    <Field label="Username" id="mqtt_username" value={mqttUsername} onChange={setMqttUsername} placeholder="Optional" />
                    <PasswordField label="Password" id="mqtt_password" value={mqttPassword} onChange={setMqttPassword} placeholder="Optional" />
                    <Field label="FA Channel" id="fa_channel" value={faChannel} onChange={setFaChannel} placeholder="Lumi/f_a/device_id" />
                    <Field label="FD Channel" id="fd_channel" value={fdChannel} onChange={setFdChannel} placeholder="Lumi/f_d/device_id" />
                  </div>
                </details>

                <button type="submit" disabled={saving} style={S.btn(saving)}>
                  {saving ? "Saving…" : "Save Changes"}
                </button>
              </form>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
