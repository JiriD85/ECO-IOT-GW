#!/bin/bash
# Stand down the RESI software stack IN PLACE (disable, never delete) so our stack
# can take the meter bus, ports, and boot. Fully reversible via the eco-downgrade.sh
# it writes. Records original state under /var/lib/eco-migrate.
#
# Safe to re-run. Does NOT touch: NetworkManager, ssh, snapd (ModemManager is a snap
# → LTE), or the eth0-direct console link.
set -uo pipefail
STATE=/var/lib/eco-migrate
mkdir -p "$STATE"
LOG="$STATE/standdown.log"
exec > >(tee -a "$LOG") 2>&1
echo "== ECO RESI stand-down $(date -u +%FT%TZ) =="

# 1. disable the @reboot cron that launches RESIvmachine (reversible: keep the original)
CRON=/var/spool/cron/crontabs/root
if [ -f "$CRON" ] && [ ! -f "$STATE/root.crontab.orig" ]; then cp "$CRON" "$STATE/root.crontab.orig"; fi
if crontab -l 2>/dev/null | grep -q 'RESIVMStartup'; then
  crontab -l 2>/dev/null | sed 's#^\(@reboot .*RESIVMStartup.*\)#\#ECO-disabled \1#' | crontab -
  echo "disabled @reboot RESIVMStartup in root crontab"
else
  echo "no active RESIVMStartup cron line (already disabled?)"
fi

# 2. stop the running RESIvmachine + its launcher
if pkill -f 'RESIvmachine_2_' 2>/dev/null; then echo "stopped RESIvmachine"; else echo "RESIvmachine not running"; fi
pkill -f 'RESIVMStartup.sh' 2>/dev/null || true
sleep 2

# 3. mask the RESI systemd services (record prior enable-state for downgrade)
MASKED="$STATE/masked.list"
[ -f "$MASKED" ] || : > "$MASKED"
for u in apache2.service ser2net.service pm2-resi.service grafana-server.service mariadb.service mosquitto.service snmpd.service; do
  if systemctl cat "$u" >/dev/null 2>&1; then
    st=$(systemctl is-enabled "$u" 2>/dev/null || echo unknown)
    systemctl disable --now "$u" >/dev/null 2>&1 || true
    systemctl mask "$u" >/dev/null 2>&1 || true
    grep -q "^$u " "$MASKED" || echo "$u $st" >> "$MASKED"
    echo "masked $u (was ${st})"
  else
    echo "skip $u (not present)"
  fi
done

# 4. write the reversal script
cat > /usr/local/sbin/eco-downgrade.sh <<'DG'
#!/bin/bash
# Reverse the ECO stand-down: unmask/re-enable RESI services + restore the cron.
set -uo pipefail
STATE=/var/lib/eco-migrate
if [ -f "$STATE/masked.list" ]; then
  while read -r u st; do
    [ -n "$u" ] || continue
    systemctl unmask "$u" 2>/dev/null || true
    [ "$st" = "enabled" ] && systemctl enable "$u" 2>/dev/null || true
    echo "restored $u ($st)"
  done < "$STATE/masked.list"
fi
if [ -f "$STATE/root.crontab.orig" ]; then crontab "$STATE/root.crontab.orig" && echo "restored root crontab (RESIvmachine @reboot)"; fi
echo "RESI stack restored. Reboot to bring it fully back up."
DG
chmod 755 /usr/local/sbin/eco-downgrade.sh
echo "downgrade script: /usr/local/sbin/eco-downgrade.sh"

# 5. verify the bus + ports are released
echo "== verify =="
sleep 1
if fuser /dev/ttyACM0 >/dev/null 2>&1; then echo "WARN: /dev/ttyACM0 STILL held: $(fuser -v /dev/ttyACM0 2>&1 | tail -1)"; else echo "OK: /dev/ttyACM0 is FREE"; fi
echo "remaining listeners on 80/443/1883/3306/502/3000:"
ss -ltnp 2>/dev/null | grep -E ':80 |:443 |:1883 |:3306 |:502 |:3000 ' || echo "  none"
echo "== stand-down done =="
