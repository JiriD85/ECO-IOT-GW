#!/bin/bash
# ECO in-place RESI -> ECO conversion, phase 1: get a foothold, stand RESI down.
#
# Runs ONCE as root on first boot, launched by systemd.run= in cmdline.txt
# (systemd-run-generator, confirmed present on the RESI image). Staged onto the
# FAT boot partition, which Windows can write directly - no ext4 tooling needed.
#
# Phase 1 deliberately does NOT touch the resi/root passwords: if the injected
# key were wrong we would be locked out of a unit we cannot reach any other way.
# Locking them is phase 2, after ecoadmin SSH is confirmed working.
#
# Everything it disables is recorded so eco-downgrade.sh can put it all back.

set +e   # never abort mid-conversion; log and keep going

BOOTDIR=/boot/firmware
LOG="$BOOTDIR/eco-firstrun.log"          # on FAT, so it is readable from Windows
STATEDIR=/var/lib/eco-migrate
MASKED="$STATEDIR/masked.list"

# make sure we can write: at kernel-command-line.target these may not be ready
mount -o remount,rw / 2>/dev/null
mount "$BOOTDIR" 2>/dev/null

log() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" | tee -a "$LOG"; }

log "=== ECO firstrun phase 1 starting on $(hostname) ==="
log "kernel: $(uname -r)   os: $(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | tr -d '\"')"

mkdir -p "$STATEDIR"

# ---------------------------------------------------------------- 1. our admin
ECOUSER=ecoadmin
if id "$ECOUSER" >/dev/null 2>&1; then
  log "user $ECOUSER already exists - leaving it alone"
else
  useradd -m -s /bin/bash -c "ECO gateway admin" "$ECOUSER" \
    && log "created user $ECOUSER" \
    || log "ERROR: useradd $ECOUSER failed"
fi
# groups needed for serial (dialout), gpio/i2c/spi, and root via sudo
for g in sudo dialout gpio i2c spi adm; do
  getent group "$g" >/dev/null 2>&1 && usermod -aG "$g" "$ECOUSER" 2>/dev/null
done
log "groups: $(id -nG "$ECOUSER" 2>/dev/null)"

# passwordless sudo, matching how RESI already treats its own user
echo "$ECOUSER ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/010_ecoadmin-nopasswd
chmod 440 /etc/sudoers.d/010_ecoadmin-nopasswd
log "sudo: /etc/sudoers.d/010_ecoadmin-nopasswd written"

# authorized_keys, staged next to this script on the FAT partition
if [ -f "$BOOTDIR/eco_authorized_keys" ]; then
  install -d -m 700 -o "$ECOUSER" -g "$ECOUSER" "/home/$ECOUSER/.ssh"
  install -m 600 -o "$ECOUSER" -g "$ECOUSER" \
    "$BOOTDIR/eco_authorized_keys" "/home/$ECOUSER/.ssh/authorized_keys"
  log "installed authorized_keys ($(wc -l < "$BOOTDIR/eco_authorized_keys") key(s))"
else
  log "WARNING: $BOOTDIR/eco_authorized_keys not found - no key installed!"
fi

# ------------------------------------------------- 2. stand the RESI stack down
# NOTE: snapd is deliberately NOT in this list - ModemManager is a snap on this
# image, so disabling snapd would take the LTE modem down with it.
RESI_UNITS="
apache2.service
ser2net.service
pm2-resi.service
grafana-server.service
mariadb.service
snmpd.service
wayvnc.service
mosquitto.service
cups.service
cups-browsed.service
cups.path
avahi-daemon.service
triggerhappy.service
"

: > "$MASKED"
for u in $RESI_UNITS; do
  if systemctl list-unit-files "$u" >/dev/null 2>&1 && \
     [ -n "$(systemctl list-unit-files "$u" 2>/dev/null | sed -n '2p')" ]; then
    state=$(systemctl is-enabled "$u" 2>/dev/null)
    systemctl disable --now "$u" >/dev/null 2>&1
    systemctl mask "$u"          >/dev/null 2>&1
    echo "$u $state" >> "$MASKED"
    log "masked $u (was: ${state:-unknown})"
  else
    log "skip $u (not present)"
  fi
done

# desktop/VNC stack: drop to multi-user so we stop paying for X
prev_target=$(systemctl get-default 2>/dev/null)
echo "DEFAULT_TARGET $prev_target" >> "$MASKED"
systemctl set-default multi-user.target >/dev/null 2>&1 \
  && log "default target: $prev_target -> multi-user.target"

# make sure the things we rely on stay up
for u in ssh.service NetworkManager.service; do
  systemctl enable "$u" >/dev/null 2>&1
  log "ensured enabled: $u"
done

# ----------------------------------------------------- 3. write the way back
cat > /usr/local/sbin/eco-downgrade.sh <<'DOWNGRADE'
#!/bin/bash
# Undo the ECO conversion: unmask and re-enable everything phase 1 stood down.
set +e
MASKED=/var/lib/eco-migrate/masked.list
[ -f "$MASKED" ] || { echo "nothing to restore ($MASKED missing)"; exit 1; }
while read -r unit state; do
  case "$unit" in
    DEFAULT_TARGET) [ -n "$state" ] && systemctl set-default "$state"; continue ;;
    ''|\#*) continue ;;
  esac
  systemctl unmask "$unit"
  [ "$state" = "enabled" ] && systemctl enable "$unit"
  echo "restored $unit (state: $state)"
done < "$MASKED"
echo "Done. Reboot to bring the RESI stack back up."
DOWNGRADE
chmod 755 /usr/local/sbin/eco-downgrade.sh
log "downgrade path: /usr/local/sbin/eco-downgrade.sh (reads $MASKED)"

# --------------------------------------------------------- 4. report + cleanup
log "--- ip addresses ---"
ip -4 -o addr show scope global 2>/dev/null | awk '{print "    "$2" "$4}' | tee -a "$LOG"
log "--- listening ports ---"
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | sed -n '2,20p' | tee -a "$LOG"
log "--- serial devices ---"
ls -l /dev/ttyACM* /dev/ttyAMA* /dev/ttyUSB* /dev/serial* 2>/dev/null | tee -a "$LOG"

# run once only: strip our systemd.run args and remove ourselves
sed -i 's| systemd\.run[^ ]*||g' "$BOOTDIR/cmdline.txt" 2>/dev/null
log "cmdline.txt cleaned: $(cat "$BOOTDIR/cmdline.txt")"
rm -f "$BOOTDIR/firstrun.sh"

log "=== phase 1 complete - rebooting into a RESI-quiet system ==="
sync
exit 0
