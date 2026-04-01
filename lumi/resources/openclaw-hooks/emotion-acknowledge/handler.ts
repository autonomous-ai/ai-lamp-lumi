const EMOTION_URL = "http://127.0.0.1:5001/emotion";

const handler = async (event: any): Promise<void> => {
  if (event.type !== "message" || event.action !== "preprocessed") return;

  const ctx = event.context;
  const text: string = ctx?.bodyForAgent ?? ctx?.body ?? "";

  // Skip sensing events — they have their own defined emotion reactions
  if (text.startsWith("[sensing:")) return;

  // Skip empty messages
  if (!text.trim()) return;

  try {
    await fetch(EMOTION_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ emotion: "listening", intensity: 0.8 }),
    });
  } catch {
    // fail silently — never block message delivery
  }
};

export default handler;
