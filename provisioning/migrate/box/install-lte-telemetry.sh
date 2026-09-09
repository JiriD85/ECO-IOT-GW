#!/bin/sh
# Restore the fleet's LTE_* telemetry on the gateway device (ECO_<HWID>_gw).
#
# The original RESI stack produced these keys with /home/resivm/RESICheckLTE.sh, which
# scraped `mmcli --signal-get`. When we stood RESI down the keys stopped (last values
# 2026-08-17). The fleet dashboards bind to them, so we re-feed the same five:
#   LTE_RSSI  LTE_RSRQ  LTE_RSRP  LTE_SN_RATIO  LTE_IP     (-9999 = no signal sentinel)
#
# How it gets to ThingsBoard, without a second MQTT client:
#   tb-gateway's *custom statistics* run shell commands inside the container and publish
#   the results with send_telemetry() on the gateway device itself - verified in
#   statistics_service.py (__send_custom_command_statistics -> _gateway.send_telemetry).
#   The container cannot reach ModemManager, so a host timer writes each value into
#   <config>/lte/<KEY> and the in-container command is a plain `cat`. The config dir is
#   already bind-mounted, so this needs no new mount and no container re-create.
#
# Idempotent. Safe to re-run.
set -eu

CFGDIR=/opt/eco/tb-gateway/config
LTEDIR="$CFGDIR/lte"
STATSDIR="$CFGDIR/statistics"
BIN=/opt/eco/bin/eco-lte-signal.sh
PERIOD="${LTE_STATS_PERIOD:-120}"   # seconds between MQTT pushes (metered SIM). 120s keeps the
                                    # dashboard's modem tile fresh (esp. right after a reboot) while
                                    # the payload is tiny (~600 B). Was 900s: too slow, and a box that
                                    # reboots inside one window never pushed, so LTE_* looked dead.

[ "$(id -u)" = 0 ] || { echo "must run as root"; exit 1; }
command -v python3 >/dev/null || { echo "python3 required on the host for the JSON patch"; exit 1; }

mkdir -p "$LTEDIR" "$STATSDIR" /opt/eco/bin

# ---------------------------------------------------------------- collector
cat > "$BIN" <<'EOS'
#!/bin/sh
# Sample the LTE modem and write one value per file for tb-gateway to `cat`.
# Runs on the HOST (needs ModemManager over D-Bus). Never fails the timer: any
# missing value is written as the fleet's -9999 no-signal sentinel.
set -u
LTEDIR=/opt/eco/tb-gateway/config/lte
SENTINEL=-9999
mkdir -p "$LTEDIR"

put() { printf '%s\n' "$2" > "$LTEDIR/$1.tmp" && mv "$LTEDIR/$1.tmp" "$LTEDIR/$1"; }
allsentinel() { for k in LTE_RSSI LTE_RSRQ LTE_RSRP LTE_SN_RATIO; do put "$k" "$SENTINEL"; done; put LTE_IP "0.0.0.0"; }

command -v mmcli >/dev/null 2>&1 || { allsentinel; exit 0; }

# first modem index, e.g. /org/freedesktop/ModemManager1/Modem/0
IDX=$(mmcli -L 2>/dev/null | sed -n 's#.*/Modem/\([0-9]\+\).*#\1#p' | head -1)
[ -n "${IDX:-}" ] || { allsentinel; exit 0; }

# --signal-get returns nothing until periodic refresh is armed; re-arm every run so it
# survives a modem re-plug or ModemManager restart (this is what RESICheckLTE.sh did).
mmcli -m "$IDX" --signal-setup=10 >/dev/null 2>&1 || true

SIG=$(mmcli -m "$IDX" --signal-get 2>/dev/null || true)
# grab the first numeric match for each metric across whatever access tech reported
val() { printf '%s\n' "$SIG" | sed -n "s/.*$1: *\(-\?[0-9][0-9.]*\).*/\1/p" | head -1; }

R=$(val rssi); Q=$(val rsrq); P=$(val rsrp); S=$(val 's\/n')
put LTE_RSSI     "${R:-$SENTINEL}"
put LTE_RSRQ     "${Q:-$SENTINEL}"
put LTE_RSRP     "${P:-$SENTINEL}"
put LTE_SN_RATIO "${S:-$SENTINEL}"

