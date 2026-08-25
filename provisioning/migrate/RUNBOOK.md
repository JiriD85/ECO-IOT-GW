# RESI → ECO in-place migration — verified runbook

Ground-truth procedure for converting a RESI Doctor-Kit gateway to the ECO stack
**in place** (RESI disabled, not wiped; fully reversible), driven from a Windows
laptop over a direct Ethernet cable. Every step here was executed and verified live
on **DBKIT24EU-0010** (HWID `1F0022000D57435535333920`). This is also the spec the
`tui.js` wizard implements.

> **Doing an install?** Follow [ENGINEER-GUIDE.md](ENGINEER-GUIDE.md) instead — a
> step-by-step tutorial for migrating a unit that is still running its factory RESI
> software, using the wizard. This runbook is the reference for *why* each step exists.

## The wizard — `node tui.js`

`node tui.js --kit <DBKIT..> [--host <addr>] [--yes] [--skip-artifacts] [--skip-tb]`

A guided, line-based installer that runs the phases below in order. It is a
**controller** over the proven pieces (`setup-direct-ethernet.sh`, `migrate-box.js`
TB logic, `box/*.sh`, `build-gw-config.js`), not new install logic. Key behaviours:

- **Auto-skip.** Every phase has an idempotency probe; a phase it detects is already
  done prints `⏭ already done` and is skipped. A re-run against a finished box skips
  everything except the read-only config-regen and verify. So the same wizard both
  provisions a box still running its factory RESI software, and safely re-runs against an
  already-migrated one.
- **Bootstrap.** Finds the box automatically: `ecoadmin@10.10.10.1` (key, already
  provisioned) → `resi@10.10.10.1` (password) → fresh box via `--host` / `RESI-C4.local`.
  Switches from the `resi` password to the `ecoadmin` key the moment phase 3 installs it.
- **Gates.** Destructive-ish phases (TB write, RESI stand-down) ask before running
  unless `--yes`. Everything streams live; a failed phase asks whether to continue.
- **Bus safety.** The scan phase refuses to probe the meter bus while `tb-gateway`
  holds it (a concurrent open corrupts the live bus) — it keeps the cached units.

The numbered phases that follow are exactly what the wizard executes.

> Outcome achieved: RESI stack masked; our tb-gateway (Docker) reads the P-Flow bus
> and publishes to `lb-mqtt.pke-iot.expert`; telemetry lands on the fleet device
> entities `ECO_<hwid>_PF1..PF4 / _TS1 / _TS2` with the GW-profile calculated fields
> running; survives reboot; SIM data cost ≈ MQTT telemetry only.

---

## 0. Model & prerequisites

- **Tool location:** `provisioning/migrate/` (repo root `ECO-IOT-GW`, pushes to GitHub).
- **Config:** copy `.env.example` → `.env` (gitignored) and fill in. `.env` is the
  ONLY user config; `cache/` (artifacts) and `out/` (per-device secrets) are gitignored.
- **Two-stage SSH auth:** bootstrap as `resi` with the fleet default password (`BOX_SSH_PASSWORD` in `.env`)
  (verified default for `resi` and `root`), then install `ecoadmin` + our key and use
  silent key auth for everything after.
- **Host-key checking is OFF** for the box (`StrictHostKeyChecking=no`,
  `UserKnownHostsFile=/dev/null`): the direct cable is physically controlled and the
  fixed IP `10.10.10.1` is reused across every unit (different host key each time).
- **Per-box data is discovered live** (present meter units, the meter-bus by-id path);
  fixed data (register map, unit IDs, temp mapping) comes from `device-maps.js` /
  the site file, firmware-ground-truthed.

### Fleet / box facts (DBKIT24EU-0010)
- ThingsBoard asset `DBKIT24EU-0010` → 8 `Contains` devices: `_gw`, `_PF1..4`, `_TS1..3`.
- `_gw` credentials are **`MQTT_BASIC`** (clientId/username/password) — the fleet MQTT model.
- Meters: **P-Flow D116**, FC03 holding regs, units **88 / 80 / 81 / 82** (PF1..PF4),
  **mixed-endian** (floats BIG/BIG, counters BIG/LITTLE → 2 slaves per meter).
