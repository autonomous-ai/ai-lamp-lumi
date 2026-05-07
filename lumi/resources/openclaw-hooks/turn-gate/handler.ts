import http from "http";

const handler = async (event: any): Promise<void> => {
  if (event.type !== "message" || event.action !== "preprocessed") return;

  const ctx = event.context;
  const text: string = ctx?.bodyForAgent ?? ctx?.body ?? "";

  // Skip sensing events — Lumi sets busy proactively in sendChat for those
  if (text.startsWith("[sensing:") || !text.trim()) return;

  // Skip OpenClaw heartbeat / memory-flush / system turns. Verified field
  // from runtime log: `messageChannel=heartbeat` (vs `webchat`/`telegram`).
  // These runs do NOT emit lifecycle.end SSE, so if we set busy=true here
  // Lumi wedges for the full 5-min busyTTL (see docs/debug/busy-stuck.md).
  // Defensive check covers nearby field names + the `target=none` doc
  // reference in case it appears on some events.
  const channel =
    ctx?.messageChannel ??
    ctx?.channel ??
    ctx?.metadata?.messageChannel ??
    ctx?.metadata?.channel ??
    event?.messageChannel ??
    event?.channel;
  if (channel === "heartbeat" || channel === "system" || channel === "internal") return;

  const target =
    ctx?.target ??
    ctx?.metadata?.target ??
    ctx?.turn?.target ??
    event?.target;
  if (target === "none") return;

  const isHeartbeat =
    ctx?.isHeartbeat === true ||
    ctx?.heartbeat === true ||
    ctx?.metadata?.isHeartbeat === true ||
    ctx?.metadata?.heartbeat === true ||
    event?.isHeartbeat === true;
  if (isHeartbeat) return;

  const req = http.request({
    hostname: "127.0.0.1",
    port: 5000,
    path: "/api/openclaw/busy",
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  req.on("error", () => {});
  req.end();
};

export default handler;
