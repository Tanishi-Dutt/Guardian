#!/usr/bin/env bash
# Container entrypoint: keep the family messenger running (restart on crash), serve the API on $PORT.
cd /app
if [ -n "${PROJECT_ID:-}" ]; then
  (cd family-messenger && while true; do node_modules/.bin/tsx src/index.ts; echo "messenger exited, restarting"; sleep 5; done) &
else
  echo "PROJECT_ID not set: family messenger disabled"
fi
exec uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers --forwarded-allow-ips '*'