- Temps **TS1/TS2**: onboard C4 AIOX read as **Modbus unit 255, FC04**, on the *same*
  meter bus; slot0/reg0=TS1, slot1/reg1=TS2, °C = int16/10. `_TS3` is a stray (no sensor).
- **Meter bus = `/dev/ttyACM2`** (RESI's `ser2net` on `ttyACM0` is the C4 *console*,
  not the meters; `ttyUSB0-3` are the cellular modem, driver `option`).

---

## Phase 1 — Networking (stable console link)

Establish a reboot-stable direct-cable link so every later step is reliable
(link-local IPv6 flaps badly).

**Run on the box** (`provisioning/setup-direct-ethernet.sh`, pushed + run over the
initial link-local SSH, **detached** because it drops eth0 when it switches over):
- eth0 → `10.10.10.1/24`, NetworkManager `ipv4.method shared` (its dnsmasq leases the
  laptop a `10.10.10.x` address), avahi for `<hostname>.local`.
- **Blocks SIM→cable passthrough** with an nft table (`eco_guard` / hook forward
  priority -150, `iifname eth0 drop`) + an NM dispatcher to reassert it.

**Gotchas baked in:** RESI has **nft only, no iptables** — the block auto-detects the
backend. `nft` reserves the token `fwd`, so the chain is named `block_cable_fwd`. The
laptop needs a DHCP renew (bounce the adapter) to pick up `10.10.10.x`.

**Verify:** laptop gets `10.10.10.x`; `ssh ecoadmin@10.10.10.1` works; on the box
`nft list table inet eco_guard` shows the drop rule.

---

## Phase 2 — ThingsBoard (reversible; independent of the box)

`node migrate-box.js --kit DBKIT24EU-0010 --phase tb --apply`

1. **Guardrail:** abort if the kit resolves to > 10 device entities (misconfig signal;
   override `--force`, tune `ECO_MAX_KIT_DEVICES`).
