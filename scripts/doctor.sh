#!/usr/bin/env bash
# Debug helper: setup check + service state + recent logs.
set -u
if command -v astra >/dev/null; then P=astra; else cd "$(dirname "$0")/.." && P="python3 -m astra"; fi
$P doctor
echo; echo "--- systemd ---"
systemctl status astra --no-pager 2>/dev/null | head -12 || echo "(not installed as a service)"
echo; echo "--- last 20 server log lines ---"
journalctl -u astra -n 20 --no-pager 2>/dev/null || true
echo; echo "--- last 10 audit events ---"
$P logs -n 10
