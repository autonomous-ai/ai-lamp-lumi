import http from "http";
import fs from "fs";
import path from "path";
import os from "os";

const CAMERA_SNAPSHOT_URL = "http://127.0.0.1:5001/camera/snapshot";
const CAMERA_INFO_URL = "http://127.0.0.1:5001/camera";

function httpGet(url: string): Promise<{ statusCode: number; body: Buffer }> {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk: Buffer) => chunks.push(chunk));
        res.on("end", () =>
          resolve({ statusCode: res.statusCode ?? 0, body: Buffer.concat(chunks) })
        );
      })
      .on("error", reject);
  });
}

const handler = async (event: any): Promise<void> => {
  if (event.type !== "message" || event.action !== "preprocessed") return;

  const ctx = event.context;
  const text: string = ctx?.bodyForAgent ?? ctx?.body ?? "";

  try {
    // Check camera availability
    const infoRes = await httpGet(CAMERA_INFO_URL);
    if (infoRes.statusCode !== 200) return;

    const info = JSON.parse(infoRes.body.toString()) as {
      available: boolean;
      width: number | null;
      height: number | null;
    };

    if (!info.available) {
      ctx.bodyForAgent = text + "\n\n[Camera is not available — no camera connected to the lamp]";
      return;
    }

    // Fetch snapshot
    const snapRes = await httpGet(CAMERA_SNAPSHOT_URL);
    if (snapRes.statusCode !== 200) return;

    // Save to temp file
    const tmpPath = path.join(os.tmpdir(), `lumi-camera-${Date.now()}.jpg`);
    fs.writeFileSync(tmpPath, snapRes.body);

    // Append camera snapshot alongside any existing user-sent image
    const existingPaths: string[] = ctx.mediaPaths ?? (ctx.mediaPath ? [ctx.mediaPath] : []);
    const existingTypes: string[] = ctx.mediaTypes ?? (ctx.mediaType ? [ctx.mediaType] : []);

    ctx.mediaPaths = [...existingPaths, tmpPath];
    ctx.mediaTypes = [...existingTypes, "image/jpeg"];

    const note = existingPaths.length > 0
      ? "\n\n[Camera snapshot attached alongside your image]"
      : "\n\n[Camera snapshot attached]";
    ctx.bodyForAgent = text + note;
  } catch {
    // Fail silently — never block message delivery
  }
};

export default handler;
