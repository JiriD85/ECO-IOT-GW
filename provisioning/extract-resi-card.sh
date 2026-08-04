#!/usr/bin/env bash
# Mount the SD card image read-only and extract the old gateway configuration.
# Run in WSL:  sudo bash /mnt/c/Users/01ALP529/sdcard/extract-config.sh
set -euo pipefail

IMG=/mnt/c/Users/01ALP529/sdcard/sd-card.img
OUT=/mnt/c/Users/01ALP529/sdcard/extracted
ROOT=/mnt/sdroot
BOOT=/mnt/sdboot

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

mkdir -p "$ROOT" "$BOOT" "$OUT"

# Reuse an existing loop device for this image if there is one.
LOOP=$(losetup -j "$IMG" | cut -d: -f1 | head -1)
if [[ -z "$LOOP" ]]; then
  LOOP=$(losetup -Pf --show "$IMG")
fi
echo "loop device: $LOOP"

mountpoint -q "$ROOT" || mount -o ro "${LOOP}p2" "$ROOT"
mountpoint -q "$BOOT" || mount -o ro "${LOOP}p1" "$BOOT"
echo "mounted ${LOOP}p2 -> $ROOT (ro)"
echo "mounted ${LOOP}p1 -> $BOOT (ro)"

# ---------- discovery ----------
{
  echo "### os-release"
  cat "$ROOT/etc/os-release" 2>/dev/null || true
  echo
  echo "### hostname"
  cat "$ROOT/etc/hostname" 2>/dev/null || true
  echo
  echo "### home dirs"
  ls -la "$ROOT/home" 2>/dev/null || true
  echo
  echo "### /opt"
  ls -la "$ROOT/opt" 2>/dev/null || true
  echo
  echo "### /srv"
  ls -la "$ROOT/srv" 2>/dev/null || true
  echo
  echo "### enabled systemd units (multi-user.target.wants)"
  ls -la "$ROOT/etc/systemd/system/multi-user.target.wants" 2>/dev/null || true
  echo
  echo "### custom systemd units in /etc/systemd/system"
  ls -la "$ROOT/etc/systemd/system" 2>/dev/null || true
  echo
  echo "### docker containers on disk (image/container metadata dirs)"
  ls -la "$ROOT/var/lib/docker/containers" 2>/dev/null | head -40 || true
  echo
  echo "### thingsboard-gateway locations"
  ls -laR "$ROOT/etc/thingsboard-gateway" 2>/dev/null | head -80 || true
  echo
  echo "### python site-packages: thingsboard_gateway present?"
  find "$ROOT/usr/lib/python3"* "$ROOT/usr/local/lib/python3"* -maxdepth 2 -name 'thingsboard*' 2>/dev/null | head || true
  echo
  echo "### crontabs"
  cat "$ROOT/etc/crontab" 2>/dev/null || true
  ls -la "$ROOT/var/spool/cron/crontabs" 2>/dev/null || true
  echo
  echo "### serial / boot config"
  cat "$BOOT/config.txt" 2>/dev/null || cat "$BOOT/firmware/config.txt" 2>/dev/null || true
  echo
  echo "### cmdline.txt"
  cat "$BOOT/cmdline.txt" 2>/dev/null || true
} > "$OUT/00-discovery.txt" 2>&1
echo "wrote $OUT/00-discovery.txt"

# ---------- find candidate config files anywhere on the card ----------
echo "searching for gateway / modbus config files (this takes a minute)..."
find "$ROOT" \
    -path "$ROOT/proc" -prune -o \
    -path "$ROOT/sys" -prune -o \
    -path "$ROOT/var/lib/docker/overlay2" -prune -o \
    -path "$ROOT/usr/share" -prune -o \
    -path "$ROOT/usr/lib" -prune -o \
    -type f \( \
        -iname 'tb_gateway*' -o \
        -iname '*modbus*' -o \
        -iname 'docker-compose*' -o \
        -iname '*pflow*' -o -iname '*p-flow*' -o -iname '*d116*' \
    \) -print 2>/dev/null | awk 'NR<=400' > "$OUT/01-candidates.txt"
echo "wrote $OUT/01-candidates.txt ($(wc -l < "$OUT/01-candidates.txt") hits)"

# ---------- grep for device-name / register hints ----------
grep -rIl --exclude-dir=overlay2 --exclude-dir=proc --exclude-dir=sys \
     -iE 'd116|p-?flow' "$ROOT/etc" "$ROOT/home" "$ROOT/opt" "$ROOT/root" "$ROOT/srv" \
     2>/dev/null | awk 'NR<=100' > "$OUT/02-name-hits.txt" || true
echo "wrote $OUT/02-name-hits.txt"

# ---------- copy the interesting trees ----------
copy() {
  local src="$1"
  if [[ -e "$ROOT/$src" ]]; then
    mkdir -p "$OUT/rootfs/$(dirname "$src")"
    cp -a "$ROOT/$src" "$OUT/rootfs/$src" 2>/dev/null || true
    echo "  copied /$src"
  fi
}

echo "copying config trees..."
copy etc/thingsboard-gateway
copy etc/systemd/system
copy etc/os-release
copy etc/hostname
copy etc/hosts
copy etc/fstab
copy etc/crontab
copy etc/network
copy etc/dhcpcd.conf
copy etc/NetworkManager/system-connections
copy etc/wpa_supplicant
copy etc/openvpn
copy etc/wireguard
copy etc/docker
copy etc/udev/rules.d
copy etc/nginx/sites-available
copy var/spool/cron/crontabs
copy opt
copy srv
copy root
copy home

# boot partition
mkdir -p "$OUT/bootfs"
cp -a "$BOOT/." "$OUT/bootfs/" 2>/dev/null || true
echo "  copied bootfs"

# ---------- also copy any candidate file found outside those trees ----------
mkdir -p "$OUT/candidates"
while IFS= read -r f; do
  rel="${f#$ROOT/}"
  dest="$OUT/candidates/$rel"
  mkdir -p "$(dirname "$dest")"
  cp -a "$f" "$dest" 2>/dev/null || true
done < "$OUT/01-candidates.txt"
echo "  copied candidate files"

# ---------- container config (may hold the gateway's mounted config path) ----------
mkdir -p "$OUT/docker-containers"
for d in "$ROOT"/var/lib/docker/containers/*/; do
  [[ -d "$d" ]] || continue
  id=$(basename "$d")
  mkdir -p "$OUT/docker-containers/$id"
  cp -a "$d/config.v2.json" "$OUT/docker-containers/$id/" 2>/dev/null || true
  cp -a "$d/hostconfig.json" "$OUT/docker-containers/$id/" 2>/dev/null || true
done
echo "  copied docker container metadata"

# make everything readable from Windows / by the normal user
chmod -R a+rX "$OUT" 2>/dev/null || true

echo
echo "DONE. Extract is at C:\\Users\\01ALP529\\sdcard\\extracted"
echo "Image stays mounted read-only at $ROOT and $BOOT."
echo "To unmount later:  sudo umount $ROOT $BOOT && sudo losetup -d $LOOP"
