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

echo "== stopping DHCP from advertising a default route/DNS to the laptop =="
# NM shared-mode runs its own dnsmasq and, by default, hands the plugged-in laptop a
# default route (DHCP option 3 = the box) and DNS (option 6 = the box). But the box
# deliberately blocks cable->SIM forwarding, so a laptop that follows that default
# route loses Internet (and Tailscale). Suppress both: the laptop keeps its real
# default route (office/WiFi) and reaches the box only via the directly-connected
# 10.10.10.0/24 route. NM's shared dnsmasq merges *.conf from this dir.
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
cat > /etc/NetworkManager/dnsmasq-shared.d/eco-no-gateway.conf <<'EOF'
dhcp-option=3
dhcp-option=6
EOF

echo "== ensuring mDNS (avahi) is running so <hostname>.local resolves =="
systemctl enable --now avahi-daemon >/dev/null 2>&1 || \
  echo "  (avahi-daemon not present — install 'avahi-daemon' for the .local name; the fixed IP still works)"

echo "== blocking internet passthrough (device must NOT NAT its SIM to the cable) =="
# NM's ipv4.method=shared also enables NAT eth0->WAN, which would let a plugged-in
# laptop pull metered LTE data through the Pi. We want the address + console, not a
# router. Drop everything FORWARDED from eth0 (console access is INPUT, so it stays
# up), and reinstall on every eth0 event via an NM dispatcher (shared mode re-creates
# its own rules on each activation).
#
# Backend-agnostic: RESI ships nft only; ECO images may have iptables. The nft path
# uses a dedicated table hooked to forward at priority -10 (ahead of NM's own filter
# chain), so a DROP there wins. It matches iifname eth0 only, so Docker container
# egress (docker0/veth) and the box's own SIM traffic (OUTPUT) are unaffected.
install_forward_block() {
  local NFT IPT
  if NFT=$(command -v nft || ([ -x /usr/sbin/nft ] && echo /usr/sbin/nft)); then
    # rebuild cleanly (idempotent): drop the table if present, then define via -f
    "$NFT" delete table inet eco_guard 2>/dev/null || true
    "$NFT" -f - <<'NFTEOF'
table inet eco_guard {
	chain block_cable_fwd {
		type filter hook forward priority -150; policy accept;
		iifname "eth0" drop
	}
}
NFTEOF
    echo "  nft: eco_guard drops forwarded traffic from eth0"
  elif IPT=$(command -v iptables || ([ -x /usr/sbin/iptables ] && echo /usr/sbin/iptables)); then
    "$IPT" -C FORWARD -i eth0 -j DROP 2>/dev/null || "$IPT" -I FORWARD -i eth0 -j DROP
    echo "  iptables: FORWARD -i eth0 -j DROP"
  else
    echo "  WARNING: neither nft nor iptables found — passthrough NOT blocked!" >&2
    return 1
  fi
}
install_forward_block || true
DISP=/etc/NetworkManager/dispatcher.d/50-eth0-no-inet-forward.sh
cat > "$DISP" <<'SCR'
#!/bin/bash
# reassert the eth0 forward-block after NM re-creates its shared-mode rules
[ "$1" = "eth0" ] || exit 0
case "$2" in up|dhcp4-change|connectivity-change) ;; *) exit 0 ;; esac
if NFT=$(command -v nft || ([ -x /usr/sbin/nft ] && echo /usr/sbin/nft)); then
  "$NFT" delete table inet eco_guard 2>/dev/null || true
  "$NFT" -f - <<'NFTEOF'
table inet eco_guard {
	chain block_cable_fwd {
		type filter hook forward priority -150; policy accept;
		iifname "eth0" drop
	}
}
NFTEOF
elif IPT=$(command -v iptables || ([ -x /usr/sbin/iptables ] && echo /usr/sbin/iptables)); then
  "$IPT" -C FORWARD -i eth0 -j DROP 2>/dev/null || "$IPT" -I FORWARD -i eth0 -j DROP
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
