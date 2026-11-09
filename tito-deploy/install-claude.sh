#!/usr/bin/env bash
# One-shot setup for a WIPED Tito VPS (Ubuntu 24.04, only root exists).
# Run as root:
#   curl -fsSL https://raw.githubusercontent.com/Forzalab/open-webui/tito/tito-deploy/install-claude.sh | bash
# Then (by hand, needs a browser login once):
#   su - tito
#   claude                      # /login, then /exit
#   tmux new -s rc 'cd /opt/tito && claude remote-control'
#
# Known traps on this box (2026-11-09):
# - claude.ai/install.sh returns 403 from this VPS IP -> install via npm.
# - Ubuntu's apt nodejs is old -> NodeSource Node 22.
# - npm can cache a corrupted tarball ("zlib: unexpected end of file") -> truncated
#   native binary -> "Segmentation fault". Fix = clean cache + reinstall, checked below.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq ca-certificates curl git tmux gnupg

# Node 22 (NodeSource), only if missing or too old.
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -qq nodejs
fi

# Claude Code via npm, retry once on a corrupted download.
install_claude() { npm install -g @anthropic-ai/claude-code >/dev/null; }
claude_ok() { timeout 30 claude --version >/dev/null 2>&1; }
install_claude || true
if ! claude_ok; then
  echo "claude broken (likely corrupted npm cache) -> cleaning cache, reinstalling"
  npm cache clean --force
  npm uninstall -g @anthropic-ai/claude-code >/dev/null 2>&1 || true
  install_claude
  claude_ok || { echo "claude still fails: run 'claude --version' and send the error"; exit 1; }
fi
echo "claude: $(claude --version)"

# User tito: sudo without password, same SSH keys as root.
id tito >/dev/null 2>&1 || useradd -m -s /bin/bash tito
usermod -aG sudo tito
echo 'tito ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/tito
chmod 440 /etc/sudoers.d/tito
if [ -f /root/.ssh/authorized_keys ]; then
  install -d -m 700 -o tito -g tito /home/tito/.ssh
  install -m 600 -o tito -g tito /root/.ssh/authorized_keys /home/tito/.ssh/authorized_keys
fi

mkdir -p /opt/tito
chown -R tito:tito /opt/tito

echo "DONE. Next: su - tito -> claude (/login) -> tmux new -s rc 'cd /opt/tito && claude remote-control'"
