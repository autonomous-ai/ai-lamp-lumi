import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { getNetworks, setupDevice, getTTSVoices, getTTSProviders, getDeviceConfig, testTTSVoice } from "@/lib/api";
import { useTheme } from "@/lib/useTheme";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import type { ChannelType, NetworkItem } from "@/types";
import { Wifi, Lamp, Brain, Volume2, MessageSquare, UserCircle, Mic, Pencil, X, Eye, EyeOff } from "lucide-react";

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

type SectionId = "wifi" | "device" | "llm" | "deepgram" | "tts" | "channel" | "mqtt" | "voice" | "face";

// ── small components ──────────────────────────────────────────────────────────

function Field({
  label, id, value, onChange, placeholder, type = "text", readOnly = false, required = false,
}: {
  label: string; id: string; value: string;
  onChange: (v: string) => void; placeholder?: string; type?: string; readOnly?: boolean; required?: boolean;
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
        readOnly={readOnly} required={required}
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

function LockedField({
  lockedInitially, label, id, value, onChange, placeholder, type = "text", required = false,
}: {
  lockedInitially: boolean; label: string; id: string; value: string;
  onChange: (v: string) => void; placeholder?: string; type?: string; required?: boolean;
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
          readOnly={readOnly} required={required}
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

function LockedPasswordField({
  lockedInitially, label, id, value, onChange, placeholder, required = false,
}: {
  lockedInitially: boolean; label: string; id: string; value: string;
  onChange: (v: string) => void; placeholder?: string; required?: boolean;
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
          readOnly={readOnly} required={required}
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
  useDocumentTitle("Setup");

  const channelParam = searchParams.get("channel");
  const initialChannel: ChannelType =
    channelParam === "slack" || channelParam === "discord" ? (channelParam as ChannelType) : "telegram";
  const [channel, setChannel] = useState<ChannelType>(initialChannel);

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
      ttsApiKey: searchParams.get("tts_api_key") ?? "",
      ttsBaseUrl: searchParams.get("tts_base_url") ?? "",
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

  // Fixed order. STT (Deepgram) / MQTT are intentionally hidden — their
  // state is still wired up and submitted with empty or URL-prefilled
  // defaults, so re-adding a SectionCard + a SECTIONS entry brings them
  // back without other plumbing.
  const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
    { id: "device", label: "Device", icon: <Lamp size={15} /> },
    { id: "wifi",   label: "Wi-Fi",  icon: <Wifi size={15} /> },
    { id: "llm",    label: "AI Brain", icon: <Brain size={15} /> },
    { id: "voice",  label: "Voice",  icon: <Mic size={15} /> },
    { id: "face",   label: "Face",   icon: <UserCircle size={15} /> },
    { id: "channel", label: "Channels", icon: <MessageSquare size={15} /> },
    { id: "tts",    label: "TTS",    icon: <Volume2 size={15} /> },
  ];

  const [networks, setNetworks] = useState<NetworkItem[]>([]);
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [setupWorking, setSetupWorking] = useState(false);
  const [countdown, setCountdown] = useState(5);
  const [activeSection, setActiveSection] = useState<SectionId>("device");
  const contentRef = useRef<HTMLDivElement>(null);

  const [deviceId, setDeviceId] = useState(urlParams.deviceId || "");
  const [llmApiKey, setLlmApiKey] = useState(urlParams.llmApiKey || "");
  const [llmUrl, setLlmUrl] = useState(urlParams.llmUrl || "");
  const [llmModel, setLlmModel] = useState(urlParams.llmModel || "");
  // Snapshot of AI Brain fields populated when entering setup (URL or saved
  // config). Populated values render with the Edit pencil so re-running setup
  // doesn't accidentally overwrite credentials.
  const [llmLoaded, setLlmLoaded] = useState({
    apiKey: !!urlParams.llmApiKey,
    baseUrl: !!urlParams.llmUrl,
    model: !!urlParams.llmModel,
  });
  const [llmDisableThinking, setLlmDisableThinking] = useState(false);
  // deepgram input is hidden in this build; submit reads urlParams.deepgramApiKey directly
  const [ttsApiKey, setTtsApiKey] = useState(urlParams.ttsApiKey || "");
  const [ttsBaseUrl, setTtsBaseUrl] = useState(urlParams.ttsBaseUrl || "");
  // STT credentials are not exposed in Setup UI but still saved to config so
  // the device's voice pipeline has fallback values mirroring the LLM endpoint.
  const [sttApiKey, setSttApiKey] = useState("");
  const [sttBaseUrl, setSttBaseUrl] = useState("");
  const [ttsProvider, setTtsProvider] = useState("openai");
  const [ttsProviders, setTtsProviders] = useState<string[]>([]);
  const [ttsVoice, setTtsVoice] = useState("alloy");
  const [ttsVoices, setTtsVoices] = useState<string[]>([]);
  const [teleToken, setTeleToken] = useState(urlParams.teleToken || "");
  const [teleUserId, setTeleUserId] = useState(urlParams.teleUserId || "");
  const [slackBotToken, setSlackBotToken] = useState(urlParams.slackBotToken || "");
  const [slackAppToken, setSlackAppToken] = useState(urlParams.slackAppToken || "");
  const [slackUserId, setSlackUserId] = useState(urlParams.slackUserId || "");
  const [discordBotToken, setDiscordBotToken] = useState(urlParams.discordBotToken || "");
  const [discordGuildId, setDiscordGuildId] = useState(urlParams.discordGuildId || "");
  const [discordUserId, setDiscordUserId] = useState(urlParams.discordUserId || "");
  // Snapshot of channel credentials populated when entering Setup. Filled
  // values render with the Edit pencil to prevent accidental overwrites.
  const [channelLoaded, setChannelLoaded] = useState({
    teleToken: !!urlParams.teleToken, teleUserId: !!urlParams.teleUserId,
    slackBotToken: !!urlParams.slackBotToken, slackAppToken: !!urlParams.slackAppToken,
    slackUserId: !!urlParams.slackUserId,
    discordBotToken: !!urlParams.discordBotToken, discordGuildId: !!urlParams.discordGuildId,
    discordUserId: !!urlParams.discordUserId,
  });
  const [mqttEndpoint, setMqttEndpoint] = useState("");
  const [mqttPort, setMqttPort] = useState("");
  const [mqttUsername, setMqttUsername] = useState("");
  const [mqttPassword, setMqttPassword] = useState("");
  const [faChannel, setFaChannel] = useState("");
  const [fdChannel, setFdChannel] = useState("");

  // Face enroll — same flow as EditConfig.Face. Uses /hw/face endpoints
  // directly so user can enroll without finishing the rest of setup.
  const [faceName, setFaceName] = useState("");
  const [faceFiles, setFaceFiles] = useState<File[]>([]);
  const [faceUploading, setFaceUploading] = useState(false);
  const [faceMsg, setFaceMsg] = useState<string | null>(null);
  const faceInputRef = useRef<HTMLInputElement>(null);
  const [faceOwners, setFaceOwners] = useState<{ label: string; photo_count: number; photos: string[]; voice_samples?: string[] }[]>([]);

  const loadFaceOwners = useCallback(async () => {
    try {
      const r = await fetch("/hw/face/owners").then((x) => x.json());
      if (Array.isArray(r?.persons)) setFaceOwners(r.persons);
    } catch { /* hardware may not be reachable during setup; silent */ }
  }, []);

  useEffect(() => { loadFaceOwners(); }, [loadFaceOwners]);

  const removeFaceOwner = async (label: string) => {
    if (!confirm(`Remove enrolled face "${label}"?`)) return;
    try {
      await fetch("/hw/face/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      });
      loadFaceOwners();
    } catch { /* ignore */ }
  };

  // Voice enroll — browser records 3 sentences via MediaRecorder, posts the
  // webm blob to Lumi /api/voice/enroll which converts to WAV and forwards
  // to lelamp /speaker/enroll. Uses same `label` as face so both biometrics
  // land in the same per-user folder (speaker_recognizer convention).
  const VOICE_PHRASES = [
    "Hi Lumi, I'm enrolling my voice so you can recognize me when we talk.",
    "The quick brown fox jumps over the lazy dog near the bright morning window.",
    "Today is a great day to start something new, and I'm looking forward to it.",
  ];
  // Voice enroll uses the LAMP'S OWN MIC, not the browser. Web is just a
  // remote trigger: countdown → POST /api/voice/enroll → Lumi tells lelamp
  // to release ALSA, runs arecord locally, re-enrolls. No HTTPS needed (we
  // never call getUserMedia), no permission prompt, and the embedding sees
  // the same mic as runtime so recognition matches.
  const VOICE_DURATION_SEC = 15;
  const [voiceLabel, setVoiceLabel] = useState("");
  const [voicePhase, setVoicePhase] = useState<"idle" | "countdown" | "recording" | "processing">("idle");
  const [voiceCountdown, setVoiceCountdown] = useState(0);
  const [voiceMsg, setVoiceMsg] = useState<string | null>(null);
  const voiceTickRef = useRef<number | null>(null);
  const [voiceExpanded, setVoiceExpanded] = useState<Record<string, boolean>>({});
  const toggleVoiceExpanded = (label: string) =>
    setVoiceExpanded((prev) => ({ ...prev, [label]: !prev[label] }));

  const removeVoiceFile = async (name: string, file: string) => {
    if (!confirm(`Delete voice sample "${file}" for "${name}"?`)) return;
    try {
      await fetch("/api/voice/file/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, file }),
      });
      loadFaceOwners();
    } catch { /* ignore */ }
  };

  const startVoiceEnroll = () => {
    if (!voiceLabel.trim()) {
      setVoiceMsg("Enter a name first");
      return;
    }
    setVoiceMsg(null);
    setVoicePhase("countdown");
    let pre = 3;
    setVoiceCountdown(pre);
    voiceTickRef.current = window.setInterval(() => {
      pre -= 1;
      if (pre > 0) {
        setVoiceCountdown(pre);
        return;
      }
      // Pre-countdown done — actually fire the recording on the lamp.
      if (voiceTickRef.current) clearInterval(voiceTickRef.current);
      setVoicePhase("recording");
      let remaining = VOICE_DURATION_SEC;
      setVoiceCountdown(remaining);
      voiceTickRef.current = window.setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
          if (voiceTickRef.current) clearInterval(voiceTickRef.current);
          setVoicePhase("processing");
          setVoiceCountdown(0);
        } else {
          setVoiceCountdown(remaining);
        }
      }, 1000);
      // POST starts at the same instant the lamp begins recording, so the
      // client countdown stays in sync with what the lamp is actually doing.
      fetch("/api/voice/enroll", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: voiceLabel.trim().toLowerCase(), duration_sec: VOICE_DURATION_SEC }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (voiceTickRef.current) clearInterval(voiceTickRef.current);
          setVoicePhase("idle");
          setVoiceCountdown(0);
          if (data.status === 1) {
            setVoiceMsg(`Enrolled "${voiceLabel.trim().toLowerCase()}"`);
            loadFaceOwners();
          } else {
            setVoiceMsg(`Error: ${data.message ?? "enroll failed"}`);
          }
        })
        .catch((e) => {
          if (voiceTickRef.current) clearInterval(voiceTickRef.current);
          setVoicePhase("idle");
          setVoiceCountdown(0);
          setVoiceMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
        });
    }, 1000);
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
        if (resp.ok) ok++;
        else lastErr = data.detail || data.message || `Failed: ${file.name}`;
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
    getTTSProviders().then(setTtsProviders).catch(() => {});
    getTTSVoices().then(setTtsVoices).catch(() => {});
    // Pre-populate the form from any existing config so re-running setup
    // doesn't blank out fields the operator already filled. URL params and
    // anything the user has typed take precedence — we only fill empty
    // state slots (prev || cfg.x).
    getDeviceConfig().then((cfg) => {
      if (cfg.tts_provider) setTtsProvider(cfg.tts_provider);
      if (cfg.tts_voice) setTtsVoice(cfg.tts_voice);
      setSsid((prev) => prev || cfg.network_ssid || "");
      setPassword((prev) => prev || cfg.network_password || "");
      setDeviceId((prev) => prev || cfg.device_id || "");
      // If Device ID is already provisioned (hardware-derived or saved), the
      // operator has nothing to fill there — jump straight to Wi-Fi. Don't
      // override an explicit user selection in progress.
      if (cfg.device_id) {
        setActiveSection((prev) => (prev === "device" ? "wifi" : prev));
      }
      setLlmApiKey((prev) => prev || cfg.llm_api_key || "");
      setLlmUrl((prev) => prev || cfg.llm_base_url || "");
      setLlmModel((prev) => prev || cfg.llm_model || "");
      setLlmLoaded((prev) => ({
        apiKey: prev.apiKey || !!cfg.llm_api_key,
        baseUrl: prev.baseUrl || !!cfg.llm_base_url,
        model: prev.model || !!cfg.llm_model,
      }));
      if (cfg.llm_disable_thinking != null) setLlmDisableThinking((prev) => prev || cfg.llm_disable_thinking);
      setTtsApiKey((prev) => prev || cfg.tts_api_key || "");
      setTtsBaseUrl((prev) => prev || cfg.tts_base_url || "");
      setChannelLoaded((prev) => ({
        teleToken: prev.teleToken || !!cfg.telegram_bot_token,
        teleUserId: prev.teleUserId || !!cfg.telegram_user_id,
        slackBotToken: prev.slackBotToken || !!cfg.slack_bot_token,
        slackAppToken: prev.slackAppToken || !!cfg.slack_app_token,
        slackUserId: prev.slackUserId || !!cfg.slack_user_id,
        discordBotToken: prev.discordBotToken || !!cfg.discord_bot_token,
        discordGuildId: prev.discordGuildId || !!cfg.discord_guild_id,
        discordUserId: prev.discordUserId || !!cfg.discord_user_id,
      }));
      setTeleToken((prev) => prev || cfg.telegram_bot_token || "");
      setTeleUserId((prev) => prev || cfg.telegram_user_id || "");
      setSlackBotToken((prev) => prev || cfg.slack_bot_token || "");
      setSlackAppToken((prev) => prev || cfg.slack_app_token || "");
      setSlackUserId((prev) => prev || cfg.slack_user_id || "");
      setDiscordBotToken((prev) => prev || cfg.discord_bot_token || "");
      setDiscordGuildId((prev) => prev || cfg.discord_guild_id || "");
      setDiscordUserId((prev) => prev || cfg.discord_user_id || "");
      // Adopt saved channel only when the user hasn't already picked one via URL.
      if (!channelParam && (cfg.channel === "telegram" || cfg.channel === "slack" || cfg.channel === "discord")) {
        setChannel(cfg.channel as ChannelType);
      }
      setMqttEndpoint((prev) => prev || cfg.mqtt_endpoint || "");
      setMqttPort((prev) => prev || (cfg.mqtt_port ? String(cfg.mqtt_port) : ""));
      setMqttUsername((prev) => prev || cfg.mqtt_username || "");
      setMqttPassword((prev) => prev || cfg.mqtt_password || "");
      setFaChannel((prev) => prev || cfg.fa_channel || "");
      setFdChannel((prev) => prev || cfg.fd_channel || "");
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


  // Refetch voices when provider changes — only reset voice if user changed provider
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
  // Same for STT (no UI in Setup — silently mirrors LLM into config).
  useEffect(() => {
    if (!sttApiKey && llmApiKey) setSttApiKey(llmApiKey);
  }, [llmApiKey, sttApiKey]);
  useEffect(() => {
    if (!sttBaseUrl && llmUrl) setSttBaseUrl(llmUrl);
  }, [llmUrl, sttBaseUrl]);

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
        deepgram_api_key: urlParams.deepgramApiKey || undefined,
        stt_api_key: sttApiKey || undefined,
        stt_base_url: sttBaseUrl || undefined,
        tts_api_key: ttsApiKey || undefined,
        tts_base_url: ttsBaseUrl || undefined,
        tts_provider: ttsProvider || undefined,
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
    llmModel, llmDisableThinking, sttApiKey, sttBaseUrl, ttsApiKey, ttsBaseUrl, ttsVoice, deviceId,
    mqttEndpoint, mqttPort, mqttUsername, mqttPassword, faChannel, fdChannel,
  ]);

  return (
    <div className={`lm-root lm-setup ${themeClass}`} style={{
      display: "flex", height: "100vh",
      background: C.bg, color: C.text,
      fontFamily: "'Inter', 'Segoe UI', sans-serif", fontSize: 14,
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

                  {/* Device */}
                  <SectionCard id="device" title="Device" active={activeSection === "device"}>
                    <Field label="Device ID" id="device_id" value={deviceId} onChange={setDeviceId} placeholder="lumi-001" readOnly />
                  </SectionCard>

                  {/* Wi-Fi */}
                  <SectionCard id="wifi" title="Wi-Fi" active={activeSection === "wifi"}>
                    <div style={{ marginBottom: 12 }}>
                      <label htmlFor="ssid" style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
                        Wi-Fi network
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
                          placeholder="Enter Wi-Fi name" autoComplete="off"
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

                  {/* LLM */}
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

                  {/* Voice enrollment — user stands near the lamp and reads
                      3 sentences while the LAMP'S OWN MIC records. Web is
                      just a remote trigger — no browser mic permission, no
                      HTTPS required. */}
                  <SectionCard id="voice" title="Voice Enroll (optional)" active={activeSection === "voice"}>
                    <div style={{ fontSize: 11, color: C.textDim, marginBottom: 12 }}>
                      Stand near the lamp. When recording starts, read the 3 sentences in a normal voice. The lamp's mic captures you — your laptop mic is not used.
                    </div>
                    <Field label="Name" id="voice_label" value={voiceLabel} onChange={setVoiceLabel} placeholder="e.g. Leo" />
                    <div style={{
                      background: C.surface, border: `1px solid ${C.border}`, borderRadius: 7,
                      padding: "12px 14px", marginBottom: 12, fontSize: 13, lineHeight: 1.55, color: C.text,
                    }}>
                      {VOICE_PHRASES.map((p, i) => (
                        <div key={i} style={{ marginBottom: i < VOICE_PHRASES.length - 1 ? 6 : 0 }}>
                          <span style={{ color: C.textMuted, marginRight: 6 }}>{i + 1}.</span>
                          {p}
                        </div>
                      ))}
                    </div>
                    {voiceMsg && (
                      <div style={{
                        fontSize: 11, padding: "6px 10px", borderRadius: 6, marginBottom: 10,
                        background: voiceMsg.startsWith("Error") ? "rgba(248,113,113,0.08)" : "rgba(52,211,153,0.08)",
                        color: voiceMsg.startsWith("Error") ? C.red : "rgb(52,211,153)",
                      }}>{voiceMsg}</div>
                    )}
                    <button
                      type="button"
                      onClick={startVoiceEnroll}
                      disabled={!voiceLabel.trim() || voicePhase !== "idle"}
                      style={{
                        width: "100%", padding: "11px 0", borderRadius: 7, fontSize: 13, fontWeight: 600,
                        cursor: voicePhase === "idle" && voiceLabel.trim() ? "pointer" : "not-allowed",
                        background: voicePhase === "recording" ? "rgba(248,113,113,0.18)"
                          : voicePhase === "countdown" ? "rgba(245,158,11,0.18)"
                          : voicePhase === "processing" ? C.surface
                          : !voiceLabel.trim() ? C.surface : "rgba(52,211,153,0.12)",
                        border: `1px solid ${voicePhase === "recording" ? "rgba(248,113,113,0.4)"
                          : voicePhase === "countdown" ? "rgba(245,158,11,0.4)"
                          : !voiceLabel.trim() ? C.border : "rgba(52,211,153,0.35)"}`,
                        color: voicePhase === "recording" ? C.red
                          : voicePhase === "countdown" ? C.amber
                          : voicePhase === "processing" ? C.textDim
                          : !voiceLabel.trim() ? C.textMuted : "rgb(52,211,153)",
                      }}
                    >
                      {voicePhase === "idle" && `Start Recording (${VOICE_DURATION_SEC}s on lamp)`}
                      {voicePhase === "countdown" && `Get ready... ${voiceCountdown}`}
                      {voicePhase === "recording" && `● Recording on lamp — read aloud (${voiceCountdown}s)`}
                      {voicePhase === "processing" && "Processing..."}
                    </button>
                    {(() => {
                      const withVoice = faceOwners.filter((p) => (p.voice_samples?.length ?? 0) > 0);
                      if (withVoice.length === 0) return null;
                      return (
                        <div style={{ marginTop: 16, borderTop: `1px solid ${C.border}`, paddingTop: 14 }}>
                          <div style={{ fontSize: 10, fontWeight: 700, color: C.textDim, textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 10 }}>
                            Voice Files
                          </div>
                          {withVoice.map((p) => {
                            const expanded = !!voiceExpanded[p.label];
                            return (
                            <div key={p.label} style={{ padding: "10px 0", borderBottom: `1px solid ${C.border}` }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: expanded ? 8 : 0 }}>
                                <button
                                  type="button"
                                  onClick={() => toggleVoiceExpanded(p.label)}
                                  style={{
                                    flex: 1, display: "flex", alignItems: "center", gap: 8,
                                    background: "none", border: "none", cursor: "pointer", padding: 0,
                                    textAlign: "left", color: C.text,
                                  }}
                                >
                                  <span style={{ fontSize: 11, color: C.textMuted, transition: "transform 0.15s", transform: expanded ? "rotate(90deg)" : "none" }}>▶</span>
                                  <span style={{ fontSize: 13, fontWeight: 600 }}>{p.label}</span>
                                  <span style={{ fontSize: 10, color: C.textMuted, fontWeight: 400 }}>({p.voice_samples!.length} file{p.voice_samples!.length !== 1 ? "s" : ""})</span>
                                </button>
                                <button
                                  type="button"
                                  onClick={async () => {
                                    if (!confirm(`Remove ALL voice files for "${p.label}"? Face data is preserved.`)) return;
                                    try {
                                      await fetch("/hw/speaker/remove", {
                                        method: "POST",
                                        headers: { "Content-Type": "application/json" },
                                        body: JSON.stringify({ name: p.label }),
                                      });
                                      loadFaceOwners();
                                    } catch { /* ignore */ }
                                  }}
                                  style={{
                                    background: "none", border: `1px solid ${C.border}`, borderRadius: 5,
                                    cursor: "pointer", fontSize: 10, color: C.red, padding: "3px 8px",
                                  }}
                                >
                                  Remove all
                                </button>
                              </div>
                              {expanded && (<>

                              {p.voice_samples!.map((file) => {
                                const ext = file.toLowerCase().split(".").pop() || "";
                                const url = `/hw/face/file/${p.label}/voice/${encodeURIComponent(file)}`;
                                const isAudio = ["wav", "ogg", "mp3", "webm", "m4a"].includes(ext);
                                const viewLabel = ["json", "jsonl", "txt"].includes(ext) ? "view" : "open";
                                return (
                                  <div key={file} title={file} style={{
                                    display: "flex", alignItems: "center", gap: 6, padding: "3px 0",
                                    fontSize: 11, color: C.textDim,
                                  }}>
                                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "monospace" }}>
                                      {file}
                                    </span>
                                    {isAudio ? (
                                      <>
                                        <audio controls src={url} style={{ width: 180, height: 24 }} />
                                        <button type="button" onClick={() => removeVoiceFile(p.label, file)}
                                          style={{ background: "none", border: "none", cursor: "pointer", color: C.red, fontSize: 14, lineHeight: 1, padding: "0 4px" }} title="Delete">
                                          ×
                                        </button>
                                      </>
                                    ) : (
                                      <a href={url} target="_blank" rel="noreferrer"
                                        style={{ fontSize: 10, color: C.amber, textDecoration: "none", padding: "2px 6px", border: `1px solid ${C.border}`, borderRadius: 4 }}>
                                        {viewLabel}
                                      </a>
                                    )}
                                  </div>
                                );
                              })}
                              </>)}
                            </div>
                            );
                          })}
                        </div>
                      );
                    })()}
                  </SectionCard>

                  {/* Face enrollment — optional during setup; user can enroll
                      themselves so the lamp recognizes them on first boot. */}
                  <SectionCard id="face" title="Face Enroll (optional)" active={activeSection === "face"}>
                    <div style={{ fontSize: 11, color: C.textDim, marginBottom: 12 }}>
                      Upload photos so the lamp can recognize you.
                    </div>
                    <Field label="Name" id="face_name" value={faceName} onChange={setFaceName} placeholder="e.g. Leo" />
                    <div style={{ marginBottom: 12 }}>
                      <label style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
                        Photos ({faceFiles.length} selected)
                      </label>
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
                          <div key={p.label} style={{ padding: "10px 0", borderBottom: `1px solid ${C.border}` }}>
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

                  {/* Channel */}
                  <SectionCard id="channel" title="Messaging Channels" active={activeSection === "channel"}>

                    <div style={{ marginBottom: 12 }}>
                      <label htmlFor="channel" style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>Channel *</label>
                      <select
                        id="channel"
                        value={channel}
                        onChange={(e) => setChannel(e.target.value as ChannelType)}
                        style={{
                          width: "100%", boxSizing: "border-box",
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
                        <LockedPasswordField required lockedInitially={channelLoaded.teleToken} label="Bot Token *" id="tele_token" value={teleToken} onChange={setTeleToken} placeholder="123456:ABC-DEF..." />
                        <LockedField required lockedInitially={channelLoaded.teleUserId} label="User ID *" id="tele_user_id" value={teleUserId} onChange={setTeleUserId} placeholder="123456789" />
                      </>
                    )}
                    {channel === "slack" && (
                      <>
                        <LockedPasswordField required lockedInitially={channelLoaded.slackBotToken} label="Bot Token *" id="slack_bot_token" value={slackBotToken} onChange={setSlackBotToken} placeholder="xoxb-..." />
                        <LockedPasswordField required lockedInitially={channelLoaded.slackAppToken} label="App Token *" id="slack_app_token" value={slackAppToken} onChange={setSlackAppToken} placeholder="xapp-..." />
                        <LockedField required lockedInitially={channelLoaded.slackUserId} label="User ID *" id="slack_user_id" value={slackUserId} onChange={setSlackUserId} placeholder="U0123456789" />
                      </>
                    )}
                    {channel === "discord" && (
                      <>
                        <LockedPasswordField required lockedInitially={channelLoaded.discordBotToken} label="Bot Token *" id="discord_bot_token" value={discordBotToken} onChange={setDiscordBotToken} placeholder="Bot token" />
                        <LockedField required lockedInitially={channelLoaded.discordGuildId} label="Guild ID *" id="discord_guild_id" value={discordGuildId} onChange={setDiscordGuildId} placeholder="123456789" />
                        <LockedField required lockedInitially={channelLoaded.discordUserId} label="User ID *" id="discord_user_id" value={discordUserId} onChange={setDiscordUserId} placeholder="123456789" />
                      </>
                    )}
                  </SectionCard>

                  {/* TTS */}
                  <SectionCard id="tts" title="TTS Voice" active={activeSection === "tts"}>
                    {/* tts_api_key + tts_base_url are not exposed in Setup —
                        they're auto-mirrored from AI Brain via useEffect and
                        submitted silently. */}
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

                </form>
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
