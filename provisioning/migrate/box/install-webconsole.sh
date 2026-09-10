#!/bin/bash
# Install the ECO web console (FastAPI backend serving the built Vue SPA directly —
# no nginx) on a migrated box. Fully offline: Python deps come from a wheelhouse
# transferred over SCP, the frontend is pre-built on the laptop. Idempotent.
#
#   install-webconsole.sh <backend.tgz> <wheelhouse.tgz> <dist.tgz>
#
# Layout:
#   /opt/eco/webui/backend      FastAPI app (app/ + requirements-lean.txt)
#   /opt/eco/webui/dist         built Vue SPA (served by FastAPI at /)
#   /opt/eco/webui/venv         venv (--system-site-packages: reuses the box's
#                               psutil / pyserial / cryptography, no compiler)
#   /opt/eco/webui/wheelhouse   arm64 wheels (offline pip source)
#
# Notes baked in from the bench deploy:
#  - runs as ROOT (temporary, documented tech-debt): reads /etc/shadow for the
#    on-site ecoadmin login and needs the docker socket for Meters/status.
#  - listens on 0.0.0.0:80 so the site is reachable at http://10.10.10.1/ (cable)
#    and http://<tailscale-ip>/ (remote). Port 80 is free (apache2 masked).
#  - netifaces/pyroute2 are intentionally omitted (no arm64 wheel); the backend
#    import-guards them, so only the network-failover page degrades.
set -euo pipefail
BACKEND_TGZ=${1:-/tmp/webconsole-backend.tgz}
WHEELS_TGZ=${2:-/tmp/webconsole-wheelhouse.tgz}
DIST_TGZ=${3:-/tmp/webconsole-dist.tgz}
RELEASE=${4:?source release hash required}
[[ "$RELEASE" =~ ^[a-f0-9]{64}$ ]] || exit 2

APP=/opt/eco/webui

echo "== dirs =="
mkdir -p "$APP" /etc/eco-iot-gw /var/log/eco-iot-gw /var/lib/eco-iot-gw/audit
chmod 750 /etc/eco-iot-gw

echo "== stage backend + dist + wheelhouse =="
STAGE=$(mktemp -d "$APP/.install-XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/backend" "$STAGE/dist" "$APP/wheelhouse"
tar -xzf "$BACKEND_TGZ" -C "$STAGE/backend"
tar -xzf "$DIST_TGZ" -C "$STAGE/dist"
tar -xzf "$WHEELS_TGZ" -C "$APP/wheelhouse"
[ -f "$STAGE/dist/index.html" ] || { echo "ERROR: dist/index.html missing"; exit 1; }
# Retain hashed assets for browser sessions opened before this upgrade.
if [ -d "$APP/dist/assets" ]; then
  mkdir -p "$STAGE/dist/assets"
  cp -an "$APP/dist/assets/." "$STAGE/dist/assets/"
fi

echo "== venv (--system-site-packages) =="
if [ ! -x "$APP/venv/bin/python" ]; then
  python3 -m venv --system-site-packages "$APP/venv"
fi
REQ="$STAGE/backend/requirements-lean.txt"
[ -f "$REQ" ] || REQ="$APP/wheelhouse/requirements-lean.txt"
"$APP/venv/bin/pip" install --no-index --find-links "$APP/wheelhouse" -r "$REQ" 2>&1 | tail -8

echo "== sanity import before replacing running code =="
(cd "$STAGE/backend" && ECO_ALLOW_DEFAULT_SECRETS=1 "$APP/venv/bin/python" -c "import app.main; print('backend imports OK')")
# Keep one complete prior application release for operator rollback.
rm -rf "$APP/previous"
mkdir -p "$APP/previous"
[ ! -d "$APP/backend" ] || mv "$APP/backend" "$APP/previous/backend"
[ ! -d "$APP/dist" ] || mv "$APP/dist" "$APP/previous/dist"
[ ! -f "$APP/release" ] || cp "$APP/release" "$APP/previous/release"
mv "$STAGE/backend" "$APP/backend"
mv "$STAGE/dist" "$APP/dist"

echo "== systemd unit =="
cat > /etc/systemd/system/eco-iot-gw-backend.service <<UNIT
[Unit]
Description=ECO IoT Gateway web console (FastAPI + Vue)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
# root: reads /etc/shadow (on-site ecoadmin login) + docker socket (Meters/status).
User=root
WorkingDirectory=$APP/backend
Environment=ECO_FRONTEND_DIST=$APP/dist
Environment=PYTHONUNBUFFERED=1
Environment=TB_GATEWAY_CONFIG_DIR=/opt/eco/tb-gateway/config
Environment=TB_GATEWAY_LOG_DIR=/opt/eco/tb-gateway/logs
# single worker: the token store + rate limiter are in-memory (per-process).
ExecStart=$APP/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 80 --workers 1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable eco-iot-gw-backend
healthy=0
if systemctl restart eco-iot-gw-backend; then
  for attempt in {1..10}; do
    if curl -fsS --max-time 2 http://127.0.0.1/api/health >/dev/null; then
      healthy=1
      break
    fi
    sleep 1
  done
fi
if [ "$healthy" -ne 1 ]; then
  echo "ERROR: new backend failed health check; restoring previous application"
  if [ -d "$APP/previous/backend" ]; then
    rm -rf "$APP/backend" "$APP/dist"
    mv "$APP/previous/backend" "$APP/backend"
    mv "$APP/previous/dist" "$APP/dist"
    systemctl restart eco-iot-gw-backend
  fi
  exit 1
fi
printf '%s' "$RELEASE" > "$APP/release"
echo "== current web console installed and healthy =="
