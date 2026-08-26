#!/usr/bin/env bash
#
# setup-networking.sh — lay down the gateway's full 3-mode WAN/console model.
#
# Supersedes setup-direct-ethernet.sh (which only did the console link). It restores
# the RESI field behaviour (plug Ethernet into a router → Internet) AND keeps our
# direct-cable console, AND keeps LTE as an always-on failover — all auto-selected by
# NetworkManager, no operator action:
#
#   eth0 in a network WITH DHCP   → profile 'eth0-wan'    → Internet over Ethernet
#   eth0 straight to a PC (no DHCP)→ profile 'eth0-direct' → box serves 10.10.10.1 + DHCP
#   no cable                       → LTE only
#   Ethernet AND LTE up            → Ethernet wins (metric 100 < 700), LTE = instant failover
#
# Why this shape: RESI carried NO ethernet profile and NO metric/route config — it just
# rode NetworkManager's default per-device route metrics (ethernet 100, wwan 700), so a
# plugged-in cable always beat the SIM. We reproduce that explicitly (deterministic
# metrics) and add the PC-direct fallback RESI never had. See docs/FIELD_ETHERNET_ACCESS.md.
#
# Idempotent — safe to re-run. Run it when you can reconnect (it drops eth0 briefly).
#
# Usage:  sudo ./setup-networking.sh
set -euo pipefail

IFACE="eth0"
WAN="eth0-wan"
DIRECT="eth0-direct"
DIRECT_ADDR="10.10.10.1/24"
GSM="gsm"            # the GSM profile we standardise on (APN wsim)
GSM_ALT="modem"      # the factory duplicate we stop from competing
WAN_METRIC=100
GSM_METRIC=700
DHCP_TIMEOUT=15

if [[ $EUID -ne 0 ]]; then echo "must run as root (use sudo)" >&2; exit 1; fi

# ---------------------------------------------------------------------------
# 1. eth0-wan — DHCP client, preferred. Fails fast if no DHCP so NM falls through
#    to eth0-direct. may-fail=no on IPv4 makes "no lease" a hard activation failure
#    (that is what triggers the fallback); IPv6 stays best-effort.
#    autoconnect-retries is left at the NM default (4): after a few failed DHCP
#    attempts NM settles on eth0-direct and stops preempting it — but a cable re-plug
#    (carrier bounce) resets the counter, so moving to a real router re-tries WAN.
#    Setting 0 (infinite) would make NM flap the console link forever in PC-direct mode.
# ---------------------------------------------------------------------------
echo "== ensuring '$WAN' (DHCP WAN, preferred) on $IFACE =="
if ! nmcli -t -f NAME con show | grep -qx "$WAN"; then
  nmcli con add type ethernet ifname "$IFACE" con-name "$WAN"
fi
nmcli con mod "$WAN" \
  connection.autoconnect yes \
  connection.autoconnect-priority 20 \
  ipv4.method auto \
  ipv4.may-fail no \
  ipv4.dhcp-timeout "$DHCP_TIMEOUT" \
  ipv4.route-metric "$WAN_METRIC" \
  ipv6.method auto

# ---------------------------------------------------------------------------
# 2. eth0-direct — shared 10.10.10.1 + own DHCP, the PC-direct/console fallback.
#    Lower priority so NM only lands here when eth0-wan's DHCP failed.
# ---------------------------------------------------------------------------
echo "== ensuring '$DIRECT' (shared 10.10.10.1 console fallback) on $IFACE =="
if ! nmcli -t -f NAME con show | grep -qx "$DIRECT"; then
  nmcli con add type ethernet ifname "$IFACE" con-name "$DIRECT"
fi
nmcli con mod "$DIRECT" \
  connection.autoconnect yes \
  connection.autoconnect-priority 10 \
  ipv4.method shared \
  ipv4.addresses "$DIRECT_ADDR" \
  ipv4.gateway "" \
  ipv4.never-default yes \
  ipv6.method ignore

