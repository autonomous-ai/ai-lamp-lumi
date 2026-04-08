import { useCallback, useEffect, useRef, useState } from "react";
import { S } from "./styles";
import { HW } from "./types";
import type { FaceOwnersDetail } from "./types";

export function FaceOwnersSection() {
  const [data, setData] = useState<FaceOwnersDetail | null>(null);
  const [error, setError] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const r = await fetch(`${HW}/face/owners`, { signal: ctrl.signal }).then((x) => x.json());
      if (ctrl.signal.aborted) return;
      setData({ owner_count: r.enrolled_count ?? r.owner_count ?? 0, owners: r.persons ?? r.owners ?? [] });
      setError(false);
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setError(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => {
      clearInterval(t);
      abortRef.current?.abort();
    };
  }, [refresh]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Summary */}
      <div style={S.card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={S.cardLabel}>Face Recognition</div>
          <button
            onClick={refresh}
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
            Refresh
          </button>
        </div>

        {error && (
          <div style={{ fontSize: 12, color: "var(--lm-red)" }}>
            Face recognizer unavailable (sensing not started?)
          </div>
        )}

        {!error && data && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontSize: 24, fontWeight: 700, color: "var(--lm-amber)" }}>
              {data.owner_count}
            </span>
            <span style={{ fontSize: 12, color: "var(--lm-text-muted)" }}>
              enrolled face{data.owner_count !== 1 ? "s" : ""}
            </span>
          </div>
        )}

        {!error && !data && (
          <div style={{ fontSize: 12, color: "var(--lm-text-muted)" }}>Loading...</div>
        )}
      </div>

      {/* Owner cards */}
      {data && data.owners.length > 0 && (
        <div className="lm-grid-2">
          {data.owners.map((owner) => (
            <div key={owner.label} style={S.card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <div style={{
                  fontSize: 14,
                  fontWeight: 700,
                  color: "var(--lm-amber)",
                  textTransform: "capitalize",
                }}>
                  {owner.label}
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <span style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: owner.role === "friend" ? "rgba(96,165,250,0.15)" : "var(--lm-amber-dim)",
                    color: owner.role === "friend" ? "rgb(96,165,250)" : "var(--lm-amber)",
                    fontWeight: 600,
                  }}>
                    {owner.role === "friend" ? "friend" : "owner"}
                  </span>
                  <span style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: "var(--lm-amber-dim)",
                    color: "var(--lm-amber)",
                    fontWeight: 600,
                  }}>
                    {owner.photo_count} photo{owner.photo_count !== 1 ? "s" : ""}
                  </span>
                </div>
              </div>
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(80px, 1fr))",
                gap: 8,
              }}>
                {owner.photos.map((filename) => (
                  <img
                    key={filename}
                    src={`${HW}/face/photo/${owner.label}/${filename}`}
                    alt={`${owner.label} - ${filename}`}
                    style={{
                      width: "100%",
                      aspectRatio: "1",
                      objectFit: "cover",
                      borderRadius: 8,
                      border: "1px solid var(--lm-border)",
                      background: "var(--lm-surface)",
                      cursor: "pointer",
                    }}
                    onClick={() => window.open(`${HW}/face/photo/${owner.label}/${filename}`, "_blank")}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {data && data.owners.length === 0 && (
        <div style={{ ...S.card, textAlign: "center" as const, padding: 32 }}>
          <div style={{ fontSize: 12, color: "var(--lm-text-muted)", fontStyle: "italic" }}>
            No faces enrolled yet. Send a photo via Telegram with "this is [name]" or "remember my face" to enroll.
          </div>
        </div>
      )}
    </div>
  );
}
