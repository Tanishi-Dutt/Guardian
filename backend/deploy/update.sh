#!/usr/bin/env bash
# Pull main and rebuild everything on the VM. Safe to re-run: sudo /opt/guardian/backend/deploy/update.sh
set -euo pipefail
cd /opt/guardian
sudo -u guardian git pull --rebase
sudo -u guardian python3 -m venv .venv
sudo -u guardian .venv/bin/pip install -q -r backend/requirements.txt
(cd family-messenger && sudo -u guardian npm ci --silent)
# web/ is built and hosted by Vercel.
systemctl restart guardian-api 2>/dev/null || true
systemctl is-enabled guardian-messenger >/dev/null 2>&1 && systemctl restart guardian-messenger || true
