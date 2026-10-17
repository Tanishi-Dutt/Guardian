#!/usr/bin/env bash
# One-time setup on a fresh Vultr Ubuntu 24.04 VM, as root:
#   curl -fsSL https://raw.githubusercontent.com/Tanishi-Dutt/Guardian/main/backend/deploy/setup.sh | DOMAIN=example.com bash
# Then copy your .env to /opt/guardian/.env and run: systemctl restart guardian-api guardian-photon
set -euo pipefail
: "${DOMAIN:?set DOMAIN=yourdomain.com}"
REPO=${REPO:-https://github.com/Tanishi-Dutt/Guardian.git}

apt-get update
apt-get install -y git curl debian-keyring debian-archive-keyring apt-transport-https python3 python3-venv
# Caddy
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
# Node 22 (Photon sidecar, web build)
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y caddy nodejs

id guardian >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin guardian
[ -d /opt/guardian/.git ] || git clone "$REPO" /opt/guardian
touch /opt/guardian/.env
chown -R guardian:guardian /opt/guardian

/opt/guardian/backend/deploy/update.sh

cp /opt/guardian/backend/deploy/guardian-api.service /opt/guardian/backend/deploy/guardian-photon.service /etc/systemd/system/
cp /opt/guardian/backend/deploy/Caddyfile /etc/caddy/Caddyfile
grep -q '^DOMAIN=' /etc/default/caddy 2>/dev/null || echo "DOMAIN=$DOMAIN" >> /etc/default/caddy
mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironmentFile=/etc/default/caddy\n' > /etc/systemd/system/caddy.service.d/env.conf
ufw allow 80,443/tcp 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now guardian-api caddy
systemctl restart caddy
echo "Done. Put the .env in /opt/guardian/.env (PUBLIC_BASE_URL=https://api.$DOMAIN), then:"
echo "  systemctl restart guardian-api && systemctl enable --now guardian-photon"
