#!/bin/bash
# Install Docker Engine from the official static aarch64 tarball (transferred over
# SCP — no apt, no internet on the box). Idempotent. Then load the tb-gateway image
# from a gzipped `docker save` tarball. Both tarballs are uploaded to /tmp by the tool.
set -euo pipefail
TGZ=${1:-/tmp/docker-static.tgz}
IMG=${2:-/tmp/tbgw-image.tar.gz}

echo "== extracting docker static binaries =="
tar -xzf "$TGZ" -C /tmp
install -m 0755 /tmp/docker/* /usr/local/bin/
rm -rf /tmp/docker
/usr/local/bin/dockerd --version

echo "== systemd units (containerd + docker) =="
cat > /etc/systemd/system/containerd.service <<'U'
[Unit]
Description=containerd container runtime
After=network.target
[Service]
ExecStart=/usr/local/bin/containerd
Restart=always
Delegate=yes
KillMode=process
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
U
cat > /etc/systemd/system/docker.service <<'U'
[Unit]
Description=Docker Application Container Engine
After=containerd.service network.target
Requires=containerd.service
[Service]
# This box has nft only (no iptables); tb-gateway runs with --network host, so we
# disable Docker's bridge/NAT entirely (otherwise dockerd aborts: "iptables not found").
ExecStart=/usr/local/bin/dockerd --containerd=/run/containerd/containerd.sock --iptables=false --ip6tables=false --bridge=none
Restart=always
RestartSec=2
LimitNOFILE=1048576
Delegate=yes
[Install]
WantedBy=multi-user.target
U

getent group docker >/dev/null 2>&1 || groupadd docker
usermod -aG docker ecoadmin 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now containerd
systemctl enable --now docker
sleep 4
echo "== docker up? =="
docker version --format 'server {{.Server.Version}} {{.Server.Os}}/{{.Server.Arch}}'

echo "== loading tb-gateway image =="
gunzip -c "$IMG" | docker load
docker image ls thingsboard/tb-gateway
rm -f "$IMG" "$TGZ"
echo "== docker install + image load DONE =="
