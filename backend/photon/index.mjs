// Photon iMessage sidecar for the Guardian backend (Photon's SDK is Node-only).
//   POST /send {to, text}   -> sends an iMessage (called by backend/app/notify.py)
//   incoming family replies -> POST {BACKEND_URL}/webhooks/photon {from, text}
// Env: PHOTON_ADDRESS (host:port), PHOTON_TOKEN, BACKEND_URL (default http://localhost:8000),
//      PHOTON_SIDECAR_PORT (default 8787), PHOTON_SIDECAR_SECRET (optional shared bearer).
import http from "node:http";
import { createGrpcClient } from "@photon-ai/advanced-imessage";

const { PHOTON_ADDRESS, PHOTON_TOKEN, PHOTON_SIDECAR_SECRET } = process.env;
const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
const PORT = Number(process.env.PHOTON_SIDECAR_PORT || 8787);

if (!PHOTON_ADDRESS || !PHOTON_TOKEN) {
  console.error("PHOTON_ADDRESS and PHOTON_TOKEN are required");
  process.exit(1);
}

const im = createGrpcClient({ address: PHOTON_ADDRESS, token: PHOTON_TOKEN });
const chats = new Map(); // address -> chat guid

async function chatFor(address) {
  if (!chats.has(address)) {
    const { chat } = await im.chats.create([address]);
    chats.set(address, chat.guid);
  }
  return chats.get(address);
}

async function send(to, text) {
  const message = await im.messages.sendText(await chatFor(to), text);
  return message.guid;
}

async function listen() {
  for (;;) {
    try {
      for await (const event of im.messages.subscribeEvents()) {
        if (event.type !== "message.received" || event.isFromMe) continue;
        const from = event.actor?.address;
        const text = event.message?.content?.text;
        if (!from || !text) continue;
        chats.set(from, event.chatGuid);
        console.log(`reply from ${from}: ${text}`);
        await fetch(`${BACKEND_URL}/webhooks/photon`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ from, text }),
        }).catch((e) => console.error("forward failed:", e.message));
      }
    } catch (e) {
      console.error("event stream dropped, reconnecting:", e.message);
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}

http
  .createServer(async (req, res) => {
    const reply = (code, body) => {
      res.writeHead(code, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (req.method === "GET" && req.url === "/health") return reply(200, { ok: true });
    if (req.method !== "POST" || req.url !== "/send") return reply(404, { error: "not found" });
    if (PHOTON_SIDECAR_SECRET && req.headers.authorization !== `Bearer ${PHOTON_SIDECAR_SECRET}`)
      return reply(401, { error: "unauthorized" });
    let body = "";
    for await (const chunk of req) body += chunk;
    try {
      const { to, text } = JSON.parse(body || "{}");
      if (!to || !text) return reply(400, { error: "to and text are required" });
      reply(200, { ok: true, guid: await send(to, text) });
    } catch (e) {
      console.error("send failed:", e);
      reply(502, { error: e.message });
    }
  })
  .listen(PORT, () => console.log(`photon sidecar on :${PORT} -> ${BACKEND_URL}`));

listen();
