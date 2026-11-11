#!/usr/bin/env bash
# edge-up.sh — run on tito-edge (Debian 12) as root. Idempotent. DRAFT, not run yet.
# Public front for Tito: Caddy (TLS) → WireGuard → box owui.
# Env: BOX_WG_PUB (box wg public key, required), EDGE_HOST (default titodori.duckdns.org),
#      EDGE_TLS_INTERNAL=1 for the dry run before DNS moves (self-signed cert), OWUI_UPSTREAM (default 10.77.0.2:8080).
set -euo pipefail
# Guard: this script must run on the GCP edge VM, never on the box.
[ "$(hostname)" = tito-edge ] || { echo "edge-up.sh: run this on tito-edge (this host: $(hostname))" >&2; exit 1; }
: "${BOX_WG_PUB:?set BOX_WG_PUB}"
EDGE_HOST="${EDGE_HOST:-titodori.duckdns.org}"
TLS_LINE=""; [ "${EDGE_TLS_INTERNAL:-0}" = 1 ] && TLS_LINE="tls internal"
UP="${OWUI_UPSTREAM:-10.77.0.2:8080}"
# Browser page loads go to the OAuth/login host (same rule as tito-deploy/Caddyfile). Empty = proxy everything.
LOGIN_HOST="${EDGE_LOGIN_HOST:-}"
export DEBIAN_FRONTEND=noninteractive
# 1. packages (caddy from its official apt repo)
if ! command -v caddy >/dev/null; then
  apt-get update -qq && apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
fi
apt-get install -y -qq wireguard caddy
# 2. wg keys (generated here; private key never leaves this host)
install -d -m 700 /etc/wireguard
[ -f /etc/wireguard/edge.key ] || (umask 077; wg genkey > /etc/wireguard/edge.key)
wg pubkey < /etc/wireguard/edge.key > /etc/wireguard/edge.pub
# 3. wg0 = 10.77.0.1/24, one peer (box 10.77.0.2)
cat > /etc/wireguard/wg0.conf <<WG
[Interface]
Address = 10.77.0.1/24
ListenPort = 51820
PostUp = wg set %i private-key /etc/wireguard/edge.key
[Peer]
PublicKey = ${BOX_WG_PUB}
AllowedIPs = 10.77.0.2/32
PersistentKeepalive = 25
WG
chmod 600 /etc/wireguard/wg0.conf
systemctl enable -q wg-quick@wg0
systemctl restart wg-quick@wg0
# 4. Caddy: TLS on EDGE_HOST → owui over wg. Websockets are proxied by default;
#    flush_interval -1 = stream SSE/long-poll replies immediately; long timeouts for slow model turns.
if [ -n "$LOGIN_HOST" ]; then
BROWSER_BLOCK="@browser header Sec-Fetch-Mode navigate
	handle @browser {
		redir https://${LOGIN_HOST}{uri} 302
	}"
else BROWSER_BLOCK=""; fi
cat > /etc/caddy/Caddyfile <<CF
${EDGE_HOST} {
	${TLS_LINE}
	encode zstd gzip
	${BROWSER_BLOCK}
	handle {
		reverse_proxy ${UP} {
			flush_interval -1
			transport http {
				keepalive 5m
				read_timeout 30m
				write_timeout 30m
				dial_timeout 10s
			}
		}
	}
}
CF
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl enable -q caddy && systemctl reload-or-restart caddy
echo "dry-run test (before DNS): curl -sk --resolve ${EDGE_HOST}:443:<edge ip> https://${EDGE_HOST}/health"
echo "edge-up: done. EDGE wg public key (give to box-wg.sh):"; cat /etc/wireguard/edge.pub
