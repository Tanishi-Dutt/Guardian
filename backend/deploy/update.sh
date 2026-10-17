#!/usr/bin/env bash
# Pull main and rebuild everything on the VM. Safe to re-run: sudo /opt/guardian/backend/deploy/update.sh
set -euo pipefail
cd /opt/guardian
sudo -u guardian git pull --rebase
sudo -u guardian python3 -m venv .venv
sudo -u guardian .venv/bin/pip install -q -r backend/requirements.txt
(cd backend/photon && sudo -u guardian npm ci --silent || sudo -u guardian npm install --silent)
if [ -f web/package.json ]; then
  (cd web && sudo -u guardian npm ci --silent && sudo -u guardian env VITE_API_BASE="$(grep ^PUBLIC_BASE_URL /opt/guardian/.env | cut -d= -f2)" npm run build)
fi
systemctl restart guardian-api 2>/dev/null || true
systemctl is-enabled guardian-photon >/dev/null 2>&1 && systemctl restart guardian-photon || true
