// Guardian family messenger: iMessage alerts to the trusted family contact via Photon Spectrum.
//   POST /send {to, text}  -> iMessages `to` (called by backend/app/notify.py when PHOTON_SIDECAR_URL is set)
//   family replies         -> POST {BACKEND_URL}/webhooks/photon {from, text} (BLOCK / SAFE)
// Env (.env): PROJECT_ID, PROJECT_SECRET (Spectrum Cloud), BACKEND_URL (default http://localhost:8000),
//             PHOTON_SIDECAR_PORT (default 8787), PHOTON_SIDECAR_SECRET (optional shared bearer).
import http from "node:http";
import { Spectrum, type Space } from "spectrum-ts";
import { imessage } from "@spectrum-ts/imessage";

try {
  process.loadEnvFile();
} catch {
  // no .env: rely on the real environment
}

const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
const PORT = Number(process.env.PHOTON_SIDECAR_PORT || 8787);
const SECRET = process.env.PHOTON_SIDECAR_SECRET;

const app = await Spectrum({
  projectId: process.env.PROJECT_ID!,
  projectSecret: process.env.PROJECT_SECRET!,
  providers: [imessage.config()],
});
const im = imessage(app);
const spaces = new Map<string, Space>(); // phone/email -> DM

async function send(to: string, text: string) {
  let space = spaces.get(to);
  if (!space) {
    space = await im.space.create(await im.user(to));
    spaces.set(to, space);
  }
  await space.send(text);
}

async function listen() {
  for await (const [space, message] of app.messages) {
    if (message.direction === "outbound" || message.content.type !== "text") continue;
    const from = message.sender?.id;
    if (!from) continue;
    spaces.set(from, space);
    console.log(`reply from ${from}: ${message.content.text}`);
    await fetch(`${BACKEND_URL}/webhooks/photon`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ from, text: message.content.text }),
    }).catch((e) => console.error("forward to backend failed:", e.message));
  }
}

http
  .createServer(async (req, res) => {
    const reply = (code: number, body: object) => {
      res.writeHead(code, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (req.method === "GET" && req.url === "/health") return reply(200, { ok: true });
    if (req.method !== "POST" || req.url !== "/send") return reply(404, { error: "not found" });
    if (SECRET && req.headers.authorization !== `Bearer ${SECRET}`) return reply(401, { error: "unauthorized" });
    let body = "";
    for await (const chunk of req) body += chunk;
    try {
      const { to, text } = JSON.parse(body || "{}");
      if (!to || !text) return reply(400, { error: "to and text are required" });
      await send(to, text);
      console.log(`sent to ${to}`);
      reply(200, { ok: true });
    } catch (e) {
      console.error("send failed:", e);
      reply(502, { error: (e as Error).message });
    }
  })
  .listen(PORT, () => console.log(`family messenger on :${PORT} -> ${BACKEND_URL}`));

listen().catch((e) => {
  console.error("message stream ended:", e);
  process.exit(1);
});
