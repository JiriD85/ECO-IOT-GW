#!/usr/bin/env bash
#
# install-lte-rawip.sh — make the LTE uplink survive a reboot.
#
# The Quectel EC25 speaks QMI raw-IP; the qmi_wwan netdev must be in raw_ip=Y or
# NetworkManager cannot apply the bearer IP and fails with
#   "device (cdc-wdm0): retrieving IP configuration failed: modem IP method unsupported"
# looping forever → no default route, no MQTT, no Tailscale. On this hardware the mode
# comes up as N after a reboot and ModemManager does not reliably flip it (raw_ip is only
# settable while the iface is DOWN, but NM's retry loop keeps it UP — a deadlock).
#
# RESI shipped NO fix for this (field units simply never rebooted). We install two layers:
#   1. a udev rule that sets raw_ip=Y the instant wwan0 appears (before NM/MM touch it), and
#   2. a udev-triggered oneshot that self-heals if the direct write didn't take, using the
#      proven disconnect → down → raw_ip=Y → up → reconnect sequence.
#
# Idempotent. Also runs the helper once now, so LTE comes up without waiting for a reboot.
#
# Usage:  sudo ./install-lte-rawip.sh
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "must run as root (use sudo)" >&2; exit 1; fi

HELPER=/usr/local/sbin/eco-wwan-rawip.sh
RULE=/etc/udev/rules.d/99-eco-wwan-rawip.rules
UNIT=/etc/systemd/system/eco-wwan-rawip.service

echo "== installing $HELPER =="
install -d /usr/local/sbin
cat > "$HELPER" <<'SH'
#!/bin/sh
# Ensure the QMI netdev is in raw_ip mode so NetworkManager can apply the bearer IP.
# Safe to run anytime: no-op if there is no QMI modem or it is already correct.
IF=wwan0
RIP="/sys/class/net/$IF/qmi/raw_ip"
[ -e "$RIP" ] || exit 0                          # no QMI modem present
[ "$(cat "$RIP" 2>/dev/null)" = "Y" ] && exit 0  # already correct — don't disturb a live link
logger -t eco-wwan-rawip "raw_ip is N on $IF — forcing Y"
nmcli dev disconnect cdc-wdm0 >/dev/null 2>&1 || true   # stop NM's retry churn
ip link set "$IF" down 2>/dev/null || true              # raw_ip is only writable while DOWN
echo Y > "$RIP" 2>/dev/null || true
ip link set "$IF" up 2>/dev/null || true
nmcli con up gsm >/dev/null 2>&1 || true                # best-effort nudge; autoconnect covers it
exit 0
SH
chmod 755 "$HELPER"

echo "== installing $UNIT =="
cat > "$UNIT" <<EOF
[Unit]
Description=Ensure QMI raw_ip=Y on wwan0 (LTE modem IP mode)
After=sys-subsystem-net-devices-wwan0.device

[Service]
Type=oneshot
ExecStart=$HELPER
EOF

echo "== installing $RULE =="
# Primary: set raw_ip=Y directly at device-add (down, so writable — earliest possible).
# Backup: trigger the self-healing oneshot the moment wwan0 appears.
cat > "$RULE" <<'EOF'
ACTION=="add", SUBSYSTEM=="net", KERNEL=="wwan0", ATTR{qmi/raw_ip}="Y", TAG+="systemd", ENV{SYSTEMD_WANTS}+="eco-wwan-rawip.service"
EOF

echo "== reloading udev + systemd =="
udevadm control --reload-rules 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true

echo "== applying now (so LTE comes up without a reboot) =="
"$HELPER" || true
sleep 3
RIP=/sys/class/net/wwan0/qmi/raw_ip
if [ -e "$RIP" ]; then echo "  wwan0 raw_ip = $(cat "$RIP")"; else echo "  (no wwan0 yet)"; fi

echo
echo "DONE. LTE raw_ip fix installed (udev + oneshot). Survives reboot and modem re-plug."
