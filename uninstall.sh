#!/usr/bin/env bash
# Remove astra. Keeps /etc/astra (config, audit log) unless --purge is given.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
systemctl disable --now astra 2>/dev/null || true
rm -f /etc/systemd/system/astra.service /usr/local/bin/astra
systemctl daemon-reload
rm -rf /opt/astra
if [ "${1:-}" = "--purge" ]; then rm -rf /etc/astra; echo "Config and logs removed."; else echo "Kept /etc/astra (use --purge to delete)."; fi
echo "astra removed. Nginx sites, cron entries and backups it created are left in place."
