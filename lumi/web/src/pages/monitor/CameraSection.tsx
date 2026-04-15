import { useCallback, useEffect, useState } from "react";
import { S } from "./styles";
import { HW } from "./types";

export function CameraSection({
  displayTs: _displayTs,
}: {
  displayTs: number;
}) {
  const [snapTs, setSnapTs] = useState(Date.now());
  const [cameraDisabled, setCameraDisabled] = useState(false);
  const [toggling, setToggling] = useState(false);

  const checkStatus = useCallback(async () => {
    try {
      const r = await fetch(`${HW}/camera`).then((x) => x.json());
      setCameraDisabled(!!r.disabled);
    } catch {}
  }, []);

  useEffect(() => { checkStatus(); }, [checkStatus]);

  const toggleCamera = async () => {
    setToggling(true);
    try {
      await fetch(`${HW}/camera/${cameraDisabled ? "enable" : "disable"}`, { method: "POST" });
      setCameraDisabled(!cameraDisabled);
    } catch {}
    setToggling(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Camera toggle */}
      <div style={S.card}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={S.cardLabel}>Camera</div>
            <div style={{ fontSize: 11, color: "var(--lm-text-muted)" }}>
              {cameraDisabled ? "Disabled — face/motion detection paused, saves CPU" : "Active — streaming, face/motion detection running"}
            </div>
          </div>
          <button
            onClick={toggleCamera}
            disabled={toggling}
            style={{
              padding: "6px 16px", borderRadius: 7, fontSize: 12, fontWeight: 600,
              cursor: toggling ? "wait" : "pointer",
              background: cameraDisabled ? "rgba(52,211,153,0.1)" : "rgba(248,113,113,0.1)",
              border: `1px solid ${cameraDisabled ? "rgba(52,211,153,0.3)" : "rgba(248,113,113,0.3)"}`,
              color: cameraDisabled ? "var(--lm-green)" : "var(--lm-red)",
            }}
          >
            {toggling ? "…" : cameraDisabled ? "Enable" : "Disable"}
          </button>
        </div>
      </div>

      {!cameraDisabled && (
      <div className="lm-grid-2">
        {/* Live camera stream */}
        <div style={S.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={S.cardLabel}>Camera Stream</div>
            <span style={{
              fontSize: 10,
              padding: "2px 7px",
              borderRadius: 4,
              background: "rgba(248,113,113,0.15)",
              color: "var(--lm-red)",
              fontWeight: 700,
              letterSpacing: "0.05em",
            }}>LIVE</span>
          </div>
          <img
            src={`${HW}/camera/stream`}
            alt="camera"
            style={{
              width: "100%",
              borderRadius: 8,
              border: "1px solid var(--lm-border)",
              display: "block",
              background: "var(--lm-surface)",
            }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        </div>

        {/* Display eyes preview */}
        <div style={S.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={S.cardLabel}>Display Eyes (GC9A01)</div>
            <button
              onClick={() => setSnapTs(Date.now())}
              style={{
                fontSize: 10,
                padding: "3px 10px",
                borderRadius: 6,
                background: "var(--lm-amber-dim)",
                border: "1px solid var(--lm-amber)",
                color: "var(--lm-amber)",
                cursor: "pointer",
              }}
            >
              Refresh
            </button>
          </div>
          <div style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            padding: 16,
          }}>
            <img
              src={`${HW}/display/snapshot?t=${snapTs}`}
              alt="display"
              style={{
                width: 160,
                height: 160,
                borderRadius: "50%",
                border: "3px solid var(--lm-amber)",
                boxShadow: "0 0 20px var(--lm-amber-glow)",
                objectFit: "cover",
                display: "block",
                background: "var(--lm-surface)",
              }}
              onError={(e) => {
                const el = e.target as HTMLImageElement;
                el.style.display = "none";
              }}
            />
          </div>
          <div style={{ textAlign: "center" as const, fontSize: 11, color: "var(--lm-text-muted)" }}>
            1.28″ round LCD — 240×240
          </div>
        </div>
      </div>

      {/* Camera snapshot */}
      <div style={S.card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={S.cardLabel}>Camera Snapshot</div>
          <button
            onClick={() => setSnapTs(Date.now())}
            style={{
              fontSize: 10,
              padding: "3px 10px",
              borderRadius: 6,
              background: "var(--lm-surface)",
              border: "1px solid var(--lm-border)",
              color: "var(--lm-text-dim)",
              cursor: "pointer",
            }}
          >
            Capture
          </button>
        </div>
        <img
          src={`${HW}/camera/snapshot?t=${snapTs}`}
          alt="snapshot"
          style={{
            width: "100%",
            maxHeight: 280,
            objectFit: "contain",
            borderRadius: 8,
            border: "1px solid var(--lm-border)",
            display: "block",
            background: "var(--lm-surface)",
          }}
          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
        />
      </div>
      )}
    </div>
  );
}
