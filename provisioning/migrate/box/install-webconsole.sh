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

APP=/opt/eco/webui

echo "== dirs =="
mkdir -p "$APP" /etc/eco-iot-gw /var/log/eco-iot-gw /var/lib/eco-iot-gw/audit
chmod 750 /etc/eco-iot-gw

echo "== unpack backend + dist + wheelhouse =="
rm -rf "$APP/backend" "$APP/dist" "$APP/wheelhouse"
mkdir -p "$APP/backend" "$APP/dist" "$APP/wheelhouse"
tar -xzf "$BACKEND_TGZ" -C "$APP/backend"
tar -xzf "$DIST_TGZ"    -C "$APP/dist"
tar -xzf "$WHEELS_TGZ"  -C "$APP/wheelhouse"
# tolerate a wrapping top dir from tar
[ -d "$APP/dist/dist" ] && { mv "$APP/dist/dist"/* "$APP/dist/"; rmdir "$APP/dist/dist"; } || true
[ -f "$APP/dist/index.html" ] || { echo "ERROR: dist/index.html missing after unpack"; exit 1; }

echo "== venv (--system-site-packages) =="
if [ ! -x "$APP/venv/bin/python" ]; then
  python3 -m venv --system-site-packages "$APP/venv"
fi
REQ="$APP/backend/requirements-lean.txt"
[ -f "$REQ" ] || REQ="$APP/wheelhouse/requirements-lean.txt"
"$APP/venv/bin/pip" install --no-index --find-links "$APP/wheelhouse" -r "$REQ" 2>&1 | tail -8

echo "== sanity import =="
ECO_ALLOW_DEFAULT_SECRETS=1 "$APP/venv/bin/python" -c "import app.main; print('backend imports OK')" \
  --  2>/dev/null || ( cd "$APP/backend" && ECO_ALLOW_DEFAULT_SECRETS=1 "$APP/venv/bin/python" -c "import app.main; print('backend imports OK')" )

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
# single worker: the token store + rate limiter are in-memory (per-process).
ExecStart=$APP/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 80 --workers 1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable eco-iot-gw-backend
echo "== install-webconsole DONE (start after setup-secrets.sh) =="
