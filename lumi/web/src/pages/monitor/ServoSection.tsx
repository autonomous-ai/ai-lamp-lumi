import { useCallback, useEffect, useState } from "react";
import { S } from "./styles";
import { HW } from "./types";
import type { ServoState } from "./types";
import { StatusDot } from "./components";

interface ServoDetail {
  id: number;
  angle: number | null;
  online: boolean;
  error?: string | null;
}

export function ServoSection() {
  const [servo, setServo] = useState<ServoState | null>(null);
  const [servos, setServos] = useState<Record<string, ServoDetail> | null>(null);
  const [aims, setAims] = useState<string[]>([]);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [sr, st] = await Promise.all([
        fetch(`${HW}/servo`).then((r) => r.json()).catch(() => null),
        fetch(`${HW}/servo/status`).then((r) => r.json()).catch(() => null),
      ]);
      if (sr) setServo(sr);
      if (st?.servos) setServos(st.servos);
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
    fetch(`${HW}/servo/aim`).then((r) => r.json()).then((r) => {
      if (r?.directions) setAims(r.directions);
    }).catch(() => {});
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  const flash = (msg: string) => {
    setActionMsg(msg);
    setTimeout(() => setActionMsg(null), 2000);
  };

  const playAnim = async (recording: string) => {
    flash(`Playing ${recording}...`);
    await fetch(`${HW}/servo/play`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recording }),
    }).catch(() => {});
    setTimeout(refresh, 500);
  };

  const aimTo = async (direction: string) => {
    flash(`Aiming ${direction}...`);
    await fetch(`${HW}/servo/aim`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction, duration: 2.0 }),
    }).catch(() => {});
    setTimeout(refresh, 2500);
  };

  const release = async () => {
    flash("Releasing...");
    await fetch(`${HW}/servo/release`, {
      method: "POST",
      headers: { accept: "application/json" },
    }).catch(() => {});
    setTimeout(refresh, 500);
  };

  const onlineCount = servos ? Object.values(servos).filter((s) => s.online).length : 0;
  const totalCount = servos ? Object.keys(servos).length : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {actionMsg && (
        <div style={{
          padding: "8px 14px", borderRadius: 6,
          background: "var(--lm-amber-dim, rgba(245,158,11,0.1))",
          border: "1px solid var(--lm-amber, #f59e0b)",
          color: "var(--lm-amber, #f59e0b)", fontSize: 12, fontWeight: 600,
        }}>{actionMsg}</div>
      )}

      {/* Per-servo status */}
      <div style={S.card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={S.cardLabel}>Servos ({onlineCount}/{totalCount} online)</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--lm-amber, #f59e0b)" }}>
            {servo?.current || "idle"}
          </div>
        </div>
        {servos ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10, marginTop: 8 }}>
            {Object.entries(servos).sort(([,a], [,b]) => a.id - b.id).map(([joint, info]) => (
              <div key={joint} style={{
                padding: "10px 12px", borderRadius: 6,
                background: "var(--lm-surface)",
                border: `1px solid ${info.online ? "var(--lm-border)" : "rgba(239,68,68,0.4)"}`,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: "var(--lm-text-dim)" }}>
                    {joint.replace(".pos", "")}
                  </span>
                  <span style={{ fontSize: 10, color: "var(--lm-text-muted)" }}>ID {info.id}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <StatusDot ok={info.online} />
                  {info.online && info.angle != null ? (
                    <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{ flex: 1, height: 6, borderRadius: 3, background: "var(--lm-border)", overflow: "hidden" }}>
                        <div style={{
                          width: `${Math.min(100, Math.max(0, ((info.angle + 180) / 360) * 100))}%`,
                          height: "100%", borderRadius: 3,
                          background: "var(--lm-teal, #14b8a6)", transition: "width 0.3s ease",
                        }} />
                      </div>
                      <span style={{ fontSize: 12, fontWeight: 600, color: "var(--lm-teal, #14b8a6)", minWidth: 48, textAlign: "right" }}>
                        {info.angle.toFixed(1)}&deg;
                      </span>
                    </div>
                  ) : (
                    <span style={{ fontSize: 11, color: "var(--lm-red, #ef4444)" }}>
                      {info.error || "offline"}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "var(--lm-text-muted)", marginTop: 8 }}>Loading...</div>
        )}
      </div>

      {/* Aim */}
      {aims.length > 0 && (
        <div style={S.card}>
          <div style={S.cardLabel}>Aim Direction</div>
          <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 6 }}>
            {aims.map((dir) => (
              <button key={dir} onClick={() => aimTo(dir)} style={{
                fontSize: 11, padding: "5px 14px", borderRadius: 5,
                background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
                color: "var(--lm-text-dim)", cursor: "pointer",
              }}>{dir}</button>
            ))}
          </div>
        </div>
      )}

      {/* Animations */}
      <div style={S.card}>
        <div style={S.cardLabel}>Animations</div>
        <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 6 }}>
          {(servo?.available_recordings ?? []).map((anim) => (
            <button key={anim} onClick={() => playAnim(anim)} style={{
              fontSize: 11, padding: "5px 14px", borderRadius: 5,
              background: anim === servo?.current ? "var(--lm-amber-dim, rgba(245,158,11,0.1))" : "var(--lm-surface)",
              border: `1px solid ${anim === servo?.current ? "var(--lm-amber, #f59e0b)" : "var(--lm-border)"}`,
              color: anim === servo?.current ? "var(--lm-amber, #f59e0b)" : "var(--lm-text-dim)",
              cursor: "pointer", fontWeight: anim === servo?.current ? 600 : 400,
            }}>{anim}</button>
          ))}
        </div>
      </div>

      {/* Release */}
      <div style={S.card}>
        <div style={S.cardLabel}>Motor Control</div>
        <button onClick={release} style={{
          fontSize: 12, padding: "6px 18px", borderRadius: 5,
          background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.3)",
          color: "var(--lm-red, #ef4444)", cursor: "pointer", fontWeight: 600,
        }}>Release All Servos</button>
        <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginTop: 4 }}>
          Disables torque — lamp can be moved by hand
        </div>
      </div>
    </div>
  );
}
