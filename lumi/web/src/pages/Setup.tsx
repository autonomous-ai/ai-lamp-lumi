import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { getNetworks, setupDevice, getTTSVoices, getDeviceConfig } from "@/lib/api";
import { useTheme } from "@/lib/useTheme";
import type { ChannelType, NetworkItem } from "@/types";

// ── CSS vars ──────────────────────────────────────────────────────────────────

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

type SectionId = "wifi" | "device" | "llm" | "deepgram" | "tts" | "channel" | "mqtt" | "face";

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

function SectionCard({ id, title, active, children }: { id: SectionId; title: string; active: boolean; children: React.ReactNode }) {
  if (!active) return null;
  return (
    <div
      id={`section-${id}`}
      style={{
        background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 12, padding: "18px 20px", marginBottom: 16,
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
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: "18px 20px", marginBottom: 16 }}>
      <div style={{ width: 80, height: 8, borderRadius: 6, background: C.surface, marginBottom: 14 }} />
      <div style={{ width: "100%", height: 32, borderRadius: 6, background: C.surface, marginBottom: 10 }} />
    </div>
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function Setup() {
  const [theme, toggleTheme, themeClass] = useTheme();
  const [searchParams] = useSearchParams();

  const channelParam = searchParams.get("channel");
  const channel: ChannelType =
    channelParam === "slack" || channelParam === "discord" ? (channelParam as ChannelType) : "telegram";

  const urlParams = useMemo(
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
      deviceId: searchParams.get("device_id") ?? "",
      mqttEndpoint: searchParams.get("mqtt_endpoint") ?? "",
      mqttPort: searchParams.get("mqtt_port") ?? "",
      mqttUsername: searchParams.get("mqtt_username") ?? "",
      mqttPassword: searchParams.get("mqtt_password") ?? "",
      faChannel: searchParams.get("fa_channel") ?? "",
      fdChannel: searchParams.get("fd_channel") ?? "",
    }),
    [searchParams],
  );

  const hasLlmParams = !!(urlParams.llmApiKey || urlParams.llmUrl);
  const hasChannelParams = !!(
    urlParams.teleToken || urlParams.teleUserId ||
    urlParams.slackBotToken || urlParams.slackAppToken ||
    urlParams.discordBotToken || urlParams.discordGuildId
  );

  const SECTIONS: { id: SectionId; label: string; icon: string }[] = [
    { id: "wifi",     label: "Wi-Fi",    icon: "⬡" },
    { id: "face",     label: "Face",     icon: "◐" },
    ...(!urlParams.deviceId ? [{ id: "device" as SectionId, label: "Device", icon: "◈" }] : []),
    ...(!hasLlmParams       ? [{ id: "llm" as SectionId,    label: "LLM",    icon: "⬢" }] : []),
    ...(!urlParams.deepgramApiKey ? [{ id: "deepgram" as SectionId, label: "STT", icon: "◉" }] : []),
    { id: "tts" as SectionId, label: "TTS", icon: "◎" },
    ...(!hasChannelParams   ? [{ id: "channel" as SectionId, label: channel === "telegram" ? "Telegram" : channel === "slack" ? "Slack" : "Discord", icon: "⬟" }] : []),
    { id: "mqtt",     label: "MQTT",     icon: "☰" },
  ];

  const [networks, setNetworks] = useState<NetworkItem[]>([]);
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [setupWorking, setSetupWorking] = useState(false);
  const [countdown, setCountdown] = useState(5);
  const [activeSection, setActiveSection] = useState<SectionId>("wifi");
  const contentRef = useRef<HTMLDivElement>(null);

  const [deviceId, setDeviceId] = useState(urlParams.deviceId || "");
  const [llmApiKey, setLlmApiKey] = useState(urlParams.llmApiKey || "pro-llm-key-57a4783fc9auto0001");
  const [llmUrl, setLlmUrl] = useState(urlParams.llmUrl || "https://campaign-api.autonomous.ai/api/v1/ai/v1");
  const [llmModel, setLlmModel] = useState(urlParams.llmModel || "claude-haiku-4-5");
  const [llmDisableThinking, setLlmDisableThinking] = useState(false);
  const [deepgramApiKey, setDeepgramApiKey] = useState("");
  const [ttsVoice, setTtsVoice] = useState("alloy");
  const [ttsVoices, setTtsVoices] = useState<string[]>([]);
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

  // Face enroll state
  const [faceName, setFaceName] = useState("");
  const [faceFiles, setFaceFiles] = useState<File[]>([]);
  const [faceUploading, setFaceUploading] = useState(false);
  const [faceMsg, setFaceMsg] = useState<string | null>(null);
  const faceInputRef = useRef<HTMLInputElement>(null);

  const handleFaceEnroll = async () => {
    if (!faceName.trim() || faceFiles.length === 0) return;
    setFaceUploading(true);
    setFaceMsg(null);
    const label = faceName.trim().toLowerCase();
    let ok = 0;
    let lastErr = "";
    for (const file of faceFiles) {
      try {
        const buf = await file.arrayBuffer();
        const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
        const resp = await fetch("/hw/face/enroll", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label, image_base64: b64 }),
        });
        const data = await resp.json();
        if (resp.ok) {
          ok++;
        } else {
          lastErr = data.detail || data.message || `Failed: ${file.name}`;
        }
      } catch (e) {
        lastErr = e instanceof Error ? e.message : String(e);
      }
    }
    if (ok > 0) {
      setFaceMsg(`Enrolled "${label}" — ${ok}/${faceFiles.length} photos`
        + (lastErr ? ` (${lastErr})` : ""));
      setFaceName("");
      setFaceFiles([]);
      if (faceInputRef.current) faceInputRef.current.value = "";
    } else {
      setFaceMsg(`Error: ${lastErr}`);
    }
    setFaceUploading(false);
  };

  useEffect(() => {
    setMqttEndpoint((prev) => prev || urlParams.mqttEndpoint);
    setMqttPort((prev) => prev || urlParams.mqttPort);
    setMqttUsername((prev) => prev || urlParams.mqttUsername);
    setMqttPassword((prev) => prev || urlParams.mqttPassword);
    setFaChannel((prev) => prev || urlParams.faChannel);
    setFdChannel((prev) => prev || urlParams.fdChannel);
  }, [urlParams]);

  useEffect(() => {
    const maxAttempts = 4;
    let attempt = 0;
    function fetchNetworks(): Promise<void> {
      attempt += 1;
      return getNetworks()
        .then((nets) => setNetworks((nets ?? []).filter((n) => n.ssid !== "")))
        .catch(() => { if (attempt < maxAttempts) return fetchNetworks(); setNetworks([]); });
    }
    fetchNetworks().finally(() => setLoadingList(false));
    getTTSVoices().then(setTtsVoices).catch(() => {});
    getDeviceConfig().then((cfg) => {
      if (cfg.tts_voice) setTtsVoice(cfg.tts_voice);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!setupWorking) return;
    const closeAt = Date.now() + 5000;
    const id = setInterval(() => {
      const left = Math.max(0, Math.ceil((closeAt - Date.now()) / 1000));
      setCountdown(left);
      if (left <= 0) window.close();
    }, 500);
    return () => clearInterval(id);
  }, [setupWorking]);


  const scrollTo = (id: SectionId) => {
    setActiveSection(id);
  };

  const uniqueNetworks = useMemo(
    () => [...new Map(networks.filter((n) => n.ssid !== "").map((n) => [n.ssid, n])).values()],
    [networks],
  );

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      let channelCredentials: Record<string, string>;
      switch (channel) {
        case "telegram":
          channelCredentials = {
            telegram_bot_token: urlParams.teleToken || teleToken,
            telegram_user_id: urlParams.teleUserId || teleUserId,
          };
          break;
        case "slack":
          channelCredentials = {
            slack_bot_token: urlParams.slackBotToken || slackBotToken,
            slack_app_token: urlParams.slackAppToken || slackAppToken,
            slack_user_id: urlParams.slackUserId || slackUserId,
          };
          break;
        default:
          channelCredentials = {
            discord_bot_token: urlParams.discordBotToken || discordBotToken,
            discord_guild_id: urlParams.discordGuildId || discordGuildId,
            discord_user_id: urlParams.discordUserId || discordUserId,
          };
      }
      const body: Parameters<typeof setupDevice>[0] = {
        ssid: ssid.trim(), password, channel,
        ...channelCredentials,
        llm_base_url: urlParams.llmUrl || llmUrl,
        llm_api_key: urlParams.llmApiKey || llmApiKey,
        llm_model: urlParams.llmModel || llmModel,
        llm_disable_thinking: llmDisableThinking || undefined,
        deepgram_api_key: urlParams.deepgramApiKey || deepgramApiKey || undefined,
        tts_voice: ttsVoice || undefined,
        device_id: urlParams.deviceId || deviceId,
      };
      const endpoint = mqttEndpoint || urlParams.mqttEndpoint;
      if (endpoint) {
        const port = mqttPort || urlParams.mqttPort;
        Object.assign(body, {
          mqtt_endpoint: endpoint,
          mqtt_port: port ? parseInt(port, 10) : 1883,
          mqtt_username: mqttUsername || urlParams.mqttUsername || undefined,
          mqtt_password: mqttPassword || urlParams.mqttPassword || undefined,
          fa_channel: faChannel || urlParams.faChannel || undefined,
          fd_channel: fdChannel || urlParams.fdChannel || undefined,
        });
      }
      const result = await setupDevice(body);
      setSetupWorking(result);
      setCountdown(5);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Setup failed.");
    }
    setLoading(false);
  }, [
    channel, urlParams, teleToken, teleUserId, slackBotToken, slackAppToken, slackUserId,
    discordBotToken, discordGuildId, discordUserId, ssid, password, llmUrl, llmApiKey,
    llmModel, llmDisableThinking, deepgramApiKey, ttsVoice, deviceId,
    mqttEndpoint, mqttPort, mqttUsername, mqttPassword, faChannel, fdChannel,
  ]);

  return (
    <div className={`lm-root lm-setup ${themeClass}`} style={{
      display: "flex", height: "100vh",
      background: C.bg, color: C.text,
      fontFamily: "'Inter', 'Segoe UI', sans-serif", fontSize: 13,
    }}>
      <style>{`
        @media (max-width: 640px) {
          .lm-setup .lm-sidebar { display: none !important; }
          .lm-setup .lm-mobile-tabs { display: flex !important; }
          .lm-setup .lm-main-content { padding: 16px !important; }
        }
      `}</style>

      {/* ── Sidebar (hidden on mobile) ── */}
      <aside className="lm-sidebar" style={{
        width: 192, flexShrink: 0,
        background: C.sidebar, borderRight: `1px solid ${C.border}`,
        display: "flex", flexDirection: "column",
      }}>
        <div style={{ padding: "18px 16px 14px", borderBottom: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.amber, letterSpacing: "-0.3px" }}>
            ✦ Lumi
          </div>
          <div style={{ fontSize: 10, color: C.textMuted, marginTop: 2 }}>Setup</div>
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

        <div style={{ padding: "12px 16px", borderTop: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
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
          <button onClick={toggleTheme} style={{
            background: "none", border: "none", cursor: "pointer",
            fontSize: 14, color: C.textMuted, padding: "2px 4px",
          }} title={`Theme: ${theme}`}>
            {theme === "dark" ? "◑" : "◐"}
          </button>
        </div>
      </aside>

      {/* ── Main ── */}
      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>

        {/* Mobile tabs (hidden on desktop) */}
        <div className="lm-mobile-tabs" style={{
          display: "none", overflowX: "auto", gap: 4, padding: "8px 12px",
          borderBottom: `1px solid ${C.border}`, flexShrink: 0, alignItems: "center",
        }}>
          {SECTIONS.map((s) => {
            const active = activeSection === s.id;
            return (
              <button key={s.id} onClick={() => scrollTo(s.id)} style={{
                padding: "5px 10px", borderRadius: 6, fontSize: 11, fontWeight: active ? 600 : 400,
                color: active ? C.amber : C.textDim,
                background: active ? C.amberDim : "transparent",
                border: "none", cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0,
              }}>
                {s.label}
              </button>
            );
          })}
          <button onClick={toggleTheme} style={{
            background: "none", border: "none", cursor: "pointer",
            fontSize: 14, color: C.textMuted, padding: "2px 6px", marginLeft: "auto", flexShrink: 0,
          }}>
            {theme === "dark" ? "◑" : "◐"}
          </button>
        </div>

        {/* Topbar */}
        <div style={{
          padding: "10px 24px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0,
        }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>
            {setupWorking ? "Setting up…" : SECTIONS.find((s) => s.id === activeSection)?.label ?? "Wi-Fi"}
          </span>
          {!setupWorking && (
            <button
              form="setup-form"
              type="submit"
              disabled={loading || loadingList}
              style={{
                padding: "6px 18px", borderRadius: 7, fontSize: 12, fontWeight: 600,
                cursor: loading || loadingList ? "not-allowed" : "pointer",
                border: "none",
                background: loading || loadingList ? C.surface : C.amber,
                color: loading || loadingList ? C.textMuted : "#0C0B09",
                transition: "all 0.15s",
                opacity: loading || loadingList ? 0.6 : 1,
              }}
            >
              {loading ? "Setting up…" : "Setup"}
            </button>
          )}
        </div>

        {/* Content */}
        <div ref={contentRef} className="lm-fade-in lm-main-content" style={{
          flex: 1, minHeight: 0, overflowY: "auto", padding: "24px 32px",
        }}>
          <div style={{ maxWidth: 560, margin: "0 auto" }}>

            {/* Success state */}
            {setupWorking ? (
              <div style={{
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 12, padding: "32px 24px", textAlign: "center",
              }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>✦</div>
                <div style={{ fontSize: 15, fontWeight: 600, color: C.amber, marginBottom: 8 }}>
                  Connected!
                </div>
                <div style={{ fontSize: 12, color: C.textDim }}>
                  Window closes in {countdown}s…
                </div>
              </div>
            ) : (
              <>
                {error && (
                  <div style={{
                    background: "rgba(248,113,113,0.08)", border: "1px solid rgba(248,113,113,0.25)",
                    borderRadius: 8, padding: "10px 14px", fontSize: 12, color: C.red, marginBottom: 16,
                  }}>
                    {error}
                  </div>
                )}

                <form id="setup-form" onSubmit={handleSubmit}>

                  {/* Wi-Fi */}
                  <SectionCard id="wifi" title="Wi-Fi" active={activeSection === "wifi"}>
                    <div style={{ marginBottom: 12 }}>
                      <label htmlFor="ssid" style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
                        SSID
                      </label>
                      {loadingList ? (
                        <SkeletonBlock />
                      ) : uniqueNetworks.length > 0 ? (
                        <select
                          id="ssid"
                          value={ssid}
                          onChange={(e) => setSsid(e.target.value)}
                          style={{
                            width: "100%", boxSizing: "border-box",
                            background: C.surface, border: `1px solid ${C.border}`,
                            borderRadius: 7, padding: "8px 11px",
                            fontSize: 12.5, color: C.text, outline: "none", cursor: "pointer",
                          }}
                        >
                          <option value="">Select network</option>
                          {uniqueNetworks.map((n) => (
                            <option key={n.bssid} value={n.ssid}>{n.ssid}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          id="ssid" type="text" value={ssid}
                          onChange={(e) => setSsid(e.target.value)}
                          placeholder="Enter SSID" autoComplete="off"
                          style={{
                            width: "100%", boxSizing: "border-box",
                            background: C.surface, border: `1px solid ${C.border}`,
                            borderRadius: 7, padding: "8px 11px",
                            fontSize: 12.5, color: C.text, outline: "none",
                          }}
                        />
                      )}
                    </div>
                    <PasswordField label="Password" id="password" value={password} onChange={setPassword} placeholder="Wi-Fi password" />
                  </SectionCard>

                  {/* Face Enroll */}
                  <SectionCard id="face" title="Face Enroll (optional)" active={activeSection === "face"}>
                    <div style={{ fontSize: 11, color: C.textDim, marginBottom: 12 }}>
                      Upload photos of the owner so the lamp can recognize them.
                    </div>
                    <Field label="Name" id="face_name" value={faceName} onChange={setFaceName} placeholder="e.g. Leo" />
                    <div style={{ marginBottom: 12 }}>
                      <label style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>Photos ({faceFiles.length} selected)</label>
                      <input
                        ref={faceInputRef}
                        type="file"
                        accept="image/*"
                        multiple
                        onChange={(e) => setFaceFiles(e.target.files ? Array.from(e.target.files) : [])}
                        style={{ fontSize: 12, color: C.text, width: "100%", boxSizing: "border-box" }}
                      />
                    </div>
                    {faceMsg && (
                      <div style={{
                        fontSize: 11, padding: "6px 10px", borderRadius: 6, marginBottom: 10,
                        background: faceMsg.startsWith("Error") || faceMsg.includes("failed")
                          ? "rgba(248,113,113,0.08)" : "rgba(52,211,153,0.08)",
                        color: faceMsg.startsWith("Error") || faceMsg.includes("failed")
                          ? C.red : "rgb(52,211,153)",
                      }}>{faceMsg}</div>
                    )}
                    <button
                      type="button"
                      onClick={handleFaceEnroll}
                      disabled={!faceName.trim() || faceFiles.length === 0 || faceUploading}
                      style={{
                        width: "100%", padding: "9px 0", borderRadius: 7, fontSize: 12.5,
                        fontWeight: 600, cursor: faceUploading ? "wait" : "pointer",
                        background: !faceName.trim() || faceFiles.length === 0 ? C.surface : "rgba(52,211,153,0.12)",
                        border: `1px solid ${!faceName.trim() || faceFiles.length === 0 ? C.border : "rgba(52,211,153,0.35)"}`,
                        color: !faceName.trim() || faceFiles.length === 0 ? C.textMuted : "rgb(52,211,153)",
                      }}
                    >
                      {faceUploading ? "Uploading…" : "Enroll Face"}
                    </button>
                  </SectionCard>

                  {/* Device */}
                  {!urlParams.deviceId && (
                    <SectionCard id="device" title="Device" active={activeSection === "device"}>
                      <Field label="Device ID" id="device_id" value={deviceId} onChange={setDeviceId} placeholder="lumi-001" />
                    </SectionCard>
                  )}

                  {/* LLM */}
                  {!hasLlmParams && (
                    <SectionCard id="llm" title="LLM" active={activeSection === "llm"}>
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
                  )}

                  {/* STT (Deepgram) */}
                  {!urlParams.deepgramApiKey && (
                    <SectionCard id="deepgram" title="STT (Deepgram)" active={activeSection === "deepgram"}>
                      <Field label="API Key" id="deepgram_api_key" value={deepgramApiKey} onChange={setDeepgramApiKey} placeholder="dg-..." />
                    </SectionCard>
                  )}

                  {/* TTS */}
                  <SectionCard id="tts" title="TTS Voice" active={activeSection === "tts"}>
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

                  {/* Channel */}
                  {!hasChannelParams && (
                    <SectionCard id="channel" title={channel === "telegram" ? "Telegram" : channel === "slack" ? "Slack" : "Discord"} active={activeSection === "channel"}>
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
                  )}

                  {/* MQTT */}
                  <SectionCard id="mqtt" title="MQTT (optional)" active={activeSection === "mqtt"}>
                    <Field label="Endpoint" id="mqtt_endpoint" value={mqttEndpoint} onChange={setMqttEndpoint} placeholder="mqtt.example.com" />
                    <Field label="Port" id="mqtt_port" value={mqttPort} onChange={setMqttPort} placeholder="1883" type="number" />
                    <Field label="Username" id="mqtt_username" value={mqttUsername} onChange={setMqttUsername} placeholder="Optional" />
                    <PasswordField label="Password" id="mqtt_password" value={mqttPassword} onChange={setMqttPassword} placeholder="Optional" />
                    <Field label="FA Channel" id="fa_channel" value={faChannel} onChange={setFaChannel} placeholder="Lumi/f_a/device_id" />
                    <Field label="FD Channel" id="fd_channel" value={fdChannel} onChange={setFdChannel} placeholder="Lumi/f_d/device_id" />
                  </SectionCard>

                </form>
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
