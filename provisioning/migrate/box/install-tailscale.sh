#!/bin/bash
# Install Tailscale from the official static arm64 tarball (transferred over SCP — no
# apt, no internet on the box beyond the tailnet control-plane handshake over LTE).
# Idempotent. Enrolls with a reusable, pre-authorized key and turns on Tailscale SSH.
#
#   install-tailscale.sh <tarball.tgz> <authkey> [hostname]
#
# Notes baked in from this box:
#  - RESI has nft only (no iptables); modern tailscaled auto-detects the nftables
#    backend, so no extra flag is needed here.
#  - --accept-dns=false: the box keeps its own resolver (MagicDNS would fight the
#    SIM/NM DNS and cost nothing we need).
#  - Tailscale SSH is intentionally NOT enabled: it intercepts port 22 and needs a
#    tailnet ACL rule (admin console) to authorize the tagged box for user nodes.
#    Instead we leave port 22 on the tailnet IP going to the box's real sshd, which
#    already accepts the ecoadmin key we installed — no admin-console step required.
set -euo pipefail
TGZ=${1:-/tmp/tailscale.tgz}
AUTHKEY=${2:-}
HOSTNAME_TS=${3:-$(hostname)}

echo "== /dev/net/tun present? =="
if [ ! -c /dev/net/tun ]; then
  modprobe tun 2>/dev/null || true
  [ -c /dev/net/tun ] || { echo "WARN: /dev/net/tun missing; tailscaled needs it"; }
fi

echo "== extracting tailscale static binaries =="
tmp=$(mktemp -d)
tar -xzf "$TGZ" -C "$tmp"
d=$(find "$tmp" -maxdepth 1 -type d -name 'tailscale_*_arm64' | head -1)
install -m 0755 "$d/tailscaled" /usr/local/bin/tailscaled
install -m 0755 "$d/tailscale"  /usr/local/bin/tailscale
install -m 0644 "$d/systemd/tailscaled.service"  /etc/systemd/system/tailscaled.service
install -m 0644 "$d/systemd/tailscaled.defaults" /etc/default/tailscaled
rm -rf "$tmp"
/usr/local/bin/tailscaled --version | head -1

# The shipped unit assumes /usr/sbin; our binary is in /usr/local/bin. Rewrite the
# two ExecStart/ExecStartPre paths to match.
sed -i 's#/usr/sbin/tailscaled#/usr/local/bin/tailscaled#g' /etc/systemd/system/tailscaled.service

echo "== enabling tailscaled =="
mkdir -p /var/lib/tailscale
systemctl daemon-reload
systemctl enable --now tailscaled
sleep 3

echo "== tailscale up =="
if [ -n "$AUTHKEY" ]; then
  tailscale up --authkey "$AUTHKEY" --accept-dns=false --hostname "$HOSTNAME_TS" --reset
else
  echo "no authkey passed; skipping 'up' (run manually)"
fi

echo "== status =="
tailscale status || true
echo "tailscale IPv4: $(tailscale ip -4 2>/dev/null || echo none)"
echo "== tailscale install DONE =="
