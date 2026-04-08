import { useCallback, useEffect, useRef, useState } from "react";
import { S } from "./styles";
import { HW } from "./types";
import type { FaceOwnersDetail } from "./types";

export function FaceOwnersSection() {
  const [data, setData] = useState<FaceOwnersDetail | null>(null);
  const [error, setError] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Enroll form state
  const [showEnroll, setShowEnroll] = useState(false);
  const [enrollName, setEnrollName] = useState("");
  const [enrollRole, setEnrollRole] = useState<"owner" | "friend">("friend");
  const [enrollFile, setEnrollFile] = useState<File | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [enrollError, setEnrollError] = useState("");

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Delete state
  const [deleting, setDeleting] = useState<string | null>(null);

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

  const handleEnroll = async () => {
    if (!enrollFile || !enrollName.trim()) return;
    setEnrolling(true);
    setEnrollError("");
    try {
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = reader.result as string;
          resolve(result.split(",")[1]); // strip "data:image/...;base64,"
        };
        reader.onerror = () => reject(new Error("Failed to read file"));
        reader.readAsDataURL(enrollFile);
      });
      const res = await fetch(`${HW}/face/enroll`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_base64: base64,
          label: enrollName.trim().toLowerCase(),
          role: enrollRole,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      setShowEnroll(false);
      setEnrollName("");
      setEnrollFile(null);
      setEnrollRole("friend");
      if (fileInputRef.current) fileInputRef.current.value = "";
      refresh();
    } catch (e) {
      setEnrollError((e as Error).message);
    } finally {
      setEnrolling(false);
    }
  };

  const handleRemove = async (label: string) => {
    if (!confirm(`Remove "${label}" and all their photos?`)) return;
    setDeleting(label);
    try {
      await fetch(`${HW}/face/remove`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      });
      refresh();
    } catch {
      // ignore
    } finally {
      setDeleting(null);
    }
  };

  const inputStyle: React.CSSProperties = {
    fontSize: 12,
    padding: "6px 10px",
    borderRadius: 6,
    background: "var(--lm-surface)",
    border: "1px solid var(--lm-border)",
    color: "var(--lm-text)",
    outline: "none",
    width: "100%",
  };

  const btnStyle: React.CSSProperties = {
    fontSize: 10,
    padding: "4px 12px",
    borderRadius: 6,
    border: "1px solid var(--lm-border)",
    cursor: "pointer",
    fontWeight: 600,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Summary */}
      <div style={S.card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={S.cardLabel}>Face Recognition</div>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              onClick={() => setShowEnroll(!showEnroll)}
              style={{
                ...btnStyle,
                background: showEnroll ? "var(--lm-amber-dim)" : "var(--lm-surface)",
                color: showEnroll ? "var(--lm-amber)" : "var(--lm-text-dim)",
              }}
            >
              + Enroll
            </button>
            <button
              onClick={refresh}
              style={{
                ...btnStyle,
                background: "var(--lm-surface)",
                color: "var(--lm-text-dim)",
              }}
            >
              Refresh
            </button>
          </div>
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

      {/* Enroll form */}
      {showEnroll && (
        <div style={S.card}>
          <div style={{ ...S.cardLabel, marginBottom: 14 }}>Enroll New Face</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <input
              type="text"
              placeholder="Name"
              value={enrollName}
              onChange={(e) => setEnrollName(e.target.value)}
              style={inputStyle}
            />
            <div style={{ display: "flex", gap: 8 }}>
              {(["owner", "friend"] as const).map((r) => (
                <button
                  key={r}
                  onClick={() => setEnrollRole(r)}
                  style={{
                    ...btnStyle,
                    flex: 1,
                    background: enrollRole === r
                      ? (r === "owner" ? "var(--lm-amber-dim)" : "rgba(96,165,250,0.15)")
                      : "var(--lm-surface)",
                    color: enrollRole === r
                      ? (r === "owner" ? "var(--lm-amber)" : "rgb(96,165,250)")
                      : "var(--lm-text-muted)",
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={(e) => setEnrollFile(e.target.files?.[0] ?? null)}
              style={{ ...inputStyle, padding: "4px 6px" }}
            />
            {enrollError && (
              <div style={{ fontSize: 11, color: "var(--lm-red)" }}>{enrollError}</div>
            )}
            <button
              onClick={handleEnroll}
              disabled={enrolling || !enrollFile || !enrollName.trim()}
              style={{
                ...btnStyle,
                padding: "7px 14px",
                fontSize: 12,
                background: enrolling || !enrollFile || !enrollName.trim()
                  ? "var(--lm-surface)"
                  : "var(--lm-amber-dim)",
                color: enrolling || !enrollFile || !enrollName.trim()
                  ? "var(--lm-text-muted)"
                  : "var(--lm-amber)",
                cursor: enrolling || !enrollFile || !enrollName.trim() ? "not-allowed" : "pointer",
              }}
            >
              {enrolling ? "Enrolling..." : "Enroll Face"}
            </button>
          </div>
        </div>
      )}

      {/* Person cards */}
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
                  <button
                    onClick={() => handleRemove(owner.label)}
                    disabled={deleting === owner.label}
                    style={{
                      ...btnStyle,
                      padding: "2px 7px",
                      background: "rgba(239,68,68,0.1)",
                      color: "rgb(239,68,68)",
                      border: "1px solid rgba(239,68,68,0.2)",
                      cursor: deleting === owner.label ? "not-allowed" : "pointer",
                      opacity: deleting === owner.label ? 0.5 : 1,
                    }}
                  >
                    {deleting === owner.label ? "..." : "Remove"}
                  </button>
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

      {data && data.owners.length === 0 && !showEnroll && (
        <div style={{ ...S.card, textAlign: "center" as const, padding: 32 }}>
          <div style={{ fontSize: 12, color: "var(--lm-text-muted)", fontStyle: "italic" }}>
            No faces enrolled yet. Click "+ Enroll" above or send a photo via Telegram.
          </div>
        </div>
      )}
    </div>
  );
}
