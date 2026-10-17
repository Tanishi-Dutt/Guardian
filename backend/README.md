# Guardian backend (Person A)

FastAPI + Tiger Data (TimescaleDB). Contracts: `../CONTRACTS.md`. Every threshold and score weight is in `app/config.py`.

## Run

```bash
# from the repo root
uv venv .venv && uv pip install -p .venv -r backend/requirements.txt
docker compose -f backend/docker-compose.yml up -d        # local TimescaleDB (until DATABASE_URL points at Tiger Cloud)
.venv/bin/uvicorn backend.app.main:app --reload --port 8000
```

The schema and Linda's seed data are applied automatically on startup. `POST /demo/reset` wipes and reseeds everything.

```bash
.venv/bin/python -m pytest backend/tests -q                  # uses the local DB only, never sends texts
.venv/bin/python backend/scripts/simulate_call.py medicare   # fake call through the real API
curl -N localhost:8000/stream/live                           # watch the dashboard events
```

## Extra env vars (beyond `.env.example`)

| Var | Default | What |
|---|---|---|
| `SCREEN_MODE` | `register` | `register`: hand unknown callers to ElevenLabs via its Twilio register-call API (one number). `forward`: `<Dial>` `SCREENER_NUMBER`. |
| `TWILIO_SMS_FROM` | `GUARDIAN_NUMBER` | SMS fallback sender when Photon isn't configured |
| `PHOTON_SEND_URL` | — | Photon send endpoint (texts are log-only until Photon or Twilio keys are set) |
| `TRUSTED_NAME` | `David (son)` | Trusted contact's name in the seed |
| `LOCAL_TZ` | `America/Los_Angeles` | For the "odd hours" score rule |

## Wiring the phone (M1)

1. Twilio number → Voice webhook `POST {PUBLIC_BASE_URL}/calls/inbound`.
2. ElevenLabs agent (C):
   - Server tool `assess` → `POST {PUBLIC_BASE_URL}/tools/assess`, body `{call_id, caller_number, guardian_asked, caller_said}`. Set `call_id` to the dynamic variable `guardian_call_id` if available (register mode), else `system__conversation_id`; set `caller_number` to `system__caller_id`.
   - Post-call webhook (transcript + audio) → `POST {PUBLIC_BASE_URL}/calls/post-call`; put its HMAC secret in `ELEVENLABS_WEBHOOK_SECRET`.
   - Max call duration 90 s. Transfer-to-number tool → `LINDA_PHONE`.
3. For `forward` mode, import the second Twilio number into ElevenLabs and set `SCREENER_NUMBER`.

## Additions not yet in CONTRACTS
- Tables `blocked_numbers` (per-user blocks from the family) and `messages` (text of messages left for Linda).
- `GET /messages`, `GET /e/{evidence_id}` (evidence page linked from the family text) and `GET /e/{evidence_id}/audio`, `GET /health`.
- The `decision` event for `connected` also carries `whisper` (the line shown on the phone simulator).
- `evidence_saved` is sent twice for a scam call: right away with `recording_url: null`, then again once the audio is saved. The dashboard should upsert on `evidence_id`.
