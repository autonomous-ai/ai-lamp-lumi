import http from "http";

const EMOTION_URL = "http://127.0.0.1:5001/emotion";

function httpPost(url: string, body: string): Promise<void> {
  return new Promise((resolve) => {
    const req = http.request(
      url,
      { method: "POST", headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } },
      () => resolve()
    );
    req.on("error", () => resolve()); // fail silently
    req.write(body);
    req.end();
  });
}

const handler = async (event: any): Promise<void> => {
  if (event.type !== "message" || event.action !== "preprocessed") return;

  const ctx = event.context;
  const text: string = ctx?.bodyForAgent ?? ctx?.body ?? "";

  // Skip sensing events — they have their own defined emotion reactions in SOUL.md
  if (text.startsWith("[sensing:")) return;

  // Skip empty messages
  if (!text.trim()) return;

  await httpPost(EMOTION_URL, JSON.stringify({ emotion: "listening", intensity: 0.8 }));
};

export default handler;
