import { S } from "./styles";
import { HW } from "./types";

const EMOTION_EMOJI: Record<string, string> = {
  happy: "😊", curious: "🤔", thinking: "💭", sad: "😢", excited: "🤩",
  shy: "😳", shock: "😱", idle: "😐", listening: "👂", laugh: "😄",
  confused: "😕", sleepy: "😴", greeting: "👋", acknowledge: "👍", stretching: "🙆",
};

const EMOTION_COLOR: Record<string, string> = {
  happy:      "#fbbf24", curious:    "#f59e0b", thinking:   "#a78bfa",
  sad:        "#60a5fa", excited:    "#fb923c", shy:        "#f472b6",
  shock:      "#f8fafc", idle:       "#2dd4bf", listening:  "#93c5fd",
  laugh:      "#fbbf24", confused:   "#c4b5fd", sleepy:     "#818cf8",
  greeting:   "#fb923c", acknowledge:"#34d399", stretching: "#fde68a",
};

const ALL_EMOTIONS = [
  "happy","curious","thinking","sad","excited","shy","shock",
  "idle","listening","laugh","confused","sleepy","greeting","acknowledge","stretching",
];
import type { SystemInfo, NetworkInfo, HWHealth, OCStatus, PresenceInfo, VoiceStatus, ServoState, DisplayState, AudioVolume, LEDColor, SceneInfo } from "./types";
import { StatusDot, HWBadge, SignalBars, StatPill, formatUptime } from "./components";

