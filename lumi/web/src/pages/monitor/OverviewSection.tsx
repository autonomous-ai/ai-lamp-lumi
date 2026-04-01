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
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Top row: 4 status cards */}
      <div style={S.grid2}>
        {/* OpenClaw */}
        <div style={S.card}>
          <div style={S.cardLabel}>OpenClaw AI</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <StatusDot ok={oc?.connected ?? false} />
            <span style={{ fontSize: 13, fontWeight: 600, color: oc?.connected ? "var(--lm-green)" : "var(--lm-red)" }}>
              {oc?.connected ? "Connected" : "Disconnected"}
            </span>
          </div>
          {oc && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Agent: <span style={{ color: "var(--lm-text)" }}>{oc.name}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Session key:
                <span style={{
                  fontSize: 10, padding: "1px 6px", borderRadius: 4,
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
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <StatusDot ok={net.internet} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--lm-text)" }}>{net.ssid || "—"}</span>
                </div>
                <SignalBars value={net.signal} />
              </div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>IP: <span style={{ color: "var(--lm-teal)" }}>{net.ip}</span></div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>Signal: <span style={{ color: "var(--lm-text)" }}>{net.signal} dBm</span></div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Internet: <span style={{ color: net.internet ? "var(--lm-green)" : "var(--lm-red)" }}>{net.internet ? "OK" : "No"}</span>
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        {/* Presence */}
        <div style={S.card}>
          <div style={S.cardLabel}>Presence</div>
          {presence ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <StatusDot ok={presence.state === "active"} />
                <span style={{ fontSize: 14, fontWeight: 700, color: presence.state === "active" ? "var(--lm-amber)" : "var(--lm-text-dim)" }}>
                  {presence.state}
                </span>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Sensing: <span style={{ color: presence.enabled ? "var(--lm-green)" : "var(--lm-red)" }}>{presence.enabled ? "Enabled" : "Disabled"}</span>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Last motion: <span style={{ color: "var(--lm-text)" }}>{presence.seconds_since_motion}s ago</span>
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        {/* Voice */}
        <div style={S.card}>
          <div style={S.cardLabel}>Voice & TTS</div>
          {voice ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={voice.voice_available} />
                <span style={{ fontSize: 12, fontWeight: 600 }}>Mic</span>
                {voice.voice_listening && (
                  <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--lm-amber-dim)", color: "var(--lm-amber)" }}>LIVE</span>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={voice.tts_available} />
                <span style={{ fontSize: 12, fontWeight: 600 }}>TTS</span>
                {voice.tts_speaking && (
                  <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "rgba(167,139,250,0.15)", color: "var(--lm-purple)" }}>SPEAKING</span>
                )}
              </div>
              <div style={{ marginTop: 4, fontSize: 11.5, color: "var(--lm-text-dim)" }}>
                Volume: <span style={{ color: "var(--lm-amber)" }}>{audio?.volume ?? "—"}%</span>
              </div>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>
      </div>

      {/* Emotion */}
      {(() => {
        const emotion = oc?.emotion ?? "";
        const color = EMOTION_COLOR[emotion] ?? "var(--lm-text-muted)";
        const emoji = EMOTION_EMOJI[emotion] ?? "✦";
        return (
          <div style={{
            ...S.card, padding: "16px 20px",
            background: emotion ? `linear-gradient(135deg, var(--lm-bg) 60%, ${color}18)` : "var(--lm-bg)",
            border: `1px solid ${emotion ? color + "55" : "var(--lm-border)"}`,
            transition: "all 0.4s ease",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              {/* Big emoji */}
              <div style={{
                fontSize: 48, lineHeight: 1,
                filter: emotion ? `drop-shadow(0 0 12px ${color}88)` : "none",
                transition: "filter 0.4s ease",
                flexShrink: 0,
              }}>
                {emotion ? emoji : "✦"}
              </div>
              {/* Name + label */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginBottom: 2, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Lumi is feeling
                </div>
                <div style={{
                  fontSize: 22, fontWeight: 700,
                  color: emotion ? color : "var(--lm-text-muted)",
                  textTransform: "capitalize",
                  transition: "color 0.4s ease",
                }}>
                  {emotion || "—"}
                </div>
              </div>
              {/* All emotions grid */}
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 5, justifyContent: "flex-end", maxWidth: 320 }}>
                {ALL_EMOTIONS.map((e) => {
                  const active = e === emotion;
                  const c = EMOTION_COLOR[e] ?? "#fff";
                  return (
                    <span key={e} style={{
                      fontSize: 10, padding: "2px 8px", borderRadius: 10,
                      background: active ? `${c}22` : "var(--lm-surface)",
                      border: `1px solid ${active ? c + "88" : "var(--lm-border)"}`,
                      color: active ? c : "var(--lm-text-muted)",
                      fontWeight: active ? 700 : 400,
                      textTransform: "capitalize",
                      transition: "all 0.3s ease",
                    }}>
                      {EMOTION_EMOJI[e]} {e}
                    </span>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })()}

      {/* Hardware status */}
      <div style={S.card}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <div style={S.cardLabel}>Hardware</div>
          {/* LED color swatch */}
          {ledColor && (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>LED color</span>
              <div style={{
                width: 22, height: 22, borderRadius: 6,
                background: ledColor.hex,
                boxShadow: `0 0 8px ${ledColor.hex}99`,
                border: "1px solid rgba(255,255,255,0.1)",
                flexShrink: 0,
              }} title={`RGB(${ledColor.color.join(", ")})`} />
              <span style={{
                fontSize: 11, fontFamily: "monospace",
                color: "var(--lm-text-dim)",
              }}>{ledColor.hex}</span>
            </div>
          )}
        </div>
        {hw ? (
          <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 8 }}>
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

      {/* Scene presets */}
      <div style={S.card}>
        <div style={S.cardLabel}>Scene</div>
        {sceneInfo ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 11.5, color: "var(--lm-text-dim)" }}>
              {sceneInfo.scenes.length} presets available
            </div>
            <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 6, marginTop: 2 }}>
              {sceneInfo.scenes.map((s) => (
                <span key={s} role="button" onClick={() => onSceneActivate(s)} style={{
                  fontSize: 11,
                  padding: "4px 10px",
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
          </div>
        ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
      </div>

      {/* Servo + Display row */}
      <div style={S.grid2}>
        <div style={S.card}>
          <div style={S.cardLabel}>Servo Pose</div>
          {servo ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--lm-amber)" }}>
                {servo.current || "idle"}
              </div>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                {servo.available_recordings?.length ?? 0} poses available
                {servo.bus_connected === false || servo.robot_connected === false ? (
                  <span style={{ color: "var(--lm-danger, #c44)", marginLeft: 6 }}>
                    (bus {servo.bus_connected === false ? "down" : "ok"}
                    {servo.robot_connected === false ? ", robot disconnected" : ""})
                  </span>
                ) : null}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4, marginTop: 4 }}>
                {(servo.available_recordings ?? []).map((p) => (
                  <span key={p} role="button" onClick={() => {
                    fetch(`${HW}/servo/play`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ recording: p }),
                    }).catch(() => {});
                  }} style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: p === servo.current ? "var(--lm-amber-dim)" : "var(--lm-surface)",
                    border: `1px solid ${p === servo.current ? "var(--lm-amber)" : "var(--lm-border)"}`,
                    color: p === servo.current ? "var(--lm-amber)" : "var(--lm-text-dim)",
                    cursor: "pointer",
                  }}>{p}</span>
                ))}
              </div>
              <button onClick={() => {
                fetch(`${HW}/servo/release`, {
                  method: "POST",
                  headers: { accept: "application/json" },
                }).catch(() => {});
              }} style={{
                marginTop: 4,
                fontSize: 10,
                padding: "3px 10px",
                borderRadius: 4,
                background: "var(--lm-surface)",
                border: "1px solid var(--lm-border)",
                color: "var(--lm-text-dim)",
                cursor: "pointer",
              }}>Release</button>
            </div>
          ) : <span style={{ color: "var(--lm-text-muted)" }}>Loading…</span>}
        </div>

        <div style={S.card}>
          <div style={S.cardLabel}>Display Eyes</div>
          {displayState ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot ok={displayState.hardware} />
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--lm-teal)" }}>
                  {displayState.mode}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "var(--lm-text-dim)" }}>
                {displayState.available_expressions?.length ?? 0} expressions
              </div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4, marginTop: 4 }}>
                {(displayState.available_expressions ?? []).map((e) => (
                  <span key={e} style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
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

      {/* System quick stats */}
      {sys && (
        <div style={S.card}>
          <div style={S.cardLabel}>System</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
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
