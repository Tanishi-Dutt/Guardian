#!/usr/bin/env bash
# One-time setup on a fresh Vultr Ubuntu 24.04 VM, as root:
#   curl -fsSL https://raw.githubusercontent.com/Tanishi-Dutt/Guardian/main/backend/deploy/setup.sh | DOMAIN=example.com bash
# Then copy both .env files (see the end of this script) and start the services.
set -euo pipefail
: "${DOMAIN:?set DOMAIN=yourdomain.com}"
REPO=${REPO:-https://github.com/Tanishi-Dutt/Guardian.git}

apt-get update
apt-get install -y git curl debian-keyring debian-archive-keyring apt-transport-https python3 python3-venv
# Caddy
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
# Node 22 (family messenger)
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y caddy nodejs

id guardian >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin guardian
[ -d /opt/guardian/.git ] || git clone "$REPO" /opt/guardian
touch /opt/guardian/.env
chown -R guardian:guardian /opt/guardian

/opt/guardian/backend/deploy/update.sh

cp /opt/guardian/backend/deploy/guardian-api.service /opt/guardian/backend/deploy/guardian-messenger.service /etc/systemd/system/
cp /opt/guardian/backend/deploy/Caddyfile /etc/caddy/Caddyfile
grep -q '^DOMAIN=' /etc/default/caddy 2>/dev/null || echo "DOMAIN=$DOMAIN" >> /etc/default/caddy
mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironmentFile=/etc/default/caddy\n' > /etc/systemd/system/caddy.service.d/env.conf
ufw allow 80,443/tcp 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now guardian-api caddy
systemctl restart caddy
echo "Done. Copy the secrets, then start everything:"
echo "  scp .env root@VM:/opt/guardian/.env                      # set PUBLIC_BASE_URL=https://api.$DOMAIN"
echo "  scp family-messenger/.env root@VM:/opt/guardian/family-messenger/.env"
echo "  chown guardian:guardian /opt/guardian/.env /opt/guardian/family-messenger/.env"
echo "  systemctl restart guardian-api && systemctl enable --now guardian-messenger"
