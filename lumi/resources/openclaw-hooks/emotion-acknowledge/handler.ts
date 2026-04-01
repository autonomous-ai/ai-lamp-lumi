import http from "http";

const handler = async (event: any): Promise<void> => {
  if (event.type !== "message" || event.action !== "preprocessed") return;

  const ctx = event.context;
  const text: string = ctx?.bodyForAgent ?? ctx?.body ?? "";

  // Skip sensing events — they have their own defined emotion reactions
  if (text.startsWith("[sensing:") || !text.trim()) return;

  const req = http.request({
    hostname: "127.0.0.1",
    port: 5001,
    path: "/emotion",
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  req.on("error", () => {});
  req.write(JSON.stringify({ emotion: "thinking", intensity: 0.7 }));
  req.end();
};

export default handler;