2. Reprofile `_gw` → **`ECO GW`** + `additionalInfo.gateway=true`.
3. Reprofile `_PF1..4` → **`P-Flow D116 GW`**, `_TS1..2` → **`Temperature Sensor GW`**
   (enables the profiles' 10 calculated fields; `_TS3` left as-is).
4. **Capture `_gw`'s MQTT_BASIC credentials** → `out/<kit>.gw-mqtt.json` (gitignored)
   — the box's tb-gateway authenticates with these.
5. Writes a **cumulative** `out/<kit>.tb-revert.json`; undo with
   `node migrate-box.js --kit <kit> --revert-tb`.

**Verify:** re-read shows the new profiles + gateway flag (the tool does this).

---

## Phase 3 — Box: ecoadmin + key

`ecoadmin.sh` (tool scps the `.pub` to `/tmp/eco-authorized_key`, runs as root via the
`resi` bootstrap): creates `ecoadmin` (groups sudo/dialout/gpio/i2c/spi/adm), installs
`authorized_keys`, passwordless sudo. **Verify:** `ssh -i <key> ecoadmin@10.10.10.1`
+ `sudo -n id` → root. All later steps use ecoadmin key auth.

---

## Phase 4 — Box: stand down RESI (reversible)

`standdown-resi.sh` (as root):
1. Disable the `@reboot` root-cron that launches RESIvmachine (comment it; back up the
   original crontab to `/var/lib/eco-migrate/root.crontab.orig`).
2. Kill the running `RESIvmachine_2_*.exe` (started from `/etc/init.d/RESIVMStartup.sh`).
3. `systemctl disable --now` + `mask`: `apache2 ser2net pm2-resi grafana-server
   mariadb mosquitto snmpd` (records prior enable-state to `masked.list`).
   **Never mask `snapd`** — ModemManager is a snap → LTE.
4. Write `/usr/local/sbin/eco-downgrade.sh` (unmask/re-enable + restore crontab).

**Verify (via `/proc/*/exe`, NOT `pgrep -f` which self-matches):** RESIvmachine not
running; `/dev/ttyACM2` free; ports 80/443/1883/3306/502 released.

---

## Phase 5 — Discover the live bus

Bus is free now, so scan it (`ecoadmin` is in `dialout`, no sudo needed):
- `scan-modbus.py --port /dev/ttyACM2 --baudrate 9600 --timeout 0.12` (probe-only,
  no `--units`, tight timeout — full 1–247 sweep must finish; `--units` does a slow
  full read per unit). Records which PF units actually respond (PF1=88 confirmed;
  PF2–4 respond only when their expansion kits are wired).
- `aiox-modbus-probe.py --port /dev/ttyACM2` → unit 255 FC04, confirm °C = /10.
- Resolve the meter bus's **stable by-id path**:
  `/dev/serial/by-id/usb-RESI_RESI_RPICM4_<serial>-if04` (interface `if04`), so a
  reboot renumbering `ttyACMx` can't break it.

**Rule:** deploy the connector with **only the units that responded**. Unwired slaves
make tb-gateway's modbus connector hit `CLOSING CONNECTION` and starve the wired ones.

---

## Phase 6 — Artifacts on the laptop (over office internet, → SCP)

- **Docker engine:** `curl` the official static aarch64 tarball
  (`download.docker.com/linux/static/stable/aarch64/docker-<ver>.tgz`, ~74 MB) → `cache/`.
- **tb-gateway image (arm64):** `docker save` fails on Docker Desktop's containerd store
  for a foreign arch, so pull it with **crane run as a throwaway container**:
  `docker run --rm -v <cache>:/out gcr.io/go-containerregistry/crane pull
  --platform linux/arm64 thingsboard/tb-gateway:3.7-stable /out/tbgw.tar` → gzip (~92 MB).
- Both wired into `.env` (`DOCKER_STATIC_TGZ`, `TBGW_IMAGE_TAR`). SIM cost = 0.

---

## Phase 7 — Box: install Docker + load image

`install-docker-static.sh` (scp both tarballs first): extract static binaries to
`/usr/local/bin`, systemd `containerd` + `docker` units, `docker load` the image.

**Critical:** this box has nft only, so dockerd is started with
**`--iptables=false --ip6tables=false --bridge=none`** (otherwise it aborts: *bridge
driver ... iptables not found*). We only ever use `--network host`, so no bridge needed.

**Verify:** `docker version` → `linux/arm64`; `docker image ls` shows `tb-gateway`.

---

## Phase 8 — Build the gateway config

`build-gw-config.js <kit> <site.json> [presentUnitsCsv]` with
`ECO_MODBUS_PORT=/dev/meterbus` (set `MSYS_NO_PATHCONV=1` in git-bash so `/dev/...`
isn't path-mangled). Produces `out/<kit>/config/`:
- `modbus.json` = `buildModbusConnector(site)` filtered to present units + temps,
  `port=/dev/meterbus`.
- `tb_gateway.json` = local config, `remoteConfiguration:false`, security
  **`usernamePassword`** from the captured `_gw` creds (clientId/username/password),
  one modbus connector.

Site file (`sites/DBKIT24EU-0010.json`) declares **all four** PF + TS1/TS2 with the fast
serial tuning (`timeout:2, retries:1, retryOnEmpty:false`); the deploy filters to wired.

---

## Phase 9 — Box: deploy tb-gateway

- `scp` `tb_gateway.json` + `modbus.json` to `/opt/eco/tb-gateway/config/`.
- **Drop `/opt/eco/tb-gateway/config/.firstlaunch`** — the image's `start-gateway.sh`
  copies its *default* configs into the volume on first launch (clobbering ours) unless
  this marker exists.
- `docker run -d --name tb-gateway --restart unless-stopped --network host
  --device /dev/serial/by-id/...-if04:/dev/meterbus
  -v /opt/eco/tb-gateway/config:/thingsboard_gateway/config
  -v /opt/eco/tb-gateway/logs:/thingsboard_gateway/logs thingsboard/tb-gateway:3.7-stable`
  — the by-id → `/dev/meterbus` mapping is what makes the serial device reboot-stable.

---

## Phase 10 — Verify telemetry

Query `GET /api/plugins/telemetry/DEVICE/<pf1Id>/values/timeseries`. **Look at the
canonical keys** (`T_flow_C`, `Vdot_m3h`, `V_m3`, `E_th_heating_kWh`, `runtime_pct`),
NOT the old RESI-style `CHC_*` keys (those are stale leftovers). Fresh (<pollPeriod)
values on `ECO_…_PF1` + `auxT2_C` on `_TS2` = success. `auxT1_C=-999` = open channel
(no sensor), expected until RTDs wired. Confirm `CLOSING CONNECTION` count = 0 in logs.

---

## Phase 11 — Reboot persistence (verified)

`systemctl reboot`; wait for `10.10.10.1`. Confirm: RESIvmachine NOT running
(`/proc/*/exe`, not `pgrep -f`), RESI services inactive/masked, `docker` active,
tb-gateway container Up, meter-bus by-id present, telemetry resumes on its own.

---

## Phase 12 — Tailscale (verified)

`box/install-tailscale.sh <tarball> <authkey> [hostname]` (scp the static arm64
tarball from `pkgs.tailscale.com/stable/tailscale_<ver>_arm64.tgz` → `cache/` first):
extracts `tailscaled`/`tailscale` to `/usr/local/bin`, rewrites the shipped unit's
`/usr/sbin` paths, enables `tailscaled`, then
`tailscale up --authkey <TS_AUTHKEY> --accept-dns=false --hostname <name> --reset`.

- **Tailscale SSH is intentionally OFF.** `--ssh` makes tailscaled intercept port 22
  and reject unless a tailnet **ACL rule** (admin console) authorizes the tagged box
  for user nodes — the closed session shows as `Connection closed` right after the
  TCP connect. Leaving it off lets port 22 pass to the box's real `sshd`, which the
  `ecoadmin` key already opens — no admin-console step.
- `--accept-dns=false` keeps the box's own resolver (MagicDNS would fight SIM/NM DNS).

**Verify:** `tailscale ip -4` on the box; from the laptop `ssh -i <key>
ecoadmin@<ts-ip>` works and `http://<ts-ip>/` loads the console **authenticated with
no prompt** (tailnet identity).

### Phase 12a — laptop default-route fix (REQUIRED, or the laptop loses Tailscale)
NM shared-mode dnsmasq hands the plugged-in laptop a **default route + DNS** pointing
at the box (DHCP options 3/6). But cable→SIM forwarding is blocked, so a laptop that
follows that route loses Internet **and its own Tailscale drops** (can't reach the
coordination server). `setup-direct-ethernet.sh` now drops
`/etc/NetworkManager/dnsmasq-shared.d/eco-no-gateway.conf` (`dhcp-option=3` /
`dhcp-option=6` empty) so the box advertises **no gateway/DNS** — the laptop keeps its
office/WiFi default route and reaches the box only via the directly-connected
`10.10.10.0/24`. After applying, **renew the laptop's cable adapter** (`ipconfig
/release` + `/renew`) to drop any stale default route it already installed.

---

## Phase 13 — Web console (verified)

FastAPI backend (systemd `eco-iot-gw-backend`) **serving the built Vue SPA directly**
(no nginx). `box/install-webconsole.sh <backend.tgz> <wheelhouse.tgz> <dist.tgz>`:

1. **SIM-free deps.** Frontend `npm run build` on the laptop → `dist/`. Python deps
   from an **arm64 wheelhouse** built on the laptop in a `python:3.11` container
   (`pip download --only-binary=:all: --platform manylinux_2_17_aarch64
   --platform manylinux_2_28_aarch64 --python-version 3.11 --abi cp311`), scp'd over.
2. venv with **`--system-site-packages`** (reuses the box's `psutil`/`pyserial`/
   `cryptography` — no compiler); `pip install --no-index --find-links wheelhouse`.
   **`netifaces`/`pyroute2` omitted** (no arm64 wheel; both import-guarded in the
   backend, so only the network-failover page degrades).
3. Backend added `main.py` **SPA static mount** (`ECO_FRONTEND_DIST`, default
   `/opt/eco/webui/dist`): serves real files, falls back to `index.html`, keeps `/api`
   JSON 404s. Registered last so `/api/*` routers win.
4. **Per-device secrets** via `setup-secrets.sh` **before** first start (boot guard
   refuses default JWT/AES on a provisioned device).
5. systemd unit runs `uvicorn app.main:app --host 0.0.0.0 --port 80` as **root**
   (reads `/etc/shadow` for on-site login + docker socket for Meters) — documented
   tech-debt. Port 80 is free (apache2 masked). `0.0.0.0` = reachable on both the
   cable IP and the tailnet IP.

**Auth with no reverse proxy:** `security/tailscale_identity._peer_ip` falls back to
`request.client.host`, so the socket peer IP classifies correctly — `100.64/10` →
tailnet (auto-admin, no login), `10.10.10.x` → on-site (needs `ecoadmin` login). The
`ecoadmin` **Linux** password is set with `chpasswd` and recorded in
`out/<kit>.secrets.json` (gitignored).

**Meters live values need connector `logLevel: DEBUG`** — `meters_service` decodes by
pairing the DEBUG `Reading N registers…` / `Read with result…` lines; at INFO the page
shows devices as `pending` with no readings. `logLevel` must go **inside**
`configurationJson` (i.e. into `modbus.json`), not on the connector wrapper.

**Verify (live on DBKIT24EU-0010):** `http://<ts-ip>/` = authenticated dashboard
(Modem/ThingsBoard/Internet Connected, `tb-gateway` running); `http://10.10.10.1/` =
anonymous, `ecoadmin` login → token → reads 200; Meters shows PF1 `T_flow_C`,
`V_m3`, `E_th_*` and TS2 `°C` (TS1 `-999` = open channel, expected).

---

## Reversal

`sudo /usr/local/sbin/eco-downgrade.sh` (unmask RESI + restore cron) then reboot; and
`node migrate-box.js --kit <kit> --revert-tb` (restore TB profiles). For a full board
rollback that box's own SD image can be re-flashed (`win/Restore-Card.ps1`) - card
images are per-box and must never be written onto a different unit.

---

## Gotchas reference (things that cost time — encode them in the TUI)

| Symptom | Cause / fix |
|---|---|
| SSH to box flaps / drops | link-local IPv6; fix = Phase 1 → stable `10.10.10.1` |
| host key "REMOTE HOST CHANGED" | `10.10.10.1` reused per box; `StrictHostKeyChecking=no` + `/dev/null` known_hosts |
| scan finds nothing on `ttyACM0` | wrong port; meter bus is `ttyACM2`; `ttyUSB*` = modem |
| dockerd won't start ("iptables not found") | nft-only box; `--iptables=false --bridge=none` |
| `docker save` fails (digest not found) | Docker Desktop containerd + foreign arch; use `crane pull` |
| gateway connects to `thingsboard.cloud` | image clobbered our config; add `.firstlaunch` marker |
| MQTT "Bad user name or password" (134) | `_gw` is MQTT_BASIC → security `usernamePassword`, not accessToken |
| PF1 stale while TS fresh | 3 unwired meters cycle the bus (`CLOSING CONNECTION`); deploy only wired units |
| PF1 telemetry "missing" | it's under **canonical** keys (`T_flow_C`…), not `CHC_*` |
| serial port changes on reboot | pin via `/dev/serial/by-id/...-if04:/dev/meterbus` |
| `pgrep -f RESIvmachine` says running | self-match; check `/proc/*/exe` instead |
| `free`/`df` parse empty | German locale; `LC_ALL=C` |
| `pip install` refused | Debian PEP668; `--break-system-packages` |
| `/dev/meterbus` becomes `C:/Program Files/Git/...` | git-bash path mangling; `MSYS_NO_PATHCONV=1` |
| laptop Tailscale drops when cable plugged in | box's DHCP pushed a default route; suppress via `dnsmasq-shared.d` opt 3/6 + renew laptop adapter (Phase 12a) |
| Tailscale SSH `Connection closed` after connect | `--ssh` needs an admin-console ACL for the tagged box; leave it off, use real `sshd` + ecoadmin key |
| Meters page shows devices `pending`, no readings | connector at INFO; set `logLevel: DEBUG` **inside** `configurationJson` (modbus.json) |
| Meters `values` empty in raw JSON | field is `readings` (list of `{tag,value,unit}`), not `values` |
