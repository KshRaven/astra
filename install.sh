#!/usr/bin/env bash
# astra system installer for Debian/Ubuntu (Windows: install.ps1). Usage: sudo ./install.sh [--port 8800] [--with "nginx ufw fail2ban docker.io certbot"]
# Developing or just trying it? You do not need this: `pip install .` then run `astra`.
set -euo pipefail

PREFIX=/opt/astra; CONF=/etc/astra; PORT=8800; WITH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2;;
    --with) WITH="$2"; shift 2;;
    -h|--help) sed -n '2p' "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo ./install.sh" >&2; exit 1; }
command -v apt-get >/dev/null || { echo "This script supports apt-based systems only. See README for a manual install." >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required." >&2; exit 1; }
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing system packages (python3 $WITH)"
apt-get update -qq
# shellcheck disable=SC2086
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 $WITH
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Python 3.9+ is required")'

echo "==> Copying files to $PREFIX"
rm -rf "$PREFIX/src"; mkdir -p "$PREFIX"
cp -a "$SRC" "$PREFIX/src"
rm -rf "$PREFIX/src/.git" "$PREFIX/src/.dev-home"

echo "==> Creating the astra command"
cat > /usr/local/bin/astra <<WRAP
#!/bin/sh
export ASTRA_HOME=$CONF
export PYTHONPATH=$PREFIX/src
exec /usr/bin/python3 -m astra "\$@"
WRAP
chmod 755 /usr/local/bin/astra

# Upgrading from the project's old name (mypanel): move config, service, cron file and nginx sites over
if [ -d /etc/mypanel ] && [ ! -d "$CONF" ]; then
  echo "==> Migrating mypanel -> astra"
  systemctl disable --now mypanel 2>/dev/null || true
  mv /etc/mypanel "$CONF"
  rm -f /etc/systemd/system/mypanel.service /usr/local/bin/mypanel
  rm -rf /opt/mypanel
  [ -f /etc/cron.d/mypanel ] && mv /etc/cron.d/mypanel /etc/cron.d/astra
  for f in /etc/nginx/sites-available/mypanel-*; do
    [ -e "$f" ] || continue
    old="${f##*/}"; new="astra-${old#mypanel-}"
    sed '1s/# mypanel:/# astra:/' "$f" > "/etc/nginx/sites-available/$new" && rm -f "$f"
    if [ -L "/etc/nginx/sites-enabled/$old" ]; then
      rm -f "/etc/nginx/sites-enabled/$old"; ln -s "/etc/nginx/sites-available/$new" "/etc/nginx/sites-enabled/$new"
    fi
  done
  if command -v nginx >/dev/null && nginx -t >/dev/null 2>&1; then nginx -s reload 2>/dev/null || true; fi
fi

echo "==> Initialising config in $CONF (the admin password is shown once)"
astra init
astra config set port "$PORT" >/dev/null

echo "==> Installing systemd unit"
install -m 644 "$PREFIX/src/systemd/astra.service" /etc/systemd/system/astra.service
systemctl daemon-reload
systemctl enable --now astra
sleep 1

echo
astra doctor || true
echo
echo "Done. The panel is running as the 'astra' service on port $PORT (all interfaces)."
echo "Restrict it to this machine with:  astra config set host 127.0.0.1   (then: systemctl restart astra)"
echo "Put it behind HTTPS before exposing it to the internet: see nginx/astra.conf.example and docs/SECURITY.md"
echo "Change the password any time with 'astra passwd'. Turn on a second factor in Settings, or run 'astra mfa'."
