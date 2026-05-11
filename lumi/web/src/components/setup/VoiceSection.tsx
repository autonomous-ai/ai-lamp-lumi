import { useRef, useState } from "react";
import { C, Field, SectionCard } from "./shared";
import type { FaceOwner } from "@/hooks/setup/useFaceEnroll";

// Voice enrollment lives inside this section component — state is local since
// nothing outside the section reads it. After each enroll we call
// loadFaceOwners so the new sample shows up in the enrolled list.
//
// Phrases + intro are picked by sttLanguage so VN/CN owners read prompts in
// their own language; embedding quality drops if the owner stumbles through
// English they don't speak natively. Mirrors EditConfig.tsx — kept in sync.
const VOICE_PHRASES_BY_LANG: Record<string, string[]> = {
  en: [
    "Hi Lumi, I'm enrolling my voice so you can recognize me when we talk.",
    "The quick brown fox jumps over the lazy dog near the bright morning window.",
    "Today is a great day to start something new, and I'm looking forward to it.",
  ],
  vi: [
    "Chào Lumi, mình đang đăng ký giọng nói để bạn nhận ra mình khi nói chuyện.",
    "Hôm nay là một ngày tuyệt vời, mình rất mong chờ những điều mới mẻ phía trước.",
    "Một cốc cà phê nóng vào buổi sáng giúp mình tỉnh táo và bắt đầu công việc tốt hơn.",
  ],
  "zh-CN": [
    "你好 Lumi，我正在录入我的声音，这样你听到我说话就能认出我。",
    "今天天气不错，是开始新事情的好日子，我期待接下来的一切。",
    "早晨喝一杯热咖啡能让我精神焕发，更好地开始一天的工作。",
  ],
  "zh-TW": [
    "你好 Lumi，我正在錄入我的聲音，這樣你聽到我說話就能認出我。",
    "今天天氣不錯，是開始新事情的好日子，我期待接下來的一切。",
    "早晨喝一杯熱咖啡能讓我精神煥發，更好地開始一天的工作。",
  ],
};
const VOICE_INTRO_BY_LANG: Record<string, string> = {
  en: "Stand near the lamp. When recording starts, read the 3 sentences in a normal voice. The lamp's mic captures you — your laptop mic is not used.",
  vi: "Đứng gần đèn. Khi bắt đầu ghi âm, đọc 3 câu sau với giọng bình thường. Mic của đèn sẽ thu âm bạn — không dùng mic của máy tính.",
  "zh-CN": "站在台灯附近。开始录音后，用正常语速朗读这 3 句话。台灯的麦克风会录下你的声音 — 不使用电脑麦克风。",
  "zh-TW": "站在檯燈附近。開始錄音後，用正常語速朗讀這 3 句話。檯燈的麥克風會錄下你的聲音 — 不使用電腦麥克風。",
};
const VOICE_DURATION_SEC = 15;

export function VoiceSection({
  active, sttLanguage, faceOwners, loadFaceOwners,
}: {
  active: boolean;
  sttLanguage: string;
  faceOwners: FaceOwner[];
  loadFaceOwners: () => Promise<void>;
}) {
  const VOICE_PHRASES = VOICE_PHRASES_BY_LANG[sttLanguage] ?? VOICE_PHRASES_BY_LANG.en;
  const VOICE_INTRO = VOICE_INTRO_BY_LANG[sttLanguage] ?? VOICE_INTRO_BY_LANG.en;
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
      fetch("/hw/speaker/record-enroll", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: voiceLabel.trim().toLowerCase(), duration_sec: VOICE_DURATION_SEC }),
      })
        .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
          if (voiceTickRef.current) clearInterval(voiceTickRef.current);
          setVoicePhase("idle");
          setVoiceCountdown(0);
          if (ok && data.status === "ok") {
            setVoiceMsg(`Enrolled "${voiceLabel.trim().toLowerCase()}"`);
            loadFaceOwners();
          } else {
            setVoiceMsg(`Error: ${data.detail ?? data.message ?? "enroll failed"}`);
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

  const enrolled = faceOwners.filter((p) => (p.voice_samples?.length ?? 0) > 0);

  return (
    <SectionCard id="voice" title="My Voice (optional)" active={active}>
      <div style={{ fontSize: 11, color: C.textDim, marginBottom: 12 }}>
        {VOICE_INTRO}
      </div>
      <Field label="Name" id="voice_label" value={voiceLabel} onChange={setVoiceLabel} placeholder="e.g. Leo" />
      <div style={{
        background: C.surface, border: `1px solid ${C.border}`,
        borderRadius: 7, padding: "10px 12px", marginBottom: 10, fontSize: 12, lineHeight: 1.5,
      }}>
        {VOICE_PHRASES.map((p, i) => (
          <div key={i} style={{ marginBottom: i < VOICE_PHRASES.length - 1 ? 6 : 0 }}>
            <span style={{ color: C.textMuted, marginRight: 6 }}>{i + 1}.</span>
            <span style={{ color: C.text }}>{p}</span>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <button
          type="button" disabled={voicePhase !== "idle"}
          onClick={startVoiceEnroll}
          style={{
            flex: 1, padding: "8px 0",
            background: voicePhase === "idle" ? C.amber : C.surface,
            color: voicePhase === "idle" ? "#fff" : C.textDim,
            border: "none", borderRadius: 7, fontSize: 12,
            cursor: voicePhase === "idle" ? "pointer" : "default", fontWeight: 600,
          }}
        >
          {voicePhase === "idle" && "Start recording"}
          {voicePhase === "countdown" && `Get ready... ${voiceCountdown}`}
          {voicePhase === "recording" && `Recording... ${voiceCountdown}s`}
          {voicePhase === "processing" && "Processing..."}
        </button>
      </div>
      {voiceMsg && (
        <div style={{ fontSize: 11, color: voiceMsg.startsWith("Error") ? C.red : C.green, marginTop: 4 }}>
          {voiceMsg}
        </div>
      )}
      {enrolled.length > 0 && (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 11, color: C.textDim, marginBottom: 8 }}>Enrolled:</div>
          {enrolled.map((p) => (
            <div key={p.label} style={{ marginBottom: 6 }}>
              <button type="button" onClick={() => toggleVoiceExpanded(p.label)} style={{
                background: "none", border: "none", color: C.text, fontSize: 12,
                cursor: "pointer", padding: 0, display: "flex", alignItems: "center", gap: 6,
              }}>
                <span>{voiceExpanded[p.label] ? "▾" : "▸"}</span>
                {p.label} <span style={{ color: C.textMuted }}>({p.voice_samples?.length ?? 0})</span>
              </button>
              {voiceExpanded[p.label] && (p.voice_samples?.length ?? 0) > 0 && (
                <div style={{ marginLeft: 18, marginTop: 4 }}>
                  {p.voice_samples!.map((file) => (
                    <div key={file} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 11, color: C.textDim, padding: "3px 0" }}>
                      <span>{file}</span>
                      <button type="button" onClick={() => removeVoiceFile(p.label, file)} style={{
                        background: "none", border: "none", color: C.red, cursor: "pointer", fontSize: 11,
                      }}>remove</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
