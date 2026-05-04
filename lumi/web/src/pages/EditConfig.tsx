import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import { getDeviceConfig, updateDeviceConfig, getTTSVoices, getTTSProviders, testTTSVoice } from "@/lib/api";
import type { DeviceConfig } from "@/lib/api";
import { useTheme } from "@/lib/useTheme";
import type { ChannelType } from "@/types";
import { Wifi, UserCircle, Lamp, Brain, Volume2, Mic, MessageSquare, Link, Pencil, X, Eye, EyeOff } from "lucide-react";

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

type SectionId = "device" | "wifi" | "llm" | "face" | "tts" | "stt" | "channel" | "mqtt";
const ICON_SIZE = 15;
const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: "device",   label: "Device",   icon: <Lamp size={ICON_SIZE} /> },
  { id: "wifi",     label: "Wi-Fi",    icon: <Wifi size={ICON_SIZE} /> },
  { id: "llm",      label: "AI Brain", icon: <Brain size={ICON_SIZE} /> },
  { id: "face",     label: "Face",     icon: <UserCircle size={ICON_SIZE} /> },
  { id: "tts",      label: "TTS",      icon: <Volume2 size={ICON_SIZE} /> },
  { id: "stt",      label: "STT",      icon: <Mic size={ICON_SIZE} /> },
  { id: "channel",  label: "Channels", icon: <MessageSquare size={ICON_SIZE} /> },
  { id: "mqtt",     label: "MQTT",     icon: <Link size={ICON_SIZE} /> },
];

// ── small components ──────────────────────────────────────────────────────────

function Field({
  label, id, value, onChange, placeholder, type = "text", readOnly = false,
}: {
  label: string; id: string; value: string;
  onChange: (v: string) => void; placeholder?: string; type?: string; readOnly?: boolean;
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
        readOnly={readOnly}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          width: "100%", boxSizing: "border-box",
          background: readOnly ? C.bg : C.surface,
          border: `1px solid ${focused && !readOnly ? C.amber : C.border}`,
          borderRadius: 7, padding: "8px 11px",
          fontSize: 12.5, color: readOnly ? C.textDim : C.text, outline: "none",
          cursor: readOnly ? "default" : "text",
          transition: "border-color 0.15s",
        }}
      />
    </div>
  );
}

