#!/usr/bin/env bash
set -euo pipefail

# Tito one-shot deploy. Idempotent: re-run to update the stack.
REPO_URL="https://github.com/Forzalab/open-webui"
TITO_REF="${TITO_REF:-tito}"
REPO="/opt/tito/open-webui"
ENV_FILE="/opt/tito/.env"

install_pkgs() { DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"; }

# 1. Docker + compose plugin from Docker's apt repo, if missing.
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  apt-get update -qq
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  install_pkgs docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# 2. unattended-upgrades: security only. + ufw.
apt-get update -qq
install_pkgs unattended-upgrades ufw
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
EOF

# 3. Firewall: ssh + http + https, then enable.
ufw allow 22/tcp  >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

# 4. 2GB swapfile if none exists.
if ! swapon --show 2>/dev/null | grep -q .; then
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# 5. Source: clone or fetch + checkout the pinned ref.
mkdir -p /opt/tito
if [ -d "$REPO/.git" ]; then
  git -C "$REPO" fetch origin "$TITO_REF" --tags
else
  git clone "$REPO_URL" "$REPO"
  git -C "$REPO" fetch origin "$TITO_REF" --tags
fi
git -C "$REPO" checkout -B tito-deploy FETCH_HEAD

# 6. First run: seed .env from the example.
if [ ! -f "$ENV_FILE" ]; then
  cp "$REPO/tito-deploy/.env.example" "$ENV_FILE"
fi

# 6b. Auto-generate WEBUI_SECRET_KEY if empty.
if grep -qE '^WEBUI_SECRET_KEY=$' "$ENV_FILE"; then
  sed -i "s|^WEBUI_SECRET_KEY=$|WEBUI_SECRET_KEY=$(openssl rand -hex 32)|" "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

# 7. Required vars must be non-empty.
REQUIRED="DATABASE_URL WEBUI_SECRET_KEY GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET ANTHROPIC_API_KEY"
missing=""
for var in $REQUIRED; do
  grep -qE "^${var}=.+" "$ENV_FILE" || missing="$missing $var"
done
if [ -n "$missing" ]; then
  echo "missing/empty required vars:$missing"
  echo "edit $ENV_FILE then rerun"
  exit 0
fi

# 8. Build + start (or update).
docker compose -f "$REPO/tito-deploy/docker-compose.yml" --env-file "$ENV_FILE" up -d --build
