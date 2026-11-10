#!/usr/bin/env bash
# box-wg.sh — run on the box as root. Idempotent. DRAFT, not run yet.
# Env: EDGE_WG_PUB (edge wg public key, required), EDGE_IP (default 8.229.241.31).
set -euo pipefail
: "${EDGE_WG_PUB:?set EDGE_WG_PUB}"
EDGE_IP="${EDGE_IP:-8.229.241.31}"
command -v wg >/dev/null || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wireguard; }
install -d -m 700 /etc/wireguard
[ -f /etc/wireguard/box.key ] || (umask 077; wg genkey > /etc/wireguard/box.key)
wg pubkey < /etc/wireguard/box.key > /etc/wireguard/box.pub
cat > /etc/wireguard/wg0.conf <<WG
[Interface]
Address = 10.77.0.2/24
PostUp = wg set %i private-key /etc/wireguard/box.key
[Peer]
PublicKey = ${EDGE_WG_PUB}
Endpoint = ${EDGE_IP}:51820
AllowedIPs = 10.77.0.1/32
PersistentKeepalive = 25
WG
chmod 600 /etc/wireguard/wg0.conf
systemctl enable -q wg-quick@wg0
systemctl restart wg-quick@wg0
# compose publishes owui on 10.77.0.2:8080; docker must start after wg0 exists or the bind fails on reboot.
install -d /etc/systemd/system/docker.service.d
printf '[Unit]\nAfter=wg-quick@wg0.service\nWants=wg-quick@wg0.service\n' > /etc/systemd/system/docker.service.d/after-wg.conf
systemctl daemon-reload
echo "box-wg: done. BOX wg public key (give to edge-up.sh):"; cat /etc/wireguard/box.pub
ping -c1 -W3 10.77.0.1 >/dev/null && echo "wg: edge reachable" || echo "wg: edge NOT reachable yet (run edge-up.sh with this key)"
