#!/bin/bash
# Create the ecoadmin login with our SSH key + passwordless sudo, so all further
# steps use silent key auth (independent of the RESI 'resi' account). Idempotent.
# The public key is read from /tmp/eco-authorized_key (uploaded by the tool).
set -euo pipefail
U=ecoadmin
KEYFILE=/tmp/eco-authorized_key
[ -f "$KEYFILE" ] || { echo "ERROR: $KEYFILE not found (tool should scp the .pub there)"; exit 1; }

id "$U" >/dev/null 2>&1 || useradd -m -s /bin/bash -c "ECO gateway admin" "$U"
for g in sudo dialout gpio i2c spi adm; do getent group "$g" >/dev/null 2>&1 && usermod -aG "$g" "$U" || true; done

install -d -m 700 -o "$U" -g "$U" "/home/$U/.ssh"
# append (dedup) our key
touch "/home/$U/.ssh/authorized_keys"
grep -qxF "$(cat "$KEYFILE")" "/home/$U/.ssh/authorized_keys" || cat "$KEYFILE" >> "/home/$U/.ssh/authorized_keys"
chmod 600 "/home/$U/.ssh/authorized_keys"
chown -R "$U:$U" "/home/$U/.ssh"

echo "$U ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/010_ecoadmin-nopasswd
chmod 440 /etc/sudoers.d/010_ecoadmin-nopasswd
rm -f "$KEYFILE"
echo "OK ecoadmin ready: $(id "$U")"
