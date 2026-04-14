import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import { getDeviceConfig, updateDeviceConfig, getTTSVoices } from "@/lib/api";
import type { DeviceConfig } from "@/lib/api";
import type { ChannelType } from "@/types";

// ── CSS vars / helpers ────────────────────────────────────────────────────────

const C = {
  bg:        "var(--lm-bg)",
  sidebar:   "var(--lm-sidebar)",
  card:      "var(--lm-card)",
  surface:   "var(--lm-surface)",
  border:    "var(--lm-border)",
  amber:     "var(--lm-amber)",
  amberDim:  "var(--lm-amber-dim)",
  text:      "var(--lm-text)",
  textDim:   "var(--lm-text-dim)",
  textMuted: "var(--lm-text-muted)",
  red:       "var(--lm-red)",
  green:     "var(--lm-green)",
};

type SectionId = "wifi" | "device" | "llm" | "deepgram" | "tts" | "channel" | "mqtt";
const SECTIONS: { id: SectionId; label: string; icon: string }[] = [
  { id: "wifi",     label: "Wi-Fi",    icon: "⬡" },
  { id: "device",   label: "Device",   icon: "◈" },
  { id: "llm",      label: "LLM",      icon: "⬢" },
  { id: "deepgram", label: "STT",      icon: "◉" },
  { id: "tts",      label: "TTS",      icon: "◎" },
  { id: "channel",  label: "Channel",  icon: "⬟" },
  { id: "mqtt",     label: "MQTT",     icon: "☰" },
];

// ── small components ──────────────────────────────────────────────────────────

function Field({
  label, id, value, onChange, placeholder, type = "text",
}: {
  label: string; id: string; value: string;
  onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <div style={{ marginBottom: 12 }}>
      <label htmlFor={id} style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
        {label}
      </label>
      <input
        id={id} type={type} value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder} autoComplete="off"
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          width: "100%", boxSizing: "border-box",
          background: C.surface, border: `1px solid ${focused ? C.amber : C.border}`,
          borderRadius: 7, padding: "8px 11px",
          fontSize: 12.5, color: C.text, outline: "none",
          transition: "border-color 0.15s",
        }}
      />
    </div>
  );
}

function PasswordField({ label, id, value, onChange, placeholder }: {
  label: string; id: string; value: string;
  onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  const [focused, setFocused] = useState(false);
  return (
    <div style={{ marginBottom: 12 }}>
      <label htmlFor={id} style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
        {label}
      </label>
      <div style={{ position: "relative" }}>
        <input
          id={id} type={show ? "text" : "password"} value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder} autoComplete="off"
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          style={{
            width: "100%", boxSizing: "border-box",
            background: C.surface, border: `1px solid ${focused ? C.amber : C.border}`,
            borderRadius: 7, padding: "8px 38px 8px 11px",
            fontSize: 12.5, color: C.text, outline: "none",
            transition: "border-color 0.15s",
          }}
        />
        <button type="button" onClick={() => setShow((v) => !v)} tabIndex={-1}
          style={{
            position: "absolute", right: 0, top: 0, height: "100%",
            padding: "0 11px", background: "none", border: "none",
            color: C.textMuted, cursor: "pointer", fontSize: 11,
          }}
        >
          {show ? "hide" : "show"}
        </button>
      </div>
    </div>
  );
}

