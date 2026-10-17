# Guardian backend (Person A)

FastAPI + Tiger Data (TimescaleDB). Contracts: `../CONTRACTS.md`. Every threshold and score weight is in `app/config.py`.

## Run

```bash
# from the repo root
uv venv .venv && uv pip install -p .venv -r backend/requirements.txt
docker compose -f backend/docker-compose.yml up -d        # local TimescaleDB (until DATABASE_URL points at Tiger Cloud)
.venv/bin/uvicorn backend.app.main:app --port 8000
```

Restart it after code changes (no `--reload`: a reload drops calls in progress). The schema and Linda's seed data are applied automatically on startup. `POST /demo/reset` wipes and reseeds everything.

```bash
.venv/bin/python -m pytest backend/tests -q                  # uses the local DB only, never sends texts
.venv/bin/python backend/scripts/simulate_call.py medicare   # fake call through the real API
curl -N localhost:8000/stream/live                           # watch the dashboard events
```

## Public URL for webhooks

`backend/scripts/dev.sh` starts the DB, the API and a Cloudflare quick tunnel (no account), and prints the webhook URLs.
Good for testing only: the quick tunnel adds 1-6 s per request, which is too slow for live calls (assess must answer in under 1.5 s).
Use the Vultr deploy (below) or a paid ngrok for real calls.

## Family texts (Photon)

Photon's SDK is Node-only, so `backend/photon/` is a small sidecar:
`cd backend/photon && npm install && node index.mjs` (needs `PHOTON_ADDRESS`, `PHOTON_TOKEN`).
It serves `POST /send {to, text}` for `app/notify.py` and forwards family replies to `/webhooks/photon`.
If `PHOTON_SIDECAR_URL` is empty, texts go out over Twilio SMS; with no Twilio keys either, they are only logged.

## Deploy (Vultr + GoDaddy)

1. Vultr: Ubuntu 24.04 VM. GoDaddy DNS: `A @` and `A api` point to its IP.
2. On the VM as root: `curl -fsSL https://raw.githubusercontent.com/Tanishi-Dutt/Guardian/main/backend/deploy/setup.sh | DOMAIN=yourdomain.com bash`
3. Copy `.env` to `/opt/guardian/.env` with `PUBLIC_BASE_URL=https://api.yourdomain.com` and the Tiger `DATABASE_URL`.
   Then run `systemctl restart guardian-api && systemctl enable --now guardian-photon`.
4. To ship new code: `sudo /opt/guardian/backend/deploy/update.sh` (it pulls main, reinstalls, rebuilds `web/` and restarts).

Caddy serves `api.DOMAIN` (backend, TLS, SSE unbuffered) and `DOMAIN` (C's `web/dist`).

## Extra env vars (beyond `.env.example`)

| Var | Default | What |
|---|---|---|
| `TRUSTED_NAME` | `David (son)` | Trusted contact's name in the seed |
| `LOCAL_TZ` | `America/Los_Angeles` | For the "odd hours" score rule |

## Wiring the phone (M1)

1. Twilio number → Voice webhook `POST {PUBLIC_BASE_URL}/calls/inbound`.
2. ElevenLabs agent (C):
   - Server tool `assess` → `POST {PUBLIC_BASE_URL}/tools/assess`, body `{call_id, caller_number, guardian_asked, caller_said}`.
     Set `call_id` and `caller_number` with value type **Dynamic variable** (not filled by the LLM):
     `call_id` = `guardian_call_id` (register mode; it's the Twilio CallSid), or `system__conversation_id` otherwise;
     `caller_number` = `system__caller_id`. The backend links the ids either way. `guardian_asked` and `caller_said` are filled by the LLM.
   - Post-call webhook (transcript + audio) → `POST {PUBLIC_BASE_URL}/calls/post-call`; put its HMAC secret in `ELEVENLABS_WEBHOOK_SECRET`.
   - Max call duration 90 s. Transfer-to-number tool → `LINDA_PHONE`.
3. For `forward` mode, import the second Twilio number into ElevenLabs and set `SCREENER_NUMBER`.

## Additions not yet in CONTRACTS
- Tables `blocked_numbers` (per-user blocks from the family) and `messages` (text of messages left for Linda).
- `GET /messages`, `GET /e/{evidence_id}` (evidence page linked from the family text) and `GET /e/{evidence_id}/audio`, `GET /health`.
- The `decision` event for `connected` also carries `whisper` (the line shown on the phone simulator).
- `evidence_saved` is sent twice for a scam call: right away with `recording_url: null`, then again once the audio is saved. The dashboard should upsert on `evidence_id`.