# NM shared-mode dnsmasq otherwise hands the plugged-in PC a default route (opt 3) and
# DNS (opt 6) pointing at the box; the box blocks cable→SIM forwarding, so a PC that
# followed that would lose Internet. Suppress both (merged from this dir in shared mode).
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
cat > /etc/NetworkManager/dnsmasq-shared.d/eco-no-gateway.conf <<'EOF'
dhcp-option=3
dhcp-option=6
EOF

# ---------------------------------------------------------------------------
# 3. LTE — standardise on a single GSM profile (APN wsim), higher route metric so
#    Ethernet always wins when present. Stop the factory duplicate from competing
#    (two autoconnect GSM profiles alternate and wedge the modem in a retry loop).
# ---------------------------------------------------------------------------
if nmcli -t -f NAME con show | grep -qx "$GSM"; then
  echo "== standardising LTE profile '$GSM' (APN wsim, metric $GSM_METRIC, always-on) =="
  nmcli con mod "$GSM" \
    connection.autoconnect yes \
    gsm.apn wsim \
    ipv4.method auto \
    ipv4.route-metric "$GSM_METRIC" \
    ipv6.method ignore
  if nmcli -t -f NAME con show | grep -qx "$GSM_ALT"; then
    echo "   disabling duplicate GSM profile '$GSM_ALT' (autoconnect off)"
    nmcli con mod "$GSM_ALT" connection.autoconnect no || true
  fi
else
  echo "== NOTE: no '$GSM' profile found — leaving LTE profiles untouched =="
fi

# ---------------------------------------------------------------------------
# 4. Mode-aware guard: the cable→SIM forward block must apply ONLY while eth0 is in
#    shared (console) mode. In WAN mode eth0 legitimately routes/forwards (Docker,
#    Tailscale subnet routes), so the block must be OFF. A dispatcher keys on which
#    connection came up on eth0 and installs/removes the nft table accordingly.
# ---------------------------------------------------------------------------
DISP=/etc/NetworkManager/dispatcher.d/50-eco-eth0-guard.sh
cat > "$DISP" <<'SCR'
#!/bin/bash
# $1 = interface, $2 = action; NM exports CONNECTION_ID for up/down events.
[ "$1" = "eth0" ] || exit 0
case "$2" in up|down|dhcp4-change|connectivity-change) ;; *) exit 0 ;; esac

apply_block() {   # drop everything FORWARDED from eth0 (console access is INPUT, unaffected)
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
}
remove_block() {
  if NFT=$(command -v nft || ([ -x /usr/sbin/nft ] && echo /usr/sbin/nft)); then
    "$NFT" delete table inet eco_guard 2>/dev/null || true
  elif IPT=$(command -v iptables || ([ -x /usr/sbin/iptables ] && echo /usr/sbin/iptables)); then
    "$IPT" -D FORWARD -i eth0 -j DROP 2>/dev/null || true
  fi
}

# Only the shared/console profile ('eth0-direct') gets the forward block; WAN mode clears it.
if [ "$CONNECTION_ID" = "eth0-direct" ] && [ "$2" != "down" ]; then apply_block; else remove_block; fi
SCR
chmod 755 "$DISP"
echo "  mode-aware eth0 guard dispatcher installed"

echo "== mDNS (avahi) so <hostname>.local resolves on the direct link =="
systemctl enable --now avahi-daemon >/dev/null 2>&1 || \
  echo "  (avahi-daemon not present — the fixed IP still works)"

echo "== re-evaluating eth0 (NM picks WAN first, falls back to direct) =="
# Bounce autoconnect so NM re-runs the priority order right now.
nmcli dev disconnect "$IFACE" >/dev/null 2>&1 || true
nmcli con up "$WAN" >/dev/null 2>&1 || nmcli con up "$DIRECT" >/dev/null 2>&1 || true

echo
echo "DONE. eth0 auto-selects:"
echo "  · plugged into a network (DHCP)  → Internet over Ethernet (preferred over LTE)"
echo "  · plugged into a PC (no DHCP)     → console at http://10.10.10.1/ (+ <hostname>.local)"
echo "  · LTE stays up as automatic failover"
