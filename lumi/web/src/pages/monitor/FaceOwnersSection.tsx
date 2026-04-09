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
          <div style={S.cardLabel}>Users</div>
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
            User recognizer unavailable (sensing not started?)
          </div>
        )}

        {!error && data && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontSize: 24, fontWeight: 700, color: "var(--lm-amber)" }}>
              {data.owner_count}
            </span>
            <span style={{ fontSize: 12, color: "var(--lm-text-muted)" }}>
              enrolled user{data.owner_count !== 1 ? "s" : ""}
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
          <div style={{ ...S.cardLabel, marginBottom: 14 }}>Add New User</div>
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
              {enrolling ? "Adding..." : "Add User"}
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
                <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: owner.role === "friend" ? "rgba(96,165,250,0.15)" : "var(--lm-amber-dim)",
                    color: owner.role === "friend" ? "rgb(96,165,250)" : "var(--lm-amber)",
                    fontWeight: 600,
                  }}>
                    {owner.role || "owner"}
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
                  {owner.mood_days && owner.mood_days.length > 0 && (
                    <span style={{
                      fontSize: 10,
                      padding: "2px 7px",
                      borderRadius: 4,
                      background: "rgba(74,222,128,0.15)",
                      color: "rgb(74,222,128)",
                      fontWeight: 600,
                    }}>
                      {owner.mood_days.length} mood day{owner.mood_days.length !== 1 ? "s" : ""}
                    </span>
                  )}
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

              {/* Folder tree */}
              <div style={{
                fontFamily: "monospace",
                fontSize: 11,
                lineHeight: 1.7,
                color: "var(--lm-text-muted)",
              }}>
                {(() => {
                  const items: { name: string; isDir?: boolean; children?: string[] }[] = [];
                  // photos
                  owner.photos.forEach((f) => items.push({ name: f }));
                  // other files
                  owner.files?.filter((f) => !owner.photos.includes(f)).forEach((f) => items.push({ name: f }));
                  // mood dir
                  if (owner.mood_days && owner.mood_days.length > 0) {
                    items.push({ name: "mood/", isDir: true, children: owner.mood_days.map((d) => `${d}.jsonl`) });
                  }
                  return items.map((item, i) => {
                    const isLastTop = i === items.length - 1;
                    const prefix = isLastTop ? "\u2514\u2500\u2500 " : "\u251C\u2500\u2500 ";
                    if (item.isDir) {
                      return (
                        <div key={item.name}>
                          <span style={{ color: "var(--lm-text-dim)" }}>{prefix}</span>
                          <span style={{ color: "rgb(74,222,128)", fontWeight: 600 }}>{item.name}</span>
                          {item.children?.map((child, ci) => {
                            const childPrefix = isLastTop ? "    " : "\u2502   ";
                            const childBranch = ci === (item.children?.length ?? 0) - 1 ? "\u2514\u2500\u2500 " : "\u251C\u2500\u2500 ";
                            return (
                              <div key={child}>
                                <span style={{ color: "var(--lm-text-dim)" }}>{childPrefix}{childBranch}</span>
                                <span>{child}</span>
                              </div>
                            );
                          })}
                        </div>
                      );
                    }
                    const isImg = /\.(jpg|jpeg|png|bmp)$/i.test(item.name);
                    return (
                      <div key={item.name} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span>
                          <span style={{ color: "var(--lm-text-dim)" }}>{prefix}</span>
                          {isImg ? (
                            <span
                              style={{ color: "var(--lm-amber)", cursor: "pointer" }}
                              onClick={() => window.open(`${HW}/face/photo/${owner.label}/${item.name}`, "_blank")}
                            >{item.name}</span>
                          ) : (
                            <span>{item.name}</span>
                          )}
                        </span>
                        {isImg && (
                          <img
                            src={`${HW}/face/photo/${owner.label}/${item.name}`}
                            style={{
                              width: 28,
                              height: 28,
                              objectFit: "cover",
                              borderRadius: 4,
                              border: "1px solid var(--lm-border)",
                            }}
                            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                          />
                        )}
                      </div>
                    );
                  });
                })()}
              </div>
            </div>
          ))}
        </div>
      )}

      {data && data.owners.length === 0 && !showEnroll && (
        <div style={{ ...S.card, textAlign: "center" as const, padding: 32 }}>
          <div style={{ fontSize: 12, color: "var(--lm-text-muted)", fontStyle: "italic" }}>
            No users enrolled yet. Click "+ Enroll" above or send a photo via Telegram.
          </div>
        </div>
      )}
    </div>
  );
}
