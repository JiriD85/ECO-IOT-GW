#!/usr/bin/env bash
#
# setup-direct-ethernet.sh — configure the gateway's Ethernet port for on-site
# console access over a direct laptop cable.
#
# The gateway OWNS the link: it takes a fixed address and runs its own DHCP (via
# NetworkManager's built-in dnsmasq) so ANY laptop gets an address on plug-in —
# no Internet Connection Sharing, no static laptop config. Combined with avahi
# (mDNS) the engineer reaches http://<hostname>.local/ or the fixed IP below.
#
# See docs/FIELD_ETHERNET_ACCESS.md. Idempotent — safe to re-run.
#
# WARNING: applying this drops any existing session on eth0 (e.g. a bench that was
# reachable at 192.168.137.2 via the laptop's ICS). Run it when you can reconnect.
#
# Usage:  sudo ./setup-direct-ethernet.sh
set -euo pipefail

CON="eth0-direct"
IFACE="eth0"
ADDR="10.10.10.1/24"

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (use sudo)" >&2
  exit 1
fi

echo "== ensuring NetworkManager connection '$CON' on $IFACE =="
if ! nmcli -t -f NAME con show | grep -qx "$CON"; then
  nmcli con add type ethernet ifname "$IFACE" con-name "$CON"
  echo "created $CON"
else
  echo "$CON already exists"
fi

echo "== applying shared config ($ADDR, own DHCP, no default route) =="
nmcli con mod "$CON" \
  connection.autoconnect yes \
  connection.autoconnect-priority 10 \
  ipv4.method shared \
  ipv4.addresses "$ADDR" \
  ipv4.gateway "" \
  ipv4.never-default yes \
  ipv6.method ignore

echo "== ensuring mDNS (avahi) is running so <hostname>.local resolves =="
systemctl enable --now avahi-daemon >/dev/null 2>&1 || \
  echo "  (avahi-daemon not present — install 'avahi-daemon' for the .local name; the fixed IP still works)"

echo "== blocking internet passthrough (device must NOT NAT its SIM to the cable) =="
# NM's ipv4.method=shared also enables NAT eth0->WAN, which would let a plugged-in
# laptop pull metered LTE data through the Pi. We want the address + console, not a
# router. Drop all forwarding FROM eth0 (console access is INPUT, so it stays up),
# and reinstall the rule on every eth0 event via an NM dispatcher (shared mode
# re-creates its own rules on each activation).
iptables -C FORWARD -i "$IFACE" -j DROP 2>/dev/null || iptables -I FORWARD -i "$IFACE" -j DROP
DISP=/etc/NetworkManager/dispatcher.d/50-eth0-no-inet-forward.sh
cat > "$DISP" <<'SCR'
#!/bin/bash
IFACE="$1"; ACTION="$2"
if [ "$IFACE" = "eth0" ]; then
  case "$ACTION" in
    up|dhcp4-change|connectivity-change)
      iptables -C FORWARD -i eth0 -j DROP 2>/dev/null || iptables -I FORWARD -i eth0 -j DROP
      ;;
  esac
fi
SCR
chmod 755 "$DISP"
echo "  forward-block rule + dispatcher installed"

echo "== bringing the connection up =="
nmcli con up "$CON"

echo
echo "DONE. On-site console reachable at:"
echo "  http://$(hostname).local/     (mDNS name)"
echo "  http://${ADDR%/*}/            (fixed IP, same on every gateway)"
