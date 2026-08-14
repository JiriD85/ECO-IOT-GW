#!/usr/bin/env bash
#
# setup-secrets.sh — generate the gateway's per-device backend secrets.
#
# The backend signs session tokens (JWT_SECRET) and encrypts stored data
# (AES_KEY). Shipped defaults are the SAME on every device and live in the
# source tree, so a device left on them can have its login token forged by
# anyone with the repo. This writes unique random values into
# /etc/eco-iot-gw/secrets.env, which the backend loads on boot.
#
# A full install.sh run already does this. Use THIS script on a device that was
# set up via the lean/manual path (so install.sh's generate_secrets never ran),
# or to repair a device found running on the defaults. Idempotent: it will NOT
# rotate an already-unique secret (that would log everyone out) unless --force.
#
# The backend refuses to start on a provisioned device while these are still the
# defaults (see backend assert_secure_secrets), so run this before/with deploy.
#
# NOTE: this handles only the backend app secrets. The `ecoadmin` LOGIN password
# is a Linux account (set with `passwd` and recorded in provisioning/out/), a
# separate concern this script does not touch.
#
# Usage:  sudo ./setup-secrets.sh [--force]
set -euo pipefail

CONFIG_DIR="/etc/eco-iot-gw"
SECRET_FILE="$CONFIG_DIR/secrets.env"
BACKEND_USER="eco-iot-gw"          # matches install.sh; falls back to root
FORCE=0

# shipped placeholders the backend recognises as "insecure default"
DEFAULT_JWT_SECRET="change-me-in-production"
DEFAULT_AES_KEY="change-me-in-production-32bytes!"

[[ "${1:-}" == "--force" ]] && FORCE=1

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (use sudo)" >&2
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl not found — cannot generate secrets" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"
chmod 750 "$CONFIG_DIR"
touch "$SECRET_FILE"

# current value of KEY in the env file (empty if unset)
cur() { grep -E "^$1=" "$SECRET_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true; }

# does KEY currently hold a real (non-empty, non-default) secret?
is_secure() {
  local key="$1" def="$2" val
  val="$(cur "$key")"
  [[ -n "$val" && "$val" != "$def" ]]
}

# set KEY=VALUE in the env file, replacing any existing line, preserving the rest
set_kv() {
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  grep -vE "^$key=" "$SECRET_FILE" > "$tmp" 2>/dev/null || true
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  cat "$tmp" > "$SECRET_FILE"
  rm -f "$tmp"
}

rotate_if_needed() {
  local key="$1" def="$2" gen="$3"
  if [[ $FORCE -eq 0 ]] && is_secure "$key" "$def"; then
    echo "  $key: already unique — kept (use --force to rotate)"
    return
  fi
  set_kv "$key" "$gen"
  echo "  $key: set to a new random value"
}

echo "== ensuring per-device backend secrets in $SECRET_FILE =="
rotate_if_needed JWT_SECRET "$DEFAULT_JWT_SECRET" "$(openssl rand -hex 32)"
rotate_if_needed AES_KEY    "$DEFAULT_AES_KEY"    "$(openssl rand -hex 32)"

# lock the file down for whoever the backend runs as
chmod 600 "$SECRET_FILE"
if id "$BACKEND_USER" >/dev/null 2>&1; then
  chown "$BACKEND_USER:$BACKEND_USER" "$SECRET_FILE"
else
  chown root:root "$SECRET_FILE"   # bench: backend still runs as root
fi

echo
echo "DONE. Restart the backend to load them:"
echo "  sudo systemctl restart eco-iot-gw-backend"
echo "(secret values are intentionally not printed — they never need to leave the device)"
