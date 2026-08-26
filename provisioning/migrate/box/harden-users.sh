#!/bin/bash
# Disable the two factory RESI accounts once ecoadmin (key auth) is proven working.
# The RESI image ships `resi` (login/sudo, uid 1000) and `resivm` (runs RESIvmachine),
# BOTH with the same shared fleet password — so anyone who knows it can SSH into every
# unit. This locks their passwords and refuses SSH password login for them specifically.
#
# Safe + reversible:
#   * It NEVER touches the account that is running this script (ecoadmin under sudo).
#   * A locked password does not stop the account's services or cron jobs from running,
#     so the RESI stack still comes back intact after `eco-downgrade.sh`.
#   * Reverse per user with:  sudo passwd -u resi ; sudo passwd -u resivm
#     and remove /etc/ssh/sshd_config.d/eco-lock-resi.conf
# Idempotent: re-running just reports "already locked".
set -euo pipefail

me="$(logname 2>/dev/null || id -un || echo)"
locked=()
for u in resi resivm; do
  if ! id "$u" >/dev/null 2>&1; then echo "absent:  $u (nothing to do)"; continue; fi
  if [ "$u" = "$me" ]; then echo "SKIP:    $u is the current login — not locking myself out"; continue; fi
  st="$(passwd -S "$u" 2>/dev/null | awk '{print $2}')"
  if [ "$st" = "L" ]; then echo "already: $u password already locked"; locked+=("$u"); continue; fi
  if passwd -l "$u" >/dev/null 2>&1; then echo "locked:  $u password"; locked+=("$u"); else echo "WARN:    could not lock $u"; fi
done

# Deny SSH password/keyboard-interactive login for these two users only, leaving the
# global default (and ecoadmin's key auth) untouched.
DROPIN=/etc/ssh/sshd_config.d/eco-lock-resi.conf
if [ -d /etc/ssh/sshd_config.d ]; then
  want=$'Match User resi,resivm\n    PasswordAuthentication no\n    KbdInteractiveAuthentication no\n'
  if [ ! -f "$DROPIN" ] || [ "$(cat "$DROPIN")" != "$want" ]; then
    printf '%s' "$want" > "$DROPIN"
    chmod 644 "$DROPIN"
    if sshd -t 2>/dev/null; then
      systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
      echo "sshd:    password login disabled for resi,resivm"
    else
      rm -f "$DROPIN"
      echo "WARN:    sshd config test failed — drop-in reverted, passwords still locked"
    fi
  else
    echo "sshd:    drop-in already in place"
  fi
fi

echo "DONE (locked: ${locked[*]:-none})"
