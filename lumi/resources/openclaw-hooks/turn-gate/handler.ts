import http from "http";

const handler = async (event: any): Promise<void> => {
  if (event.type !== "message" || event.action !== "preprocessed") return;

  const ctx = event.context;
  const text: string = ctx?.bodyForAgent ?? ctx?.body ?? "";

  // Skip sensing events — Lumi sets busy proactively in sendChat for those
  if (text.startsWith("[sensing:") || !text.trim()) return;

  // Skip OpenClaw heartbeat / memory-flush turns. These run with target=none
  // (no channel to reply to) and never emit lifecycle.end SSE, so if we set
  // busy=true here Lumi gets stuck for the full 5-min busyTTL. Field locations
  // are checked defensively because the runtime schema isn't pinned here.
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
