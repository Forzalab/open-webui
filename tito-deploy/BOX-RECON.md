# Box recon (prompt for the Claude Code running ON the VPS)

Paste this to `claude` on the box (as user tito, in /opt/tito):

---

READ-ONLY recon of this VPS for the Tito deploy. Do NOT install, change, restart, or delete anything.
Never print secrets (no file contents from ~/.ssh, /opt/tito/.env, tokens, passwords): names and yes/no only.
Use sudo only for read commands. Each check: run it, record the short result. If a command is missing, write "missing", do not install it.

Write the report to /opt/tito/box-report.md as a table: check | result | OK / WARN / FAIL | why it matters.

1. System: OS + version, kernel, uptime, timezone + NTP sync (`timedatectl`).
2. Virtualization: `systemd-detect-virt` (KVM = good; OpenVZ/LXC = Docker may not work = FAIL). cgroup version (`stat -fc %T /sys/fs/cgroup`).
3. CPU: model, cores, flags avx/avx2/sse4_2 (yes/no each).
4. RAM + swap: `free -h`. Disk: `df -h /` and inode use. Disk type if visible.
5. Network: public IPv4 + IPv6 (yes/no), `ip -br a`, listening ports (`ss -tlnp`), ufw status, iptables rule count.
6. SSH: `sshd -T | grep -E 'permitrootlogin|passwordauthentication|port'` (FAIL if password auth on).
7. Outbound HTTPS reachability (HTTP code + time, `curl -s -o /dev/null -w '%{http_code} %{time_total}'`):
   api.anthropic.com, github.com, raw.githubusercontent.com, ghcr.io, registry.npmjs.org, deb.nodesource.com,
   download.docker.com, acme-v02.api.letsencrypt.org, claude.ai/install.sh (expect 403 here), console.neon.tech.
8. Neon: TCP to the Neon host on 5432 if /opt/tito/.env has DATABASE_URL (read ONLY the host part, never print the URL); time it (Frankfurt should be < 15 ms).
9. DNS: `getent hosts 185-147-159-26.sslip.io` must return 185.147.159.26.
10. Ports 80/443: is anything already bound? (Caddy needs both free.)
11. Docker: installed? version, compose plugin, `docker info` storage driver, can user tito run it (group)?
12. Node + npm + claude versions; `npm config get cache` size.
13. Packages: unattended-upgrades installed + enabled? pending updates count; reboot required?
14. Users: list human users (uid >= 1000) + sudo group members.
15. Free space after a ~6 GB image pull: estimate (disk free minus 6 GB).

End the report with: TOP 3 RISKS for running Open WebUI + Caddy + Docker here, and anything that blocks `bootstrap.sh`.
Then print only the summary table + top 3 risks to the screen.