function PasswordField({ label, id, value, onChange, placeholder, readOnly = false }: {
  label: string; id: string; value: string;
  onChange: (v: string) => void; placeholder?: string; readOnly?: boolean;
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
          readOnly={readOnly}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          style={{
            width: "100%", boxSizing: "border-box",
            background: readOnly ? C.bg : C.surface,
            border: `1px solid ${focused && !readOnly ? C.amber : C.border}`,
            borderRadius: 7, padding: "8px 38px 8px 11px",
            fontSize: 12.5, color: readOnly ? C.textDim : C.text, outline: "none",
            cursor: readOnly ? "default" : "text",
            transition: "border-color 0.15s",
          }}
        />
        <button type="button" onClick={() => setShow((v) => !v)} tabIndex={-1}
          style={{
            position: "absolute", right: 0, top: 0, height: "100%",
            padding: "0 11px", background: "none", border: "none",
            color: C.textMuted, cursor: "pointer",
            display: "flex", alignItems: "center",
          }}
        >
          {show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
    </div>
  );
}

// useLockToggle — shared lock/unlock + cancel-restore logic for LockedField and
// LockedPasswordField. Captures the value when a field first becomes locked so
// "Cancel" can revert any in-progress edits.
function useLockToggle(lockedInitially: boolean, value: string, onChange: (v: string) => void) {
  const [unlocked, setUnlocked] = useState(false);
  const originalRef = useRef<string | null>(null);
  useEffect(() => {
    if (lockedInitially && originalRef.current === null) {
      originalRef.current = value;
    }
  }, [lockedInitially, value]);
  const readOnly = lockedInitially && !unlocked;
  const handleCancel = () => {
    if (originalRef.current !== null) onChange(originalRef.current);
    setUnlocked(false);
  };
  return { readOnly, showToggle: lockedInitially, unlock: () => setUnlocked(true), handleCancel };
}

// LockedField — Field that starts read-only when initially populated (e.g. loaded
// from saved config) and exposes an "Edit"/cancel button to unlock or revert.
function LockedField({
  lockedInitially, label, id, value, onChange, placeholder, type = "text",
}: {
  lockedInitially: boolean; label: string; id: string; value: string;
  onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  const { readOnly, showToggle, unlock, handleCancel } = useLockToggle(lockedInitially, value, onChange);
  return (
    <div style={{ marginBottom: 12 }}>
      <label htmlFor={id} style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
        {label}
      </label>
      <div style={{ position: "relative" }}>
        <input
          id={id} type={type} value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder} autoComplete="off"
          readOnly={readOnly}
          style={{
            width: "100%", boxSizing: "border-box",
            background: readOnly ? C.bg : C.surface,
            border: `1px solid ${C.border}`,
            borderRadius: 7, padding: showToggle ? "8px 36px 8px 11px" : "8px 11px",
            fontSize: 12.5, color: readOnly ? C.textDim : C.text, outline: "none",
            cursor: readOnly ? "default" : "text",
          }}
        />
        {showToggle && (
          <button
            type="button"
            onClick={readOnly ? unlock : handleCancel}
            tabIndex={-1}
            aria-label={readOnly ? "Edit" : "Cancel edit"}
            title={readOnly ? "Edit" : "Cancel edit"}
            style={{
              position: "absolute", right: 0, top: 0, height: "100%",
              padding: "0 10px", background: "none", border: "none",
              color: readOnly ? C.amber : C.textMuted, cursor: "pointer",
              display: "flex", alignItems: "center",
            }}
          >
            {readOnly ? <Pencil size={13} /> : <X size={14} />}
          </button>
        )}
      </div>
    </div>
  );
}

// LockedPasswordField — same lock semantics as LockedField, plus a show/hide
// toggle while editing. When locked the value stays masked behind dots.
function LockedPasswordField({
  lockedInitially, label, id, value, onChange, placeholder,
}: {
  lockedInitially: boolean; label: string; id: string; value: string;
  onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  const { readOnly, showToggle, unlock, handleCancel } = useLockToggle(lockedInitially, value, onChange);
  // Right side stack: [show/hide][lock toggle]. show/hide is always available so
  // the user can verify a saved password without unlocking it for edit first.
  const rightPad = showToggle ? 64 : 38;
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
          readOnly={readOnly}
          style={{
            width: "100%", boxSizing: "border-box",
            background: readOnly ? C.bg : C.surface,
            border: `1px solid ${C.border}`,
            borderRadius: 7, padding: `8px ${rightPad}px 8px 11px`,
            fontSize: 12.5, color: readOnly ? C.textDim : C.text, outline: "none",
            cursor: readOnly ? "default" : "text",
          }}
        />
        <button
          type="button" onClick={() => setShow((v) => !v)} tabIndex={-1}
          style={{
            position: "absolute", right: showToggle ? 28 : 0, top: 0, height: "100%",
            padding: "0 10px", background: "none", border: "none",
            color: C.textMuted, cursor: "pointer",
            display: "flex", alignItems: "center",
          }}
        >
          {show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
        {showToggle && (
          <button
            type="button"
            onClick={readOnly ? unlock : handleCancel}
            tabIndex={-1}
            aria-label={readOnly ? "Edit" : "Cancel edit"}
            title={readOnly ? "Edit" : "Cancel edit"}
            style={{
              position: "absolute", right: 0, top: 0, height: "100%",
              padding: "0 10px", background: "none", border: "none",
              color: readOnly ? C.amber : C.textMuted, cursor: "pointer",
              display: "flex", alignItems: "center",
            }}
          >
            {readOnly ? <Pencil size={13} /> : <X size={14} />}
          </button>
        )}
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
  const [theme, toggleTheme, themeClass] = useTheme();
  const [loadingCfg, setLoadingCfg] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionId>(() => {
    const hash = window.location.hash.replace("#", "") as SectionId;
    return SECTIONS.some((s) => s.id === hash) ? hash : "device";
  });
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
  const [sttApiKey, setSttApiKey] = useState("");
  const [sttBaseUrl, setSttBaseUrl] = useState("");
  // STT provider: derived from saved config (deepgram if key present, else autonomous).
  // Default for fresh devices is "autonomous" — uses LLM endpoint as fallback.
  const [sttProvider, setSttProvider] = useState<"autonomous" | "deepgram">("autonomous");
  const [ttsApiKey, setTtsApiKey] = useState("");
  const [ttsBaseUrl, setTtsBaseUrl] = useState("");
  const [ttsProvider, setTtsProvider] = useState("openai");
  const [ttsProviders, setTtsProviders] = useState<string[]>([]);
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
  // Snapshot of MQTT fields that were already populated when config loaded.
  // Locks those fields against edits; fields blank at load remain editable.
  const [mqttLoaded, setMqttLoaded] = useState({
    endpoint: false, port: false, username: false,
    password: false, faChannel: false, fdChannel: false,
  });
  // Same idea for messaging-channel credentials. Already-saved values render
  // read-only with an inline "Edit" button to opt-in to changing them.
  const [channelLoaded, setChannelLoaded] = useState({
    teleToken: false, teleUserId: false,
    slackBotToken: false, slackAppToken: false, slackUserId: false,
    discordBotToken: false, discordGuildId: false, discordUserId: false,
  });
  const [wifiLoaded, setWifiLoaded] = useState({ ssid: false, password: false });
  const [llmLoaded, setLlmLoaded] = useState({ apiKey: false, baseUrl: false, model: false });
  const [ttsLoaded, setTtsLoaded] = useState({ apiKey: false, baseUrl: false });
  const [sttLoaded, setSttLoaded] = useState({ deepgram: false, apiKey: false, baseUrl: false });

  // Face enroll state
  const [faceName, setFaceName] = useState("");
  const [faceFiles, setFaceFiles] = useState<File[]>([]);
  const [faceUploading, setFaceUploading] = useState(false);
  const [faceMsg, setFaceMsg] = useState<string | null>(null);
  const faceInputRef = useRef<HTMLInputElement>(null);
  const [faceOwners, setFaceOwners] = useState<{ label: string; photo_count: number; photos: string[] }[]>([]);

  const loadFaceOwners = useCallback(async () => {
    try {
      const r = await fetch("/hw/face/owners").then((x) => x.json());
      if (Array.isArray(r?.persons)) setFaceOwners(r.persons);
    } catch {}
  }, []);

  useEffect(() => { loadFaceOwners(); }, [loadFaceOwners]);

  const removeFaceOwner = async (label: string) => {
    if (!confirm(`Remove "${label}"?`)) return;
    try {
      await fetch("/hw/face/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      });
      loadFaceOwners();
    } catch {}
  };

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
      loadFaceOwners();
    } else {
      setFaceMsg(`Error: ${lastErr}`);
    }
    setFaceUploading(false);
  };

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
        setSttApiKey(cfg.stt_api_key ?? "");
        setSttBaseUrl(cfg.stt_base_url ?? "");
        setSttProvider(cfg.deepgram_api_key ? "deepgram" : "autonomous");
        setTtsApiKey(cfg.tts_api_key ?? "");
        setTtsBaseUrl(cfg.tts_base_url ?? "");
        setTtsProvider(cfg.tts_provider || "openai");
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
        setMqttLoaded({
          endpoint: !!cfg.mqtt_endpoint,
          port: !!cfg.mqtt_port,
          username: !!cfg.mqtt_username,
          password: !!cfg.mqtt_password,
          faChannel: !!cfg.fa_channel,
          fdChannel: !!cfg.fd_channel,
        });
        setChannelLoaded({
          teleToken: !!cfg.telegram_bot_token,
          teleUserId: !!cfg.telegram_user_id,
          slackBotToken: !!cfg.slack_bot_token,
          slackAppToken: !!cfg.slack_app_token,
          slackUserId: !!cfg.slack_user_id,
          discordBotToken: !!cfg.discord_bot_token,
          discordGuildId: !!cfg.discord_guild_id,
          discordUserId: !!cfg.discord_user_id,
        });
        setWifiLoaded({
          ssid: !!cfg.network_ssid,
          password: !!cfg.network_password,
        });
        setLlmLoaded({
          apiKey: !!cfg.llm_api_key,
          baseUrl: !!cfg.llm_base_url,
          model: !!cfg.llm_model,
        });
        setTtsLoaded({
          apiKey: !!cfg.tts_api_key,
          baseUrl: !!cfg.tts_base_url,
        });
        setSttLoaded({
          deepgram: !!cfg.deepgram_api_key,
          apiKey: !!cfg.stt_api_key,
          baseUrl: !!cfg.stt_base_url,
        });
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingCfg(false));
    getTTSProviders().then(setTtsProviders).catch(() => {});
    getTTSVoices().then(setTtsVoices).catch(() => {});
  }, []);

  // Refetch voices when provider changes — only reset voice if current voice is not in new list
  const providerChangedByUser = useRef(false);
  useEffect(() => {
    getTTSVoices(ttsProvider).then((voices) => {
      setTtsVoices(voices);
      if (providerChangedByUser.current && voices.length > 0 && !voices.includes(ttsVoice)) {
        setTtsVoice(voices[0]);
      }
      providerChangedByUser.current = true;
    }).catch(() => {});
  }, [ttsProvider]);

  // Auto-mirror AI Brain key/URL into TTS while TTS field is empty.
  // Once the user types into TTS the sync stops; clearing it re-enables mirroring.
  useEffect(() => {
    if (!ttsApiKey && llmApiKey) setTtsApiKey(llmApiKey);
  }, [llmApiKey, ttsApiKey]);
  useEffect(() => {
    if (!ttsBaseUrl && llmUrl) setTtsBaseUrl(llmUrl);
  }, [llmUrl, ttsBaseUrl]);
  // Same auto-mirror for STT in autonomous mode (Deepgram has its own key).
  useEffect(() => {
    if (sttProvider === "autonomous" && !sttApiKey && llmApiKey) setSttApiKey(llmApiKey);
  }, [llmApiKey, sttApiKey, sttProvider]);
  useEffect(() => {
    if (sttProvider === "autonomous" && !sttBaseUrl && llmUrl) setSttBaseUrl(llmUrl);
  }, [llmUrl, sttBaseUrl, sttProvider]);

  const scrollTo = (id: SectionId) => {
    setActiveSection(id);
    window.location.hash = id;
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
      // STT provider is implicit on backend: deepgram if deepgram_api_key set,
      // else autonomous via stt_api_key/stt_base_url. So when picking
      // autonomous we send deepgram_api_key="" to clear it (backend now allows
      // blank-clears for STT/Deepgram), and vice versa.
      const sttFields = sttProvider === "deepgram"
        ? { deepgram_api_key: deepgramApiKey, stt_api_key: "", stt_base_url: "" }
        : { deepgram_api_key: "", stt_api_key: sttApiKey, stt_base_url: sttBaseUrl };
      await updateDeviceConfig({
        ssid: ssid.trim(), password,
        channel, ...channelCreds,
        llm_base_url: llmUrl, llm_api_key: llmApiKey, llm_model: llmModel,
        llm_disable_thinking: llmDisableThinking,
        ...sttFields,
        tts_api_key: ttsApiKey, tts_base_url: ttsBaseUrl, tts_provider: ttsProvider, tts_voice: ttsVoice, device_id: deviceId,
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
    llmApiKey, llmModel, llmDisableThinking, deepgramApiKey, sttApiKey, sttBaseUrl, sttProvider,
    ttsApiKey, ttsBaseUrl, ttsProvider, ttsVoice, deviceId,
    mqttEndpoint, mqttUsername, mqttPassword, mqttPort, faChannel, fdChannel,
  ]);

  return (
    <div className={`lm-root lm-edit ${themeClass}`} style={{
      display: "flex", height: "100vh",
      background: C.bg, color: C.text,
      fontFamily: "'Inter', 'Segoe UI', sans-serif", fontSize: 14,
    }}>
      <style>{`
        @media (max-width: 640px) {
          .lm-edit .lm-sidebar { display: none !important; }
          .lm-edit .lm-mobile-tabs { display: flex !important; }
          .lm-edit .lm-main-content { padding: 16px !important; }
        }
      `}</style>

      {/* ── Sidebar (hidden on mobile) ── */}
      <aside className="lm-sidebar" style={{
        width: 192, flexShrink: 0,
        background: C.sidebar, borderRight: `1px solid ${C.border}`,
        display: "flex", flexDirection: "column",
      }}>

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
                {s.icon}
                {s.label}
              </button>
            );
          })}
        </nav>

        <div style={{ padding: "12px 16px", borderTop: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <a href="/monitor" style={{
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
            {SECTIONS.find((s) => s.id === activeSection)?.label}
          </span>
          {activeSection !== "face" && (
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
          )}
        </div>

        {/* Content */}
        <div ref={contentRef} className="lm-fade-in lm-main-content" style={{
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
              ↻ &nbsp;Restart Lumi after saving for AI brain and channel changes to take full effect.
            </div>

            {loadingCfg ? <SkeletonBlock /> : (
              <form id="edit-form" onSubmit={handleSubmit}>

                <SectionCard id="device" title="Device" active={activeSection === "device"}>
                  <Field label="Device ID" id="device_id" value={deviceId} onChange={setDeviceId} placeholder="lumi-001" readOnly />
                </SectionCard>

                <SectionCard id="wifi" title="Wi-Fi" active={activeSection === "wifi"}>
                  <LockedField lockedInitially={wifiLoaded.ssid} label="Wi-Fi network" id="ssid" value={ssid} onChange={setSsid} placeholder="Network name" />
                  <LockedPasswordField lockedInitially={wifiLoaded.password} label="Password" id="password" value={password} onChange={setPassword} placeholder="Wi-Fi password" />
                </SectionCard>

                <SectionCard id="llm" title="AI Brain" active={activeSection === "llm"}>
                  <LockedPasswordField lockedInitially={llmLoaded.apiKey} label="API Key" id="llm_api_key" value={llmApiKey} onChange={setLlmApiKey} placeholder="sk-..." />
                  <LockedField lockedInitially={llmLoaded.baseUrl} label="Base URL" id="llm_url" value={llmUrl} onChange={setLlmUrl} placeholder="https://api.openai.com/v1" />
                  <LockedField lockedInitially={llmLoaded.model} label="Model" id="llm_model" value={llmModel} onChange={setLlmModel} placeholder="gpt-4o-mini" />
                  <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", marginTop: 4 }}>
                    <input
                      type="checkbox" checked={llmDisableThinking}
                      onChange={(e) => setLlmDisableThinking(e.target.checked)}
                      style={{ accentColor: C.amber, width: 14, height: 14, cursor: "pointer" }}
                    />
                    <span style={{ fontSize: 12, color: C.textDim }}>Disable extended thinking (faster responses)</span>
                  </label>
                </SectionCard>

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
                  {faceOwners.length > 0 && (
                    <div style={{ marginTop: 16, borderTop: `1px solid ${C.border}`, paddingTop: 14 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: C.textDim, textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 10 }}>
                        Enrolled ({faceOwners.length})
                      </div>
                      {faceOwners.filter((p) => p.photo_count > 0).map((p) => (
                        <div key={p.label} style={{
                          padding: "10px 0", borderBottom: `1px solid ${C.border}`,
                        }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: p.photos.length > 1 ? 8 : 0 }}>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{p.label}</div>
                              <div style={{ fontSize: 10, color: C.textMuted }}>{p.photo_count} photo{p.photo_count !== 1 ? "s" : ""}</div>
                            </div>
                            {p.label !== "unknown" && (
                              <button
                                type="button"
                                onClick={() => removeFaceOwner(p.label)}
                                style={{
                                  background: "none", border: "none", cursor: "pointer",
                                  fontSize: 11, color: C.red, padding: "4px 8px",
                                }}
                              >
                                Remove
                              </button>
                            )}
                          </div>
                          {p.photos.length > 0 && (
                            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                              {p.photos.map((photo) => (
                                <img
                                  key={photo}
                                  src={`/hw/face/photo/${p.label}/${photo}`}
                                  onClick={() => window.open(`/hw/face/photo/${p.label}/${photo}`, "_blank")}
                                  style={{
                                    width: 48, height: 48, borderRadius: 8, objectFit: "cover",
                                    border: `1px solid ${C.border}`, cursor: "pointer",
                                  }}
                                />
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </SectionCard>

                <SectionCard id="tts" title="TTS Voice" active={activeSection === "tts"}>
                  <LockedPasswordField lockedInitially={ttsLoaded.apiKey || llmLoaded.apiKey} label="API Key (optional — leave blank to reuse AI brain key)" id="tts_api_key" value={ttsApiKey} onChange={setTtsApiKey} placeholder="sk-..." />
                  <LockedField lockedInitially={ttsLoaded.baseUrl || llmLoaded.baseUrl} label="Base URL (optional — leave blank to reuse AI brain base URL)" id="tts_base_url" value={ttsBaseUrl} onChange={setTtsBaseUrl} placeholder="https://api.openai.com/v1" />
                  <div style={{ marginBottom: 12 }}>
                    <label htmlFor="tts_provider" style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
                      Provider
                    </label>
                    <select
                      id="tts_provider"
                      value={ttsProvider}
                      onChange={(e) => setTtsProvider(e.target.value)}
                      style={{
                        width: "100%", boxSizing: "border-box",
                        background: C.surface, border: `1px solid ${C.border}`,
                        borderRadius: 7, padding: "8px 11px",
                        fontSize: 12.5, color: C.text, outline: "none", cursor: "pointer",
                      }}
                    >
                      {(ttsProviders.length > 0 ? ttsProviders : ["openai"]).map((p) => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                  </div>
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
                    <button
                      type="button"
                      onClick={() => testTTSVoice(ttsVoice, {
                        provider: ttsProvider,
                        ttsApiKey, ttsBaseUrl,
                        llmApiKey, llmBaseUrl: llmUrl,
                      })}
                      style={{
                        marginTop: 8, width: "100%", padding: "8px 0",
                        background: C.amber, color: "#fff", border: "none",
                        borderRadius: 7, fontSize: 12, cursor: "pointer", fontWeight: 600,
                      }}
                    >
                      Test Voice
                    </button>
                  </div>
                </SectionCard>

                <SectionCard id="stt" title="STT (Speech-to-Text)" active={activeSection === "stt"}>
                  <div style={{ marginBottom: 12 }}>
                    <label htmlFor="stt_provider" style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
                      Provider
                    </label>
                    <select
                      id="stt_provider"
                      value={sttProvider}
                      onChange={(e) => setSttProvider(e.target.value as "autonomous" | "deepgram")}
                      style={{
                        width: "100%", boxSizing: "border-box",
                        background: C.surface, border: `1px solid ${C.border}`,
                        borderRadius: 7, padding: "8px 11px",
                        fontSize: 12.5, color: C.text, outline: "none", cursor: "pointer",
                      }}
                    >
                      <option value="autonomous">Autonomous (reuse AI brain)</option>
                      <option value="deepgram">Deepgram</option>
                    </select>
                  </div>
                  {sttProvider === "deepgram" ? (
                    <LockedPasswordField lockedInitially={sttLoaded.deepgram} label="Deepgram API Key" id="deepgram_api_key" value={deepgramApiKey} onChange={setDeepgramApiKey} placeholder="Deepgram key" />
                  ) : (
                    <>
                      <LockedPasswordField lockedInitially={sttLoaded.apiKey || llmLoaded.apiKey} label="API Key (optional — leave blank to reuse AI brain key)" id="stt_api_key" value={sttApiKey} onChange={setSttApiKey} placeholder="sk-..." />
                      <LockedField lockedInitially={sttLoaded.baseUrl || llmLoaded.baseUrl} label="Base URL (optional — leave blank to reuse AI brain base URL)" id="stt_base_url" value={sttBaseUrl} onChange={setSttBaseUrl} placeholder="https://api.openai.com/v1" />
                    </>
                  )}
                </SectionCard>

                <SectionCard id="channel" title="Messaging Channels" active={activeSection === "channel"}>
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
                      <LockedField lockedInitially={channelLoaded.teleToken} label="Bot Token" id="tele_token" value={teleToken} onChange={setTeleToken} placeholder="123456:ABC-DEF..." />
                      <LockedField lockedInitially={channelLoaded.teleUserId} label="User ID" id="tele_user_id" value={teleUserId} onChange={setTeleUserId} placeholder="123456789" />
                    </>
                  )}
                  {channel === "slack" && (
                    <>
                      <LockedField lockedInitially={channelLoaded.slackBotToken} label="Bot Token" id="slack_bot_token" value={slackBotToken} onChange={setSlackBotToken} placeholder="xoxb-..." />
                      <LockedField lockedInitially={channelLoaded.slackAppToken} label="App Token" id="slack_app_token" value={slackAppToken} onChange={setSlackAppToken} placeholder="xapp-..." />
                      <LockedField lockedInitially={channelLoaded.slackUserId} label="User ID" id="slack_user_id" value={slackUserId} onChange={setSlackUserId} placeholder="U0123456789" />
                    </>
                  )}
                  {channel === "discord" && (
                    <>
                      <LockedField lockedInitially={channelLoaded.discordBotToken} label="Bot Token" id="discord_bot_token" value={discordBotToken} onChange={setDiscordBotToken} placeholder="Bot token" />
                      <LockedField lockedInitially={channelLoaded.discordGuildId} label="Guild ID" id="discord_guild_id" value={discordGuildId} onChange={setDiscordGuildId} placeholder="123456789" />
                      <LockedField lockedInitially={channelLoaded.discordUserId} label="User ID" id="discord_user_id" value={discordUserId} onChange={setDiscordUserId} placeholder="123456789" />
                    </>
                  )}
                </SectionCard>

                <SectionCard id="mqtt" title="MQTT (optional)" active={activeSection === "mqtt"}>
                  <LockedField lockedInitially={mqttLoaded.endpoint} label="Endpoint" id="mqtt_endpoint" value={mqttEndpoint} onChange={setMqttEndpoint} placeholder="mqtt.example.com" />
                  <LockedField lockedInitially={mqttLoaded.port} label="Port" id="mqtt_port" value={mqttPort} onChange={setMqttPort} placeholder="1883" type="number" />
                  <LockedField lockedInitially={mqttLoaded.username} label="Username" id="mqtt_username" value={mqttUsername} onChange={setMqttUsername} placeholder="Optional" />
                  <LockedPasswordField lockedInitially={mqttLoaded.password} label="Password" id="mqtt_password" value={mqttPassword} onChange={setMqttPassword} placeholder="Optional" />
                  <LockedField lockedInitially={mqttLoaded.faChannel} label="FA Channel" id="fa_channel" value={faChannel} onChange={setFaChannel} placeholder="Lumi/f_a/device_id" />
                  <LockedField lockedInitially={mqttLoaded.fdChannel} label="FD Channel" id="fd_channel" value={fdChannel} onChange={setFdChannel} placeholder="Lumi/f_d/device_id" />
                </SectionCard>

              </form>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
