#!/usr/bin/env bash
# box-wg-off.sh — run on the box as root, AFTER `up` with the new compose (no 10.77.0.2 bind).
# Undoes box-wg.sh: the GCP edge was deleted 2026-11-11 (DNS titodori -> box). Idempotent.
set -euo pipefail
if docker ps --format '{{.Ports}}' | grep -q '10.77.0.2'; then
  echo "box-wg-off: a container still publishes on 10.77.0.2; run 'up' with the new compose first." >&2
  exit 1
fi
systemctl disable --now wg-quick@wg0 2>/dev/null || true
rm -f /etc/systemd/system/docker.service.d/after-wg.conf
rmdir /etc/systemd/system/docker.service.d 2>/dev/null || true
systemctl daemon-reload
ip link show wg0 >/dev/null 2>&1 && echo "box-wg-off: wg0 still up (check)" || echo "box-wg-off: wg0 down, docker no longer waits on wg. Keys left in /etc/wireguard (harmless)."
