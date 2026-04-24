import { useCallback, useEffect, useRef, useState } from "react";
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
  const [trackBbox, setTrackBbox] = useState("");

  // Gate the MJPEG stream on tab visibility. <img src="/camera/stream">
  // holds one persistent HTTP/1.1 connection open for as long as the
  // element is mounted — if the tab is backgrounded or the component
  // unmounts, keeping it alive steals one of Chrome's 6 per-origin
  // connection slots and also wastes Pi bandwidth.
  const [streamActive, setStreamActive] = useState(!document.hidden);
  useEffect(() => {
    const onVis = () => setStreamActive(!document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  // In-flight guards — skip a scheduled poll if the previous request for
  // the same endpoint hasn't returned yet. Without this, every 3s tick
  // started a new fetch even if the Pi was slow, and pending fetches
  // piled up against Chrome's 6-connection-per-origin cap until the
  // MJPEG stream and fresh fetches starved.
  const checkInFlight = useRef(false);
  const trackInFlight = useRef(false);

  // Fetch with hard timeout via AbortController. Network stalls without
  // this leave fetches "pending" forever and consume connection slots.
  const fetchWithTimeout = useCallback(async (url: string, init: RequestInit = {}, timeoutMs = 4000) => {
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), timeoutMs);
    try {
      return await fetch(url, { ...init, signal: ac.signal });
    } finally {
      clearTimeout(timer);
    }
  }, []);

  const checkStatus = useCallback(async () => {
    if (checkInFlight.current) return;
    checkInFlight.current = true;
    try {
      const r = await fetchWithTimeout(`${HW}/camera`).then((x) => x.json());
      setCameraDisabled(!!r.disabled);
      setManualOverride(!!r.manual_override);
    } catch {} finally {
      checkInFlight.current = false;
    }
  }, [fetchWithTimeout]);

  const fetchTrackStatus = useCallback(async () => {
    if (trackInFlight.current) return;
    trackInFlight.current = true;
    try {
      const r = await fetchWithTimeout(`${HW}/servo/track`).then((x) => x.json());
      setTrack({ tracking: !!r.tracking, target: r.target, bbox: r.bbox, confidence: r.confidence ?? null });
    } catch {} finally {
      trackInFlight.current = false;
    }
  }, [fetchWithTimeout]);

  // Poll camera + track state every 3s. Pauses while the tab is hidden
  // so a backgrounded tab doesn't keep hammering the Pi.
  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (id !== null) return;
      checkStatus();
      fetchTrackStatus();
      id = setInterval(() => { checkStatus(); fetchTrackStatus(); }, 3000);
    };
    const stop = () => {
      if (id !== null) { clearInterval(id); id = null; }
    };
    const onVisibility = () => {
      if (document.hidden) stop(); else start();
    };
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
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
    // Split on commas so the user can enter synonyms as "cup, mug, coffee cup".
    // A single label with no commas is sent as a plain string for readability
    // in the request body; multiple labels are sent as an array.
    const labels = trackTarget.split(",").map((s) => s.trim()).filter(Boolean);
    const body: Record<string, unknown> = {};
    if (labels.length === 1) body.target = labels[0];
    else if (labels.length > 1) body.target = labels;
    if (trackBbox.trim()) {
      const parts = trackBbox.split(",").map((s) => parseInt(s.trim(), 10));
      if (parts.length === 4 && !parts.some(isNaN)) {
        body.bbox = parts;
      }
    }
    if (!body.target && !body.bbox) return;
    try {
      const r = await fetch(`${HW}/servo/track`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then((x) => x.json());
      setTrack({ tracking: !!r.tracking, target: r.target, bbox: r.bbox, confidence: r.confidence ?? null });
    } catch {}
  };

  const stopTracking = async () => {
    try {
      await fetch(`${HW}/servo/track/stop`, { method: "POST" });
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
          {streamActive ? (
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
          ) : (
            <div style={{
              width: "100%",
              aspectRatio: "4 / 3",
              borderRadius: 8,
              border: `1px solid var(--lm-border)`,
              background: "var(--lm-surface)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 11,
              color: "var(--lm-text-muted)",
            }}>Stream paused (tab hidden)</div>
          )}
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
          Enter one label or several comma-separated (sent as an array of candidates). Optional bbox [x, y, w, h] skips YOLO detection.
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          <input
            value={trackTarget}
            onChange={(e) => setTrackTarget(e.target.value)}
            placeholder="cup, mug, coffee cup"
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
