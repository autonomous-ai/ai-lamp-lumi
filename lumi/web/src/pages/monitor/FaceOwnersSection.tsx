import { useCallback, useEffect, useRef, useState } from "react";
import { S } from "./styles";
import { HW } from "./types";
import type { FaceOwnersDetail } from "./types";

interface AudioHistoryEntry {
  ts: number;
  date: string;
  hour: number;
  query: string;
  title: string;
  duration_s: number;
  stopped_by: string;
  person: string;
}

interface CooldownEntry {
  person_id: string;
  kind: string;
  last_seen_ago: number;
  cooldown_remaining: number;
  cooldown_total: number;
}
interface CooldownState {
  owners: CooldownEntry[];
  strangers: CooldownEntry[];
  owners_forget_s: number;
  strangers_forget_s: number;
}

function fmtCountdown(s: number): string {
  if (s <= 0) return "ready";
  if (s < 60) return `${Math.ceil(s)}s`;
  const m = Math.floor(s / 60);
  const sec = Math.ceil(s % 60);
  return sec > 0 ? `${m}m ${sec}s` : `${m}m`;
}

export function FaceOwnersSection() {
  const [data, setData] = useState<FaceOwnersDetail | null>(null);
  const [error, setError] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Cooldown state
  const [cooldowns, setCooldowns] = useState<CooldownState | null>(null);
  const [cdError, setCdError] = useState(false);
  const [resetting, setResetting] = useState(false);

  // Enroll form state
  const [showEnroll, setShowEnroll] = useState(false);
  const [enrollName, setEnrollName] = useState("");
  const [enrollTgUsername, setEnrollTgUsername] = useState("");
  const [enrollTgId, setEnrollTgId] = useState("");
  const [enrollFile, setEnrollFile] = useState<File | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [enrollError, setEnrollError] = useState("");

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Delete state
  const [deleting, setDeleting] = useState<string | null>(null);

  // Audio history per user: { "gray": [...entries] }
  const [audioHistory, setAudioHistory] = useState<Record<string, AudioHistoryEntry[]>>({});

  // Folder toggle state: "label:mood" => expanded
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // File preview state: { label, path, content, loading }
  const [preview, setPreview] = useState<{ label: string; path: string; content: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const toggleDir = (key: string) => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  const fetchAudioHistory = useCallback(async (person: string) => {
    try {
      const r = await fetch(`${HW}/audio/history?person=${encodeURIComponent(person)}&last=20`);
      if (!r.ok) return;
      const json = await r.json();
      setAudioHistory((prev) => ({ ...prev, [person]: json.entries ?? [] }));
    } catch {
      // ignore
    }
  }, []);

  const openFile = async (label: string, filepath: string) => {
    const isImg = /\.(jpg|jpeg|png|bmp)$/i.test(filepath);
    if (isImg) {
      window.open(`${HW}/face/photo/${label}/${filepath}`, "_blank");
      return;
    }
    // Already showing this file? close it
    if (preview?.label === label && preview?.path === filepath) {
      setPreview(null);
      return;
    }
    setPreviewLoading(true);
    try {
      const res = await fetch(`${HW}/face/file/${label}/${filepath}`);
      const text = await res.text();
      setPreview({ label, path: filepath, content: text });
    } catch {
      setPreview({ label, path: filepath, content: "(failed to load)" });
    } finally {
      setPreviewLoading(false);
    }
  };

  const refresh = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const r = await fetch(`${HW}/face/owners`, { signal: ctrl.signal }).then((x) => x.json());
      if (ctrl.signal.aborted) return;
      setData({ enrolled_count: r.enrolled_count ?? 0, persons: r.persons ?? [] });
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

  // Cooldown polling — every 2s for live countdown
  const refreshCooldowns = useCallback(async () => {
    try {
      const r = await fetch(`${HW}/face/cooldowns`);
      if (!r.ok) throw new Error();
      setCooldowns(await r.json());
      setCdError(false);
    } catch {
      setCdError(true);
    }
  }, []);

  useEffect(() => {
    refreshCooldowns();
    const t = setInterval(refreshCooldowns, 2000);
    return () => clearInterval(t);
  }, [refreshCooldowns]);

  const handleResetCooldowns = async () => {
    setResetting(true);
    try {
      await fetch(`${HW}/face/cooldowns/reset`, { method: "POST" });
      await refreshCooldowns();
    } catch {
      // ignore
    } finally {
      setResetting(false);
    }
  };

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
          ...(enrollTgUsername.trim() ? { telegram_username: enrollTgUsername.trim() } : {}),
          ...(enrollTgId.trim() ? { telegram_id: enrollTgId.trim() } : {}),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      setShowEnroll(false);
      setEnrollName("");
      setEnrollTgUsername("");
      setEnrollTgId("");
      setEnrollFile(null);
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

  const allCooldownEntries = [
    ...(cooldowns?.owners ?? []),
    ...(cooldowns?.strangers ?? []),
  ];
  const hasActiveCooldowns = allCooldownEntries.some((e) => e.cooldown_remaining > 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Face Recognition Cooldowns */}
      <div style={S.card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={S.cardLabel}>Face Recognition</div>
          <button
            onClick={handleResetCooldowns}
            disabled={resetting || !hasActiveCooldowns}
            style={{
              fontSize: 10,
              padding: "4px 12px",
              borderRadius: 6,
              border: "1px solid var(--lm-border)",
              cursor: resetting || !hasActiveCooldowns ? "not-allowed" : "pointer",
              fontWeight: 600,
              background: hasActiveCooldowns ? "var(--lm-amber-dim)" : "var(--lm-surface)",
              color: hasActiveCooldowns ? "var(--lm-amber)" : "var(--lm-text-muted)",
              opacity: resetting ? 0.5 : 1,
            }}
          >
            {resetting ? "Resetting..." : "Reset Cooldowns"}
          </button>
        </div>

        {cdError && (
          <div style={{ fontSize: 12, color: "var(--lm-text-muted)", fontStyle: "italic" }}>
            Cooldown info unavailable
          </div>
        )}

        {!cdError && allCooldownEntries.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--lm-text-muted)", fontStyle: "italic" }}>
            No faces currently tracked
          </div>
        )}

        {!cdError && allCooldownEntries.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {allCooldownEntries.map((entry) => {
              const pct = entry.cooldown_total > 0
                ? (entry.cooldown_remaining / entry.cooldown_total) * 100
                : 0;
              const kindColor =
                entry.kind === "stranger" ? "rgb(239,68,68)"
                : "rgb(96,165,250)";
              return (
                <div key={`${entry.kind}-${entry.person_id}`} style={{
                  padding: "8px 12px",
                  borderRadius: 8,
                  background: "var(--lm-surface)",
                  border: "1px solid var(--lm-border)",
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{
                        fontSize: 12,
                        fontWeight: 600,
                        color: kindColor,
                        textTransform: "capitalize",
                      }}>
                        {entry.person_id}
                      </span>
                      <span style={{
                        fontSize: 9,
                        padding: "1px 6px",
                        borderRadius: 4,
                        background: entry.kind === "stranger" ? "rgba(239,68,68,0.1)" : "rgba(96,165,250,0.15)",
                        color: kindColor,
                        fontWeight: 600,
                      }}>
                        {entry.kind}
                      </span>
                    </div>
                    <span style={{
                      fontSize: 11,
                      fontWeight: 600,
                      fontFamily: "monospace",
                      color: entry.cooldown_remaining > 0 ? "var(--lm-text)" : "rgb(74,222,128)",
                    }}>
                      {fmtCountdown(entry.cooldown_remaining)}
                    </span>
                  </div>
                  {/* Progress bar */}
                  <div style={{
                    height: 4,
                    borderRadius: 2,
                    background: "var(--lm-border)",
                    overflow: "hidden",
                  }}>
                    <div style={{
                      height: "100%",
                      width: `${pct}%`,
                      borderRadius: 2,
                      background: kindColor,
                      transition: "width 1.5s linear",
                    }} />
                  </div>
                  <div style={{ fontSize: 9, color: "var(--lm-text-muted)", marginTop: 4 }}>
                    seen {Math.round(entry.last_seen_ago)}s ago · next event in {fmtCountdown(entry.cooldown_remaining)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

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
              {data.enrolled_count}
            </span>
            <span style={{ fontSize: 12, color: "var(--lm-text-muted)" }}>
              enrolled user{data.enrolled_count !== 1 ? "s" : ""}
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
            <input
              type="text"
              placeholder="Telegram username (optional)"
              value={enrollTgUsername}
              onChange={(e) => setEnrollTgUsername(e.target.value)}
              style={inputStyle}
            />
            <input
              type="text"
              placeholder="Telegram ID (optional)"
              value={enrollTgId}
              onChange={(e) => setEnrollTgId(e.target.value)}
              style={inputStyle}
            />
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
      {data && data.persons.length > 0 && (
        <div className="lm-grid-2">
          {data.persons.map((person) => (
            <div key={person.label} style={S.card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <div>
                  <div style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: "var(--lm-amber)",
                    textTransform: "capitalize",
                  }}>
                    {person.label}
                  </div>
                  {(person.telegram_username || person.telegram_id) && (
                    <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginTop: 2 }}>
                      {person.telegram_username && <span>@{person.telegram_username}</span>}
                      {person.telegram_username && person.telegram_id && <span> · </span>}
                      {person.telegram_id && <span>ID: {person.telegram_id}</span>}
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: "var(--lm-amber-dim)",
                    color: "var(--lm-amber)",
                    fontWeight: 600,
                  }}>
                    {person.photo_count} photo{person.photo_count !== 1 ? "s" : ""}
                  </span>
                  {person.mood_days && person.mood_days.length > 0 && (
                    <span style={{
                      fontSize: 10,
                      padding: "2px 7px",
                      borderRadius: 4,
                      background: "rgba(74,222,128,0.15)",
                      color: "rgb(74,222,128)",
                      fontWeight: 600,
                    }}>
                      {person.mood_days.length} mood day{person.mood_days.length !== 1 ? "s" : ""}
                    </span>
                  )}
                  <button
                    onClick={() => handleRemove(person.label)}
                    disabled={deleting === person.label}
                    style={{
                      ...btnStyle,
                      padding: "2px 7px",
                      background: "rgba(239,68,68,0.1)",
                      color: "rgb(239,68,68)",
                      border: "1px solid rgba(239,68,68,0.2)",
                      cursor: deleting === person.label ? "not-allowed" : "pointer",
                      opacity: deleting === person.label ? 0.5 : 1,
                    }}
                  >
                    {deleting === person.label ? "..." : "Remove"}
                  </button>
                </div>
              </div>

              {/* Audio history */}
              {(() => {
                const histKey = `${person.label}:audio`;
                const isOpen = expanded[histKey] ?? false;
                const entries = audioHistory[person.label];
                return (
                  <div style={{ marginBottom: 8 }}>
                    <span
                      style={{
                        cursor: "pointer",
                        fontSize: 11,
                        fontFamily: "monospace",
                        color: "rgb(96,165,250)",
                        fontWeight: 600,
                      }}
                      onClick={() => {
                        toggleDir(histKey);
                        if (!entries) fetchAudioHistory(person.label);
                      }}
                    >
                      {isOpen ? "▾" : "▸"} ♫ audio history
                      {entries && <span style={{ fontWeight: 400, color: "var(--lm-text-muted)" }}> ({entries.length})</span>}
                    </span>
                    {isOpen && entries && entries.length === 0 && (
                      <div style={{ fontSize: 10, color: "var(--lm-text-muted)", fontStyle: "italic", marginLeft: 16, marginTop: 4 }}>
                        No listening history yet
                      </div>
                    )}
                    {isOpen && entries && entries.length > 0 && (
                      <div style={{
                        marginTop: 6,
                        maxHeight: 180,
                        overflowY: "auto",
                        display: "flex",
                        flexDirection: "column",
                        gap: 4,
                      }}>
                        {entries.slice().reverse().map((e, i) => {
                          const time = new Date(e.ts * 1000);
                          const hh = time.getHours().toString().padStart(2, "0");
                          const mm = time.getMinutes().toString().padStart(2, "0");
                          const dur = e.duration_s < 60
                            ? `${Math.round(e.duration_s)}s`
                            : `${Math.floor(e.duration_s / 60)}m${Math.round(e.duration_s % 60)}s`;
                          const stopColor = e.stopped_by === "user" ? "var(--lm-amber)"
                            : e.stopped_by === "end" ? "rgb(74,222,128)"
                            : "var(--lm-text-muted)";
                          return (
                            <div key={i} style={{
                              fontSize: 10,
                              fontFamily: "monospace",
                              padding: "4px 8px",
                              borderRadius: 4,
                              background: "var(--lm-surface)",
                              border: "1px solid var(--lm-border)",
                              lineHeight: 1.5,
                            }}>
                              <div style={{ display: "flex", justifyContent: "space-between" }}>
                                <span style={{ color: "var(--lm-text)" }}>{e.title || e.query}</span>
                                <span style={{ color: "var(--lm-text-muted)", whiteSpace: "nowrap", marginLeft: 8 }}>{hh}:{mm}</span>
                              </div>
                              <div style={{ display: "flex", gap: 8, color: "var(--lm-text-muted)", marginTop: 2 }}>
                                <span>{dur}</span>
                                <span style={{ color: stopColor }}>{e.stopped_by}</span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {isOpen && !entries && (
                      <div style={{ fontSize: 10, color: "var(--lm-text-muted)", marginLeft: 16, marginTop: 4 }}>Loading...</div>
                    )}
                  </div>
                );
              })()}

              {/* Folder tree */}
              <div style={{
                fontFamily: "monospace",
                fontSize: 11,
                lineHeight: 1.7,
                color: "var(--lm-text-muted)",
              }}>
                {(() => {
                  const items: { name: string; isDir?: boolean; dirKey?: string; children?: string[]; filePath?: string }[] = [];
                  person.photos.forEach((f) => items.push({ name: f, filePath: f }));
                  person.files?.filter((f) => !person.photos.includes(f)).forEach((f) => items.push({ name: f, filePath: f }));
                  if (person.mood_days && person.mood_days.length > 0) {
                    items.push({ name: "mood", isDir: true, dirKey: `${person.label}:mood`, children: person.mood_days.map((d) => `${d}.jsonl`) });
                  }
                  return items.map((item, i) => {
                    const isLastTop = i === items.length - 1;
                    const prefix = isLastTop ? "\u2514\u2500\u2500 " : "\u251C\u2500\u2500 ";
                    if (item.isDir && item.dirKey) {
                      const isOpen = expanded[item.dirKey] ?? false;
                      return (
                        <div key={item.name}>
                          <span
                            style={{ cursor: "pointer" }}
                            onClick={() => toggleDir(item.dirKey!)}
                          >
                            <span style={{ color: "var(--lm-text-dim)" }}>{prefix}</span>
                            <span style={{ color: "rgb(74,222,128)" }}>{isOpen ? "\u25BE" : "\u25B8"}</span>
                            <span style={{ color: "rgb(74,222,128)", fontWeight: 600 }}> {item.name}/</span>
                          </span>
                          {isOpen && item.children?.map((child, ci) => {
                            const childPrefix = isLastTop ? "    " : "\u2502   ";
                            const childBranch = ci === (item.children?.length ?? 0) - 1 ? "\u2514\u2500\u2500 " : "\u251C\u2500\u2500 ";
                            const childPath = `${item.name}/${child}`;
                            const isActive = preview?.label === person.label && preview?.path === childPath;
                            return (
                              <div key={child}>
                                <span
                                  style={{ cursor: "pointer" }}
                                  onClick={() => openFile(person.label, childPath)}
                                >
                                  <span style={{ color: "var(--lm-text-dim)" }}>{childPrefix}{childBranch}</span>
                                  <span style={{
                                    color: isActive ? "var(--lm-amber)" : "inherit",
                                    textDecoration: "underline",
                                    textDecorationStyle: "dotted" as const,
                                    textUnderlineOffset: 3,
                                  }}>{child}</span>
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      );
                    }
                    const isImg = /\.(jpg|jpeg|png|bmp)$/i.test(item.name);
                    const isActive = preview?.label === person.label && preview?.path === item.filePath;
                    return (
                      <div key={item.name} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span
                          style={{ cursor: "pointer" }}
                          onClick={() => openFile(person.label, item.filePath!)}
                        >
                          <span style={{ color: "var(--lm-text-dim)" }}>{prefix}</span>
                          <span style={{
                            color: isImg ? "var(--lm-amber)" : (isActive ? "var(--lm-amber)" : "inherit"),
                            textDecoration: "underline",
                            textDecorationStyle: "dotted" as const,
                            textUnderlineOffset: 3,
                          }}>{item.name}</span>
                        </span>
                        {isImg && (
                          <img
                            src={`${HW}/face/photo/${person.label}/${item.name}`}
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

              {/* File preview */}
              {preview && preview.label === person.label && (
                <div style={{
                  marginTop: 8,
                  padding: "8px 10px",
                  borderRadius: 6,
                  background: "var(--lm-surface)",
                  border: "1px solid var(--lm-border)",
                  fontSize: 10,
                  fontFamily: "monospace",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-all",
                  maxHeight: 200,
                  overflowY: "auto",
                  color: "var(--lm-text)",
                  position: "relative",
                }}>
                  <div style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 6,
                    paddingBottom: 4,
                    borderBottom: "1px solid var(--lm-border)",
                  }}>
                    <span style={{ color: "var(--lm-amber)", fontWeight: 600 }}>{preview.path}</span>
                    <span
                      style={{ cursor: "pointer", color: "var(--lm-text-muted)", fontSize: 12 }}
                      onClick={() => setPreview(null)}
                    >x</span>
                  </div>
                  {previewLoading ? "Loading..." : preview.content}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {data && data.persons.length === 0 && !showEnroll && (
        <div style={{ ...S.card, textAlign: "center" as const, padding: 32 }}>
          <div style={{ fontSize: 12, color: "var(--lm-text-muted)", fontStyle: "italic" }}>
            No users enrolled yet. Click "+ Enroll" above or send a photo via Telegram.
          </div>
        </div>
      )}
    </div>
  );
}