function SectionCard({ id, title, children }: { id: SectionId; title: string; children: React.ReactNode }) {
  return (
    <div
      id={`section-${id}`}
      style={{
        background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 12, padding: "18px 20px", marginBottom: 16,
        scrollMarginTop: 16,
      }}
    >
      <div style={{
        fontSize: 10, fontWeight: 700, color: C.textDim,
        textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 16,
      }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function SkeletonBlock() {
  const bar = (w: string | number, h = 10) => (
    <div style={{ width: w, height: h, borderRadius: 6, background: C.surface, marginBottom: 10 }} />
  );
  return (
    <>
      {[1, 2, 3, 4].map((i) => (
        <div key={i} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: "18px 20px", marginBottom: 16 }}>
          {bar(80, 8)}
          <div style={{ marginTop: 14 }}>{bar("100%", 32)}{bar("100%", 32)}</div>
        </div>
      ))}
    </>
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function EditConfig() {
  const [loadingCfg, setLoadingCfg] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionId>("wifi");
  const contentRef = useRef<HTMLDivElement>(null);

  // form state
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmUrl, setLlmUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmDisableThinking, setLlmDisableThinking] = useState(false);
  const [deepgramApiKey, setDeepgramApiKey] = useState("");
  const [ttsVoice, setTtsVoice] = useState("alloy");
  const [ttsVoices, setTtsVoices] = useState<string[]>([]);
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
        setPassword(cfg.network_password ?? "");
        setDeviceId(cfg.device_id ?? "");
        setLlmApiKey(cfg.llm_api_key ?? "");
        setLlmUrl(cfg.llm_base_url ?? "");
        setLlmModel(cfg.llm_model ?? "");
        setLlmDisableThinking(cfg.llm_disable_thinking ?? false);
        setDeepgramApiKey(cfg.deepgram_api_key ?? "");
        setTtsVoice(cfg.tts_voice || "alloy");
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
    getTTSVoices().then(setTtsVoices).catch(() => {});
  }, []);

  // scroll spy: update active section as user scrolls
  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const handler = () => {
      for (const s of [...SECTIONS].reverse()) {
        const node = document.getElementById(`section-${s.id}`);
        if (node && node.getBoundingClientRect().top <= 80) {
          setActiveSection(s.id);
          return;
        }
      }
      setActiveSection("wifi");
    };
    el.addEventListener("scroll", handler, { passive: true });
    return () => el.removeEventListener("scroll", handler);
  }, []);

  const scrollTo = (id: SectionId) => {
    setActiveSection(id);
    document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

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
        ssid: ssid.trim(), password,
        channel, ...channelCreds,
        llm_base_url: llmUrl, llm_api_key: llmApiKey, llm_model: llmModel,
        llm_disable_thinking: llmDisableThinking,
        deepgram_api_key: deepgramApiKey, tts_voice: ttsVoice, device_id: deviceId,
        mqtt_endpoint: mqttEndpoint, mqtt_username: mqttUsername,
        mqtt_password: mqttPassword,
        mqtt_port: mqttPort ? parseInt(mqttPort, 10) : 0,
        fa_channel: faChannel, fd_channel: fdChannel,
      } as Parameters<typeof updateDeviceConfig>[0]);
      toast.success("Config saved — restart Lumi for changes to take effect.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    }
    setSaving(false);
  }, [
    channel, teleToken, teleUserId, slackBotToken, slackAppToken, slackUserId,
    discordBotToken, discordGuildId, discordUserId, ssid, password, llmUrl,
    llmApiKey, llmModel, llmDisableThinking, deepgramApiKey, ttsVoice, deviceId,
    mqttEndpoint, mqttUsername, mqttPassword, mqttPort, faChannel, fdChannel,
  ]);

  return (
    <div className="lm-root" style={{
      display: "flex", height: "100vh",
      background: C.bg, color: C.text,
      fontFamily: "'Inter', 'Segoe UI', sans-serif", fontSize: 13,
    }}>

      {/* ── Sidebar ── */}
      <aside style={{
        width: 192, flexShrink: 0,
        background: C.sidebar, borderRight: `1px solid ${C.border}`,
        display: "flex", flexDirection: "column",
      }}>
        <div style={{ padding: "18px 16px 14px", borderBottom: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.amber, letterSpacing: "-0.3px" }}>
            ✦ Lumi
          </div>
          <div style={{ fontSize: 10, color: C.textMuted, marginTop: 2 }}>Settings</div>
        </div>

        <nav style={{ padding: "10px 0", flex: 1 }}>
          {SECTIONS.map((s) => {
            const active = activeSection === s.id;
            return (
              <button key={s.id} onClick={() => scrollTo(s.id)} style={{
                display: "flex", alignItems: "center", gap: 9,
                padding: "8px 14px", borderRadius: 8, margin: "2px 8px",
                fontSize: 12.5, fontWeight: active ? 600 : 400,
                color: active ? C.amber : "var(--lm-text-dim)",
                background: active ? C.amberDim : "transparent",
                cursor: "pointer", transition: "all 0.15s",
                border: "none", width: "calc(100% - 16px)", textAlign: "left",
              }}>
                <span style={{ fontSize: 14, lineHeight: 1 }}>{s.icon}</span>
                {s.label}
              </button>
            );
          })}
        </nav>

        <div style={{
          padding: "12px 16px", borderTop: `1px solid ${C.border}`,
        }}>
          <a href="/" style={{
            display: "flex", alignItems: "center", gap: 7,
            color: C.textMuted, textDecoration: "none", fontSize: 12,
            transition: "color 0.15s",
          }}
            onMouseEnter={(e) => (e.currentTarget.style.color = C.textDim)}
            onMouseLeave={(e) => (e.currentTarget.style.color = C.textMuted)}
          >
            ← Monitor
          </a>
        </div>
      </aside>

      {/* ── Main ── */}
      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>

        {/* Topbar */}
        <div style={{
          padding: "10px 24px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0,
        }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>
            {SECTIONS.find((s) => s.id === activeSection)?.label}
          </span>
          <button
            form="edit-form"
            type="submit"
            disabled={saving || loadingCfg}
            style={{
              padding: "6px 18px", borderRadius: 7, fontSize: 12, fontWeight: 600,
              cursor: saving || loadingCfg ? "not-allowed" : "pointer",
              border: "none",
              background: saving || loadingCfg ? C.surface : C.amber,
              color: saving || loadingCfg ? C.textMuted : "#0C0B09",
              transition: "all 0.15s",
              opacity: saving || loadingCfg ? 0.6 : 1,
            }}
          >
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>

        {/* Content */}
        <div ref={contentRef} className="lm-fade-in" style={{
          flex: 1, minHeight: 0, overflowY: "auto", padding: "24px 32px",
        }}>
          <div style={{ maxWidth: 560, margin: "0 auto" }}>

            {error && (
              <div style={{
                background: "rgba(248,113,113,0.08)", border: "1px solid rgba(248,113,113,0.25)",
                borderRadius: 8, padding: "10px 14px", fontSize: 12, color: C.red, marginBottom: 16,
              }}>
                {error}
              </div>
            )}

            <div style={{
              background: C.amberDim, border: "1px solid rgba(245,158,11,0.2)",
              borderRadius: 8, padding: "10px 14px", fontSize: 11.5,
              color: C.textDim, marginBottom: 20, lineHeight: 1.6,
            }}>
              ↻ &nbsp;Restart Lumi after saving for LLM and channel changes to take full effect.
            </div>

            {loadingCfg ? <SkeletonBlock /> : (
              <form id="edit-form" onSubmit={handleSubmit}>

                <SectionCard id="wifi" title="Wi-Fi">
                  <Field label="SSID" id="ssid" value={ssid} onChange={setSsid} placeholder="Network name" />
                  <PasswordField label="Password" id="password" value={password} onChange={setPassword} placeholder="Wi-Fi password" />
                </SectionCard>

                <SectionCard id="device" title="Device">
                  <Field label="Device ID" id="device_id" value={deviceId} onChange={setDeviceId} placeholder="lumi-001" />
                </SectionCard>

                <SectionCard id="llm" title="LLM">
                  <Field label="API Key" id="llm_api_key" value={llmApiKey} onChange={setLlmApiKey} placeholder="sk-..." />
                  <Field label="Base URL" id="llm_url" value={llmUrl} onChange={setLlmUrl} placeholder="https://api.openai.com/v1" />
                  <Field label="Model" id="llm_model" value={llmModel} onChange={setLlmModel} placeholder="gpt-4o-mini" />
                  <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", marginTop: 4 }}>
                    <input
                      type="checkbox" checked={llmDisableThinking}
                      onChange={(e) => setLlmDisableThinking(e.target.checked)}
                      style={{ accentColor: C.amber, width: 14, height: 14, cursor: "pointer" }}
                    />
                    <span style={{ fontSize: 12, color: C.textDim }}>Disable extended thinking (faster responses)</span>
                  </label>
                </SectionCard>

                <SectionCard id="deepgram" title="STT (Deepgram)">
                  <Field label="API Key" id="deepgram_api_key" value={deepgramApiKey} onChange={setDeepgramApiKey} placeholder="dg-..." />
                </SectionCard>

                <SectionCard id="tts" title="TTS Voice">
                  <div style={{ marginBottom: 12 }}>
                    <label htmlFor="tts_voice" style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
                      Voice
                    </label>
                    <select
                      id="tts_voice"
                      value={ttsVoice}
                      onChange={(e) => setTtsVoice(e.target.value)}
                      style={{
                        width: "100%", boxSizing: "border-box",
                        background: C.surface, border: `1px solid ${C.border}`,
                        borderRadius: 7, padding: "8px 11px",
                        fontSize: 12.5, color: C.text, outline: "none", cursor: "pointer",
                      }}
                    >
                      {(ttsVoices.length > 0 ? ttsVoices : ["alloy"]).map((v) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  </div>
                </SectionCard>

                <SectionCard id="channel" title="Messaging Channel">
                  <div style={{ marginBottom: 12 }}>
                    <label style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>Channel</label>
                    <select
                      value={channel}
                      onChange={(e) => setChannel(e.target.value as ChannelType)}
                      style={{
                        width: "100%", boxSizing: "border-box" as const,
                        background: C.surface, border: `1px solid ${C.border}`,
                        borderRadius: 7, padding: "8px 11px",
                        fontSize: 12.5, color: C.text, outline: "none", cursor: "pointer",
                      }}
                    >
                      <option value="telegram">Telegram</option>
                      <option value="slack">Slack</option>
                      <option value="discord">Discord</option>
                    </select>
                  </div>
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
                </SectionCard>

                <SectionCard id="mqtt" title="MQTT (optional)">
                  <Field label="Endpoint" id="mqtt_endpoint" value={mqttEndpoint} onChange={setMqttEndpoint} placeholder="mqtt.example.com" />
                  <Field label="Port" id="mqtt_port" value={mqttPort} onChange={setMqttPort} placeholder="1883" type="number" />
                  <Field label="Username" id="mqtt_username" value={mqttUsername} onChange={setMqttUsername} placeholder="Optional" />
                  <PasswordField label="Password" id="mqtt_password" value={mqttPassword} onChange={setMqttPassword} placeholder="Optional" />
                  <Field label="FA Channel" id="fa_channel" value={faChannel} onChange={setFaChannel} placeholder="Lumi/f_a/device_id" />
                  <Field label="FD Channel" id="fd_channel" value={fdChannel} onChange={setFdChannel} placeholder="Lumi/f_d/device_id" />
                </SectionCard>

              </form>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