# modem IP: prefer the ModemManager bearer, fall back to the wwan interface
BEARER=$(mmcli -m "$IDX" 2>/dev/null | sed -n 's#.*\(/org/freedesktop/ModemManager1/Bearer/[0-9]\+\).*#\1#p' | head -1)
IP=''
[ -n "$BEARER" ] && IP=$(mmcli -b "$BEARER" 2>/dev/null | sed -n 's/.*address: *\([0-9.]\+\).*/\1/p' | head -1)
[ -n "$IP" ] || IP=$(ip -4 -o addr show 2>/dev/null | awk '$2 ~ /^(wwan|cdc-wdm)/ {split($4,a,"/"); print a[1]; exit}')
put LTE_IP "${IP:-0.0.0.0}"
EOS
chmod 755 "$BIN"

# ---------------------------------------------------------------- timer
cat > /etc/systemd/system/eco-lte-signal.service <<'EOF'
[Unit]
Description=Sample LTE signal for gateway telemetry
After=ModemManager.service
[Service]
Type=oneshot
ExecStart=/opt/eco/bin/eco-lte-signal.sh
EOF

cat > /etc/systemd/system/eco-lte-signal.timer <<'EOF'
[Unit]
Description=Sample LTE signal every minute
[Timer]
OnBootSec=60
OnUnitActiveSec=60
AccuracySec=10s
[Install]
WantedBy=timers.target
EOF

# ---------------------------------------------------------------- gateway wiring
# One `cat` per key. Paths are the CONTAINER view of the bind-mounted config dir.
cat > "$STATSDIR/eco_lte.json" <<'EOF'
[
  { "attributeOnGateway": "LTE_RSSI",     "command": "printf %s $(cat /thingsboard_gateway/config/lte/LTE_RSSI)",     "timeout": 5 },
  { "attributeOnGateway": "LTE_RSRQ",     "command": "printf %s $(cat /thingsboard_gateway/config/lte/LTE_RSRQ)",     "timeout": 5 },
  { "attributeOnGateway": "LTE_RSRP",     "command": "printf %s $(cat /thingsboard_gateway/config/lte/LTE_RSRP)",     "timeout": 5 },
  { "attributeOnGateway": "LTE_SN_RATIO", "command": "printf %s $(cat /thingsboard_gateway/config/lte/LTE_SN_RATIO)", "timeout": 5 },
  { "attributeOnGateway": "LTE_IP",       "command": "printf %s $(cat /thingsboard_gateway/config/lte/LTE_IP)",       "timeout": 5 }
]
EOF

# statistics.configuration is resolved as <config_dir> + <value>, so keep it relative.
python3 - "$CFGDIR/tb_gateway.json" "$PERIOD" <<'EOF'
import json, sys, shutil
p, period = sys.argv[1], int(sys.argv[2])
with open(p) as f: cfg = json.load(f)
st = cfg.setdefault('thingsboard', {}).setdefault('statistics', {})
before = dict(st)
st['enable'] = True
st.setdefault('statsSendPeriodInSeconds', 3600)
st['enableCustom'] = True
st['configuration'] = 'statistics/eco_lte.json'
st['customStatsSendPeriodInSeconds'] = period
if before != st:
    shutil.copyfile(p, p + '.bak')
    with open(p, 'w') as f: json.dump(cfg, f, indent=2)
    print('tb_gateway.json patched (backup: tb_gateway.json.bak)')
else:
    print('tb_gateway.json already configured')
EOF

systemctl daemon-reload
systemctl enable --now eco-lte-signal.timer >/dev/null 2>&1 || systemctl enable --now eco-lte-signal.timer
systemctl start eco-lte-signal.service || true

echo "--- sampled values ---"
for k in LTE_RSSI LTE_RSRQ LTE_RSRP LTE_SN_RATIO LTE_IP; do
  printf '  %-13s %s\n' "$k" "$(cat "$LTEDIR/$k" 2>/dev/null || echo MISSING)"
done

if docker inspect tb-gateway >/dev/null 2>&1; then
  echo "restarting tb-gateway to pick up the statistics config"
  docker restart tb-gateway >/dev/null
  echo "restarted"
fi
echo "LTE telemetry installed (push every ${PERIOD}s)"