export function OverviewSection({
  sys,
  net,
  hw,
  oc,
  presence,
  voice,
  servo,
  displayState,
  audio,
  ledColor,
  sceneInfo,
  onSceneActivate,
}: {
  sys: SystemInfo | null;
  net: NetworkInfo | null;
  hw: HWHealth | null;
  oc: OCStatus | null;
  presence: PresenceInfo | null;
  voice: VoiceStatus | null;
  servo: ServoState | null;
  displayState: DisplayState | null;
  audio: AudioVolume | null;
  ledColor: LEDColor | null;
  sceneInfo: SceneInfo | null;
  onSceneActivate: (scene: string) => void;
}) {
  const emotion = oc?.emotion ?? "";
  const emotionColor = EMOTION_COLOR[emotion] ?? "var(--lm-text-muted)";
  const emotionEmoji = EMOTION_EMOJI[emotion] ?? "✦";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

      {/* Row 1: 4 status cards in one row */}
      <div className="lm-grid-4">
        {/* OpenClaw */}
        <div style={S.card}>
          <div style={S.cardLabel}>OpenClaw AI</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <StatusDot ok={oc?.connected ?? false} />
            <span style={{ fontSize: 12, fontWeight: 600, color: oc?.connected ? "var(--lm-green)" : "var(--lm-red)" }}>
              {oc?.connected ? "Connected" : "Disconnected"}
            </span>
          </div>
          {oc && (
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                Agent: <span style={{ color: "var(--lm-text)" }}>{oc.name}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--lm-text-dim)" }}>
                Key:
                <span style={{
                  fontSize: 10, padding: "1px 5px", borderRadius: 4,
                  background: oc.sessionKey ? "rgba(52,211,153,0.1)" : "rgba(80,74,60,0.4)",
                  color: oc.sessionKey ? "var(--lm-green)" : "var(--lm-text-muted)",
                  border: `1px solid ${oc.sessionKey ? "rgba(52,211,153,0.3)" : "var(--lm-border)"}`,
                  fontWeight: 600,
                }}>
                  {oc.sessionKey ? "Acquired" : "Pending"}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Network */}
        <div style={S.card}>
          <div style={S.cardLabel}>Network</div>
          {net ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <StatusDot ok={net.internet} />
                  <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--lm-text)" }}>{net.ssid || "—"}</span>
                </div>
                <SignalBars value={net.signal} />
              </div>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>IP: <span style={{ color: "var(--lm-teal)" }}>{net.ip}</span>{net.publicIp && <span style={{ color: "var(--lm-text-dim)" }}> · Public: <span style={{ color: "var(--lm-teal)" }}>{net.publicIp}</span></span>}</div>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                {net.signal} dBm · Internet: <span style={{ color: net.internet ? "var(--lm-green)" : "var(--lm-red)" }}>{net.internet ? "OK" : "No"}</span>
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        {/* Presence */}
        <div style={S.card}>
          <div style={S.cardLabel}>Presence</div>
          {presence ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={presence.state === "active"} />
                <span style={{ fontSize: 13, fontWeight: 700, color: presence.state === "active" ? "var(--lm-amber)" : "var(--lm-text-dim)" }}>
                  {presence.state}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                Sensing: <span style={{ color: presence.enabled ? "var(--lm-green)" : "var(--lm-red)" }}>{presence.enabled ? "On" : "Off"}</span>
              </div>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                Motion: <span style={{ color: "var(--lm-text)" }}>{presence.seconds_since_motion}s ago</span>
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        {/* Voice */}
        <div style={S.card}>
          <div style={S.cardLabel}>Voice & TTS</div>
          {voice ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={voice.voice_available} />
                <span style={{ fontSize: 11.5, fontWeight: 600 }}>Mic</span>
                {voice.voice_listening && (
                  <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 4, background: "var(--lm-amber-dim)", color: "var(--lm-amber)" }}>LIVE</span>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={voice.tts_available} />
                <span style={{ fontSize: 11.5, fontWeight: 600 }}>TTS</span>
                {voice.tts_speaking && (
                  <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 4, background: "rgba(167,139,250,0.15)", color: "var(--lm-purple)" }}>SPEAKING</span>
                )}
              </div>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                Vol: <span style={{ color: "var(--lm-amber)" }}>{audio?.volume ?? "—"}%</span>
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>
      </div>

      {/* Row 2: Emotion (left) + Hardware (right) */}
      <div className="lm-grid-2">
        {/* Emotion */}
        <div style={{
          ...S.card, padding: "14px 16px",
          background: emotion ? `linear-gradient(135deg, var(--lm-bg) 60%, ${emotionColor}18)` : "var(--lm-bg)",
          border: `1px solid ${emotion ? emotionColor + "55" : "var(--lm-border)"}`,
          transition: "all 0.4s ease",
        }}>
          <div style={S.cardLabel}>Emotion</div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              fontSize: 36, lineHeight: 1, flexShrink: 0,
              filter: emotion ? `drop-shadow(0 0 8px ${emotionColor}88)` : "none",
              transition: "filter 0.4s ease",
            }}>
              {emotion ? emotionEmoji : "✦"}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginBottom: 2, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Lumi is feeling
              </div>
              <div style={{ fontSize: 18, fontWeight: 700, color: emotion ? emotionColor : "var(--lm-text-muted)", textTransform: "capitalize", transition: "color 0.4s ease" }}>
                {emotion || "—"}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4, marginTop: 10 }}>
            {ALL_EMOTIONS.map((e) => {
              const active = e === emotion;
              const c = EMOTION_COLOR[e] ?? "#fff";
              return (
                <span key={e} role="button" title={`Test emotion: ${e}`} onClick={() => {
                  fetch(`${HW}/emotion`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ emotion: e, intensity: 1.0 }),
                  }).catch(() => {});
                }} style={{
                  fontSize: 9.5, padding: "1px 6px", borderRadius: 8,
                  background: active ? `${c}22` : "var(--lm-surface)",
                  border: `1px solid ${active ? c + "88" : "var(--lm-border)"}`,
                  color: active ? c : "var(--lm-text-muted)",
                  fontWeight: active ? 700 : 400,
                  textTransform: "capitalize",
                  transition: "all 0.3s ease",
                  cursor: "pointer",
                }}>
                  {EMOTION_EMOJI[e]} {e}
                </span>
              );
            })}
          </div>
        </div>

        {/* Hardware */}
        <div style={S.card}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div style={S.cardLabel}>Hardware</div>
            {ledColor && (
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{
                  width: 14, height: 14, borderRadius: "50%",
                  background: ledColor.on ? ledColor.hex : "transparent",
                  boxShadow: ledColor.on ? `0 0 8px ${ledColor.hex}cc` : "none",
                  border: `2px solid ${ledColor.on ? ledColor.hex : "var(--lm-border)"}`,
                  flexShrink: 0,
                }} title={`RGB(${ledColor.color.join(", ")})`} />
                <span style={{ fontSize: 10, fontFamily: "monospace", color: ledColor.on ? "var(--lm-text)" : "var(--lm-text-muted)" }}>
                  {ledColor.on ? ledColor.hex : "off"}
                </span>
                {ledColor.on && (
                  <span style={{ fontSize: 10, color: "var(--lm-text-dim)" }}>
                    {Math.round(ledColor.brightness * 100)}%
                  </span>
                )}
                {ledColor.effect && (
                  <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 4, background: "rgba(167,139,250,0.15)", color: "var(--lm-purple)", fontWeight: 600 }}>
                    {ledColor.effect}
                  </span>
                )}
                {ledColor.scene && !ledColor.effect && (
                  <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 4, background: "var(--lm-amber-dim)", color: "var(--lm-amber)", fontWeight: 600 }}>
                    {ledColor.scene}
                  </span>
                )}
              </div>
            )}
          </div>
          {hw ? (
            <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 7 }}>
              <HWBadge label="Servo" ok={hw.servo} />
              <HWBadge label="LED" ok={hw.led} />
              <HWBadge label="Camera" ok={hw.camera} />
              <HWBadge label="Audio" ok={hw.audio} />
              <HWBadge label="Sensing" ok={hw.sensing} />
              <HWBadge label="Voice" ok={hw.voice} />
              <HWBadge label="TTS" ok={hw.tts} />
              <HWBadge label="Display" ok={hw.display} />
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>
      </div>

      {/* Row 3: Scene + Servo + Display */}
      <div className="lm-grid-3">
        {/* Scene */}
        <div style={S.card}>
          <div style={S.cardLabel}>Scene</div>
          {sceneInfo ? (
            <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 5 }}>
              {sceneInfo.scenes.map((s) => (
                <span key={s} role="button" onClick={() => onSceneActivate(s)} style={{
                  fontSize: 11,
                  padding: "3px 9px",
                  borderRadius: 6,
                  background: s === sceneInfo.active ? "var(--lm-amber-dim)" : "var(--lm-surface)",
                  border: `1px solid ${s === sceneInfo.active ? "var(--lm-amber)" : "var(--lm-border)"}`,
                  color: s === sceneInfo.active ? "var(--lm-amber)" : "var(--lm-text-dim)",
                  cursor: "pointer",
                  fontWeight: s === sceneInfo.active ? 600 : 400,
                  textTransform: "capitalize",
                }}>{s}</span>
              ))}
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        {/* Servo */}
        <div style={S.card}>
          <div style={S.cardLabel}>Servo Pose</div>
          {servo ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--lm-amber)" }}>
                {servo.current || "idle"}
                {(servo.bus_connected === false || servo.robot_connected === false) && (
                  <span style={{ fontSize: 10, color: "var(--lm-danger, #c44)", marginLeft: 6 }}>
                    (bus {servo.bus_connected === false ? "down" : "ok"}{servo.robot_connected === false ? ", robot off" : ""})
                  </span>
                )}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4 }}>
                {(servo.available_recordings ?? []).map((p) => (
                  <span key={p} role="button" onClick={() => {
                    fetch(`${HW}/servo/play`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ recording: p }),
                    }).catch(() => {});
                  }} style={{
                    fontSize: 10, padding: "2px 6px", borderRadius: 4,
                    background: p === servo.current ? "var(--lm-amber-dim)" : "var(--lm-surface)",
                    border: `1px solid ${p === servo.current ? "var(--lm-amber)" : "var(--lm-border)"}`,
                    color: p === servo.current ? "var(--lm-amber)" : "var(--lm-text-dim)",
                    cursor: "pointer",
                  }}>{p}</span>
                ))}
              </div>
              <button onClick={() => {
                fetch(`${HW}/servo/release`, { method: "POST", headers: { accept: "application/json" } }).catch(() => {});
              }} style={{
                marginTop: 2, fontSize: 10, padding: "3px 9px", borderRadius: 4,
                background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                color: "var(--lm-text-dim)", cursor: "pointer",
              }}>Release</button>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        {/* Display Eyes */}
        <div style={S.card}>
          <div style={S.cardLabel}>Display Eyes</div>
          {displayState ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={displayState.hardware} />
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--lm-teal)" }}>{displayState.mode}</span>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4 }}>
                {(displayState.available_expressions ?? []).map((e) => (
                  <span key={e} style={{
                    fontSize: 10, padding: "2px 6px", borderRadius: 4,
                    background: e === displayState.mode ? "rgba(45,212,191,0.12)" : "var(--lm-surface)",
                    border: `1px solid ${e === displayState.mode ? "rgba(45,212,191,0.4)" : "var(--lm-border)"}`,
                    color: e === displayState.mode ? "var(--lm-teal)" : "var(--lm-text-dim)",
                  }}>{e}</span>
                ))}
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>
      </div>

      {/* Row 4: System stats */}
      {sys && (
        <div style={S.card}>
          <div className="lm-grid-5">
            <StatPill label="CPU" value={`${sys.cpuLoad.toFixed(1)}%`} color="var(--lm-amber)" />
            <StatPill label="RAM" value={`${sys.memPercent.toFixed(0)}%`} color="var(--lm-blue)" />
            <StatPill label="Disk" value={`${(sys.diskPercent ?? 0).toFixed(0)}%`} color={(sys.diskPercent ?? 0) > 90 ? "var(--lm-red)" : "var(--lm-teal)"} />
            <StatPill label="Temp" value={`${sys.cpuTemp.toFixed(1)}°C`} color={sys.cpuTemp > 70 ? "var(--lm-red)" : "var(--lm-teal)"} />
            <StatPill label="Uptime" value={formatUptime(sys.uptime)} />
          </div>
        </div>
      )}

    </div>
  );
}
