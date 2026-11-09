#!/usr/bin/env bash
# Run as root on the fresh VPS:
#   curl -fsSL https://raw.githubusercontent.com/Forzalab/open-webui/tito/tito-deploy/install-claude.sh | bash
# Then: su - tito ; claude   (log in once, /login) ; tmux new -s rc 'claude remote-control'
set -euo pipefail
apt-get update -qq && apt-get install -y -qq tmux git curl
id tito >/dev/null 2>&1 || { useradd -m -s /bin/bash tito; usermod -aG sudo tito; }
echo 'tito ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/tito && chmod 440 /etc/sudoers.d/tito
mkdir -p /opt/tito && chown tito:tito /opt/tito
su - tito -c 'curl -fsSL https://claude.ai/install.sh | bash'
su - tito -c 'grep -q ".local/bin" ~/.bashrc || echo "export PATH=\$HOME/.local/bin:\$PATH" >> ~/.bashrc'
echo "DONE. Next: su - tito  ->  cd /opt/tito && claude  (login)  ->  exit  ->  tmux new -s rc 'cd /opt/tito && claude remote-control'"
