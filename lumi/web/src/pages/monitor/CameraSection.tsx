import { useCallback, useEffect, useState } from "react";
import { S } from "./styles";
import { HW } from "./types";

interface TrackStatus {
  tracking: boolean;
  target: string | null;
  bbox: number[] | null;
  confidence: number | null;
}

export function CameraSection({
  displayTs: _displayTs,
}: {
  displayTs: number;
}) {
  const [snapTs, setSnapTs] = useState(Date.now());
  const [cameraDisabled, setCameraDisabled] = useState(false);
  const [manualOverride, setManualOverride] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [track, setTrack] = useState<TrackStatus>({ tracking: false, target: null, bbox: null, confidence: null });
  const [trackTarget, setTrackTarget] = useState("object");
  const [trackBbox, setTrackBbox] = useState("280,200,80,80");

  const checkStatus = useCallback(async () => {
    try {
      const r = await fetch(`${HW}/camera`).then((x) => x.json());
      setCameraDisabled(!!r.disabled);
      setManualOverride(!!r.manual_override);
    } catch {}
  }, []);

  const fetchTrackStatus = useCallback(async () => {
    try {
      const r = await fetch(`${HW}/servo/track`).then((x) => x.json());
      setTrack({ tracking: !!r.tracking, target: r.target, bbox: r.bbox });
    } catch {}
  }, []);

  // Poll camera state every 5s to stay in sync with auto triggers (scene/emotion)
  useEffect(() => {
    checkStatus();
    fetchTrackStatus();
    const id = setInterval(() => { checkStatus(); fetchTrackStatus(); }, 3000);
    return () => clearInterval(id);
  }, [checkStatus, fetchTrackStatus]);

  const toggleCamera = async () => {
    setToggling(true);
    try {
      await fetch(`${HW}/camera/${cameraDisabled ? "enable" : "disable"}`, { method: "POST" });
      setCameraDisabled(!cameraDisabled);
    } catch {}
    setToggling(false);
  };

  const startTracking = async () => {
    const parts = trackBbox.split(",").map((s) => parseInt(s.trim(), 10));
    if (parts.length !== 4 || parts.some(isNaN)) return;
    try {
      const r = await fetch(`${HW}/servo/track`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bbox: parts, target: trackTarget }),
      }).then((x) => x.json());
      setTrack({ tracking: !!r.tracking, target: r.target, bbox: r.bbox });
    } catch {}
  };

  const stopTracking = async () => {
    try {
      await fetch(`${HW}/servo/track`, { method: "DELETE" });
      setTrack({ tracking: false, target: null, bbox: null, confidence: null });
    } catch {}
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Camera toggle */}
      <div style={S.card}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={S.cardLabel}>Camera</div>
            <div style={{ fontSize: 11, color: "var(--lm-text-muted)" }}>
              {cameraDisabled
                ? manualOverride
                  ? "Disabled by you — face/motion detection paused"
                  : "Auto-disabled (scene/emotion) — face/motion paused"
                : "Active — streaming, face/motion detection running"}
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

      {!cameraDisabled && ( <>
      <div className="lm-grid-2">
        {/* Live camera stream */}
        <div style={S.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={S.cardLabel}>Camera Stream</div>
            <span style={{
              fontSize: 10,
              padding: "2px 7px",
              borderRadius: 4,
              background: track.tracking ? "rgba(52,211,153,0.15)" : "rgba(248,113,113,0.15)",
              color: track.tracking ? "var(--lm-green)" : "var(--lm-red)",
              fontWeight: 700,
              letterSpacing: "0.05em",
            }}>{track.tracking ? `TRACKING: ${track.target || "?"}` : "LIVE"}</span>
          </div>
          <img
            src={`${HW}/camera/stream`}
            alt="camera"
            style={{
              width: "100%",
              borderRadius: 8,
              border: `1px solid ${track.tracking ? "var(--lm-green)" : "var(--lm-border)"}`,
              display: "block",
              background: "var(--lm-surface)",
            }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
          {track.tracking && track.bbox && (
            <div style={{ fontSize: 11, color: "var(--lm-text-muted)", marginTop: 6 }}>
              bbox: [{track.bbox.join(", ")}]
            </div>
          )}
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

      {/* Vision Tracking */}
      <div style={S.card}>
        <div style={S.cardLabel}>Vision Tracking</div>
        <div style={{ fontSize: 11, color: "var(--lm-text-muted)", marginBottom: 10 }}>
          Track any object by bounding box [x, y, w, h] on camera frame
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          <input
            value={trackTarget}
            onChange={(e) => setTrackTarget(e.target.value)}
            placeholder="target label"
            style={{
              flex: 1, minWidth: 100, padding: "5px 8px", borderRadius: 6, fontSize: 12,
              background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
              color: "var(--lm-text)",
            }}
          />
          <input
            value={trackBbox}
            onChange={(e) => setTrackBbox(e.target.value)}
            placeholder="x, y, w, h"
            style={{
              width: 140, padding: "5px 8px", borderRadius: 6, fontSize: 12,
              background: "var(--lm-surface)", border: "1px solid var(--lm-border)",
              color: "var(--lm-text)", fontFamily: "monospace",
            }}
          />
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={startTracking}
            disabled={track.tracking}
            style={{
              padding: "6px 16px", borderRadius: 7, fontSize: 12, fontWeight: 600,
              cursor: track.tracking ? "not-allowed" : "pointer",
              background: "rgba(52,211,153,0.1)",
              border: "1px solid rgba(52,211,153,0.3)",
              color: "var(--lm-green)",
              opacity: track.tracking ? 0.5 : 1,
            }}
          >
            Start
          </button>
          <button
            onClick={stopTracking}
            disabled={!track.tracking}
            style={{
              padding: "6px 16px", borderRadius: 7, fontSize: 12, fontWeight: 600,
              cursor: !track.tracking ? "not-allowed" : "pointer",
              background: "rgba(248,113,113,0.1)",
              border: "1px solid rgba(248,113,113,0.3)",
              color: "var(--lm-red)",
              opacity: !track.tracking ? 0.5 : 1,
            }}
          >
            Stop
          </button>
          <button
            onClick={fetchTrackStatus}
            style={{
              padding: "6px 16px", borderRadius: 7, fontSize: 12, fontWeight: 600,
              cursor: "pointer",
              background: "var(--lm-surface)",
              border: "1px solid var(--lm-border)",
              color: "var(--lm-text-dim)",
            }}
          >
            Status
          </button>
        </div>
        {track.tracking && (
          <div style={{
            marginTop: 10, padding: "6px 10px", borderRadius: 6, fontSize: 11,
            background: "rgba(52,211,153,0.08)", border: "1px solid rgba(52,211,153,0.2)",
            color: "var(--lm-green)", fontFamily: "monospace",
          }}>
            Tracking "{track.target}" — conf: {track.confidence?.toFixed(3) ?? "?"} — bbox: [{track.bbox?.join(", ")}]
          </div>
        )}
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
      </> )}
    </div>
  );
}
