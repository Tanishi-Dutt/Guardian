#!/usr/bin/env bash
# Local dev with a public URL for Twilio/ElevenLabs webhooks (no account needed):
#   backend/scripts/dev.sh
# Starts the local DB, the API on :8000 and a Cloudflare quick tunnel, then prints the URL.
# Put that URL in .env as PUBLIC_BASE_URL and in the Twilio/ElevenLabs webhook settings.
set -euo pipefail
cd "$(dirname "$0")/../.."
grep -q '^DATABASE_URL=.*tsdb' .env 2>/dev/null || docker compose -f backend/docker-compose.yml up -d
.venv/bin/uvicorn backend.app.main:app --port 8000 &
API=$!
trap 'kill $API 2>/dev/null' EXIT
CF=$(command -v cloudflared || echo ~/.local/bin/cloudflared)
"$CF" tunnel --no-autoupdate --url http://localhost:8000 2>&1 | while read -r line; do
  url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' <<<"$line" || true)
  [ -n "$url" ] && printf '\n  PUBLIC_BASE_URL=%s\n  Twilio voice webhook:  %s/calls/inbound\n  ElevenLabs tool:       %s/tools/assess\n  ElevenLabs post-call:  %s/calls/post-call\n\n' "$url" "$url" "$url" "$url"
done
