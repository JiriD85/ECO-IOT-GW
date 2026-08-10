#!/usr/bin/env bash
# Enroll an ECO gateway into the Tailscale tailnet with Tailscale SSH.
# Run ON the gateway (or over SSH) as root/sudo.
#
#   sudo ./enroll-gateway.sh <TS_AUTHKEY> [hostname]
#
# <TS_AUTHKEY> : a TAGGED auth key (tag:eco-gw). For the fleet, mint a UNIQUE single-use
#               key per device from the OAuth client (see README) — never bake one shared
#               key into customer images.
# [hostname]  : tailnet node name; defaults to eco-gw-<board-serial>.
set -euo pipefail

AUTHKEY="${1:?usage: enroll-gateway.sh <TS_AUTHKEY> [hostname]}"

# Derive a stable per-device hostname from the CM4/board serial if not given.
default_host() {
  local s
  s="$(tr -d '\000' < /proc/device-tree/serial-number 2>/dev/null || true)"
  [ -z "$s" ] && s="$(awk '/Serial/{print $3}' /proc/cpuinfo 2>/dev/null | tail -1)"
  [ -z "$s" ] && s="$(hostname)"
  echo "eco-gw-${s}"
}
HOSTNAME_ARG="${2:-$(default_host)}"

# Install Tailscale if missing (official install script; ARM/Debian supported).
if ! command -v tailscale >/dev/null 2>&1; then
  echo "[*] installing tailscale ..."
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled

# Join: tagged identity, Tailscale SSH on, stable hostname.
# --accept-dns=false: do NOT let MagicDNS override the gateway's resolver (the SIM path
#   is sensitive to DNS changes; telemetry must keep resolving the MQTT broker).
echo "[*] tailscale up as ${HOSTNAME_ARG} ..."
tailscale up \
  --authkey="${AUTHKEY}" \
  --advertise-tags=tag:eco-gw \
  --ssh \
  --hostname="${HOSTNAME_ARG}" \
  --accept-dns=false \
  --accept-routes=false

echo "[*] status:"
tailscale status || true
tailscale ip -4 || true
echo "[✓] enrolled as ${HOSTNAME_ARG}. Reachable at that MagicDNS name by group:ops via Tailscale SSH."
