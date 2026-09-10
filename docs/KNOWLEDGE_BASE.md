# ECO-IOT-GW — Operational Knowledge Base

This is the consolidated, hard-won operational knowledge for turning a factory **RESI
Doctor-Kit** (Raspberry Pi CM4 on a RESI C4 carrier) into an **ECO ThingsBoard gateway**,
and for running that gateway in the field. Much of this is **not derivable from the code** and
silently corrupts data or breaks connectivity if guessed — it was recovered from the original
RESI SD card, live hardware, and field debugging.

Companion docs (this file links to them rather than duplicating):
- [CLAUDE.md](../CLAUDE.md) — repo overview, build/run, architecture.
- [docs/RESI_MIGRATION.md](RESI_MIGRATION.md) — RESI unit analysis + verified P-Flow D116 register map.
- [docs/FIELD_ETHERNET_ACCESS.md](FIELD_ETHERNET_ACCESS.md) — on-site console over the direct cable.
- [provisioning/README.md](../provisioning/README.md) · [provisioning/migrate/RUNBOOK.md](../provisioning/migrate/RUNBOOK.md) · [provisioning/migrate/ENGINEER-GUIDE.md](../provisioning/migrate/ENGINEER-GUIDE.md) · [provisioning/migrate/ARTIFACTS.md](../provisioning/migrate/ARTIFACTS.md) — the migration wizard and offline artifacts.
- [TELEMETRY_KEY_MAP.md](../TELEMETRY_KEY_MAP.md) · [TELEMETRY_PIPELINE.md](../TELEMETRY_PIPELINE.md) — telemetry keys/pipeline (note: the VR branch in TELEMETRY_PIPELINE is legacy — see §4.3).

> **Security / publishing:** see §14. Do not push to GitHub without asking. No secret values
> appear in this file by design (they live in gitignored `.env` / `out/`).

---

## 1. System overview

- **Hardware:** Raspberry Pi CM4 on a RESI **C4-A-32DI24RO16AIOX** carrier board, LTE modem
  **Quectel EC25** (USB `2c7c:0125`, QMI/`cdc-wdm0`). **No WiFi hardware** (the WiFi-AP feature
  was removed, see §14). The board's onboard **AIOX** analog expander is itself a Modbus slave.
- **The migration keeps the carrier board and replaces only the SD card.** So the unit's
  identity (**HWID**, a 24-hex-char STM32 96-bit id) is inherited, the AIOX inputs stay wired,
  and there is never a moment of two gateways publishing at once (one card slot, atomic swap).
  A swap does take a live site offline briefly.
- **Reference unit:** `DBKIT24EU-0010`, HWID `1F0022000D57435535333920` (ThingsBoard project
  `PKE_3`), factory hostname `RESI-C4`.
- **Software after migration:** Docker + **tb-gateway** (image `thingsboard/tb-gateway`,
  3.7-stable pinned) reads the meter bus and publishes to ThingsBoard over MQTT; **Tailscale**
  for remote access; an on-box **FastAPI+Vue web console** on port 80.

## 2. The two telemetry "worlds" (read this before touching telemetry)

There are **two parallel naming/pipeline conventions**. Confusing them is the single biggest
source of "dashboard shows no data" incidents.

| | RESI / fleet | ECO GW (new) |
|---|---|---|
| Device profile | `P-Flow D116`, `Temperature Sensor`, `RESI` | `P-Flow D116 GW`, `Temperature Sensor GW`, `ECO GW` |
| P-Flow keys | `CHC_M_*`, `CHC_S_*`, `CHC_C_*` (19 keys) | `E_th_*`, `V_m3`, `T_flow_C`, `Vdot_m3h`, `v_ms` … |
| Temp key | `temperature` | `auxT1_C` / `auxT2_C` |
| Where derived keys are computed | TB rule chain + **Measurement asset** calculated fields | **device-profile** calculated fields (device-first) |
| Data path into TB | RESIvmachine → aggregated blob to `_gw` | tb-gateway per-device → `v1/gateway/telemetry` |

The connector's **`emit` mode** (site file) selects which world it publishes:
`canonical` (ECO GW keys, GW profiles — current default for migrated kits) or `raw` (fleet
`CHC_*`, RESI profiles). See `provisioning/device-maps.js` (both names live on each register)
and `provisioning/generate-connector.js`.

> **Design decision (2026-09):** the connector stays **canonical-only**. An `emit:'both'` mode
> (publish CHC_* *and* canonical) was tried to make an on-console "P-Flow not shown" symptom go
> away, and **reverted** — that symptom is a **web-console bug** (the console must read the
> canonical keys), not a telemetry problem. Do not re-add CHC_* to the connector to paper over
> a UI issue.

## 3. ThingsBoard integration

### 3.1 MQTT endpoint (not the REST host)
- REST/UI host: `https://diagnostics.ecoenergygroup.com`.
- Gateways connect over **MQTT to a different host: `lb-mqtt.pke-iot.expert`** — `1883` plain
  or `8883` TLS. **Never** put the REST hostname (or the repo's old `demo.thingsboard.io`
  default) into the gateway config.
- The RESI stack used **8883 TLS** with MQTT basic auth (user `pke`, fleet password) publishing
  a nested gateway-style payload to the single-device topic `v1/devices/me/telemetry` (a rule
  chain fans it out). A real tb-gateway instead uses `v1/gateway/telemetry` — device creation
  and attribute handling differ, so do not assume a drop-in swap of the data path.

### 3.2 Device naming (must match exactly or dashboards won't bind)
The fleet (700+ devices) uses a fixed convention keyed on the inherited HWID:
- `ECO_<HWID>_PF1` … `_PF4` — P-Flow D116 heat meters.
- `ECO_<HWID>_TS1` / `_TS2` — the two spare PT1000 probes on the C4 AIOX (see §6). **TS1+TS2
  only**; a `_TS3` is a fleet-wide stray (no physical sensor) — ignore/clean it.
- `ECO_<HWID>_gw` — the gateway's own health device (keys `LTE_IP`, `LTE_RSSI`, `LTE_RSRQ`,
  `LTE_RSRP`, `LTE_SN_RATIO`; `-9999` = no-signal sentinel).

### 3.3 The derivation pipeline (where derived keys come from)
Verified on ThingsBoard PE 4.2.1. The `criticalAlarmsCount` / `major` / `minor` / `warning`
keys are produced by **TB rule chains**, not the gateway.
- **RESI/asset path:** the `_gw` device → `RESI` rule chain → `RESI Device` sub-chain computes
  `CHC_S_TemperatureDiff` (= Flow − Return), stores `CHC_*` on the device, then forwards to a
  **Measurement asset** whose ASSET_PROFILE calculated fields produce the canonical + analytics
  keys the dashboards read.
- **ECO GW path (device-first):** canonical + derived keys both land on the **device**; the
  calculated fields were cloned onto the `P-Flow D116 GW` **device profile**. Telemetry
  currently **stops at the device** (Measurement-asset forward is deferred, not removed).
- **CF limit gotcha:** TB PE enforces **max 10 calculated fields per entity**. On the GW device
  profile the quota is full, so `dT_K` and `E_th_kWh` were folded into `derived_basic` rather
  than added as new CFs. `derived_power` was edited to fire from flow·ΔT (its `P_th_measured_kW`
  arg — a key the connector never emits — was removed, which had blocked the whole cascade).
- **Legacy — do NOT chase:** the "VR device" hop is dead; the VR nodes in `resi_device.json`
  and the VR branch in `TELEMETRY_PIPELINE.md` are legacy. Current pattern: Measurement asset
  relates directly to the real device (reference a live measurement like `EPI_8_15`, not the
  stale `PKE_3_1`).

## 4. P-Flow D116 heat meter (Modbus)

Full verified map: [docs/RESI_MIGRATION.md](RESI_MIGRATION.md) and `provisioning/device-maps.js`.
Meter is a **GENTOS "P-Flow" D116-PT1000** (thermal/BTU variant). Serial: RTU, **9600 8N1**,
FC 3 (holding registers). Only **unitId 88** (PF1) is a known-real address; **PF2–PF4 unit IDs
were never recorded** — do not assume 80/81/82 or 89/90/91; verify with a bus scan per site.

- **Mixed endianness (critical):** 32-bit **floats** are word-order **BIG**, 32-bit **integer
  counters** are word-order **LITTLE**. tb-gateway sets byte/word order **per slave, not per
  register**, so every physical meter needs **two slave entries** sharing one `deviceName` and
  `unitId`. Collapsing them into one silently byte-swaps half the values.
- **Totals are mantissa + exponent.** Counters sit **3 registers apart** (8/11/14 and 77/80):
  two registers are the mantissa, a third 16-bit register is the exponent (exponents at
  10/13/16 for volumes, **79/82** for heating/cooling energy). Reading the mantissa as a bare
  int and dividing by a constant is correct **only while the exponent is 0** (true on every
  meter seen). The GW pipeline reads `E_th_heating_exp`@79 / `E_th_cooling_exp`@82 and applies
  `×10^exp` in a calculated field so `E_th_kWh` is always true kWh.
- **Energy scaling:** the register is **kJ**, the fleet stores **kWh** → `divider: 3600` on the
  energy registers (the RESI firmware did this scaling itself).
- **Address off-by-one convention:** the recovered config entered floats as `reg#−40000` but
  ints as `reg#−40001`. The live float addresses 5/7/74/76 read correct — **trust the live read
  over the datasheet PDU number.**
- **Instantaneous power register is UNKNOWN** (low-confidence guess: a single 32float in the
  40065–40073 gap, GJ/h). The meter reports one "EFR" power value (heating vs cooling is sign,
  so there are **no separate** heating/cooling power registers). **Recommended: derive power**
  server-side (ρ·cp·V̇·ΔT) rather than blind-scanning the bus. Consequence: `CHC_*_Power_*` and
  `P_deviation_pct`/`P_sensor_flag` are not available until that register is confirmed against a
  meter showing non-zero flow (a **targeted** read of regs ~64–73, not a blind full scan).

## 5. Temperature sensors (AIOX, not on the meter bus in the way you'd think)

The base kit ships 4 PT1000 terminals: two are the meter's own flow/return probes (read as the
P-Flow's `CHC_S_TemperatureFlow`/`Return` registers); the **other two** are `TS1`/`TS2` — spare
probes on the C4's **onboard AIOX**.

**Firmware-verified map** (decoded from RESI's production program, supersedes an earlier
unitId-1/×100 guess): the AIOX is reached as **Modbus unit 255** (the C4 mainboard's own
address) on the **same external RS485 meter bus** as the P-Flows — **FC04 (input registers)**,
start 0, count 8, signed 16-bit, unpacked as two interleaved sensors:
`reg[0]/reg[1]` = T_ACT for slot 0 (TS1) / slot 1 (TS2). **degC = int16 / 10** (0.1°C
resolution — divide by **10, not 100**). Validity is inferred from a T_ERRORS field; there is
no sentinel, so a missing/untyped channel can read `-999`-ish or garbage. If a channel reads
zero/garbage on live hardware it may need **AIOX channel typing once** (RTD/resistance mode) —
see `provisioning/aiox-modbus-probe.py` / `aiox-console-probe.py`.

## 6. Modbus connector tuning

Config: `provisioning/generate-connector.js` → `modbus.json`. See memory of the bench debug in
[docs/RESI_MIGRATION.md] and the notes below.

- **Short per-slave timeout.** RS485 RTU is one shared multi-drop bus. A **35s** timeout (an old
  repo default, **never** a RESI value) on empty/unwired addresses stalls the bus so long that
  the one real meter's frames arrive misaligned and get **misattributed to the wrong unit**
  (garbled/zero values, flapping "connected", `[0,16887]` instead of `[16887,0]`). Fix: fail
  dead addresses fast. **Production default:** `timeout: 2, retries: 1, retryOnEmpty: false,
  retryOnInvalid: true` (one cheap retry recovers a noisy CRC frame within the 60s cycle).
- **Retry semantics:** `retries` = retry on **timeout** (amplifies dead-address stalls — keep
  low while empty slots exist); `retryOnEmpty` = responded-but-empty; `retryOnInvalid` =
  responded-but-CRC-bad. None fix valid-CRC-but-wrong-data (desync) — that's downstream.
- **The "stops for minutes, then a big value" artifact** is a **data gap on a cumulative
  counter** (the first delta after a gap covers the whole gap). The meter is fine; cap
  implausible one-interval jumps / compute rate as Δcounter ÷ elapsed downstream. Do **not**
  copy RESI's aggressive `reconnectOnTimeout` loop.
- **`logLevel: DEBUG` is required inside `configurationJson`** for the web console's Meters page,
  which decodes live values by pairing the connector's DEBUG "Reading…/Read with result…" lines.
- **PORT TRAP:** inside the container the serial device is **`/dev/meterbus`**, not
  `/dev/ttyACM2`. The container is started `--device <by-id>:/dev/meterbus`; the site's
  `serial.port` is the host name, and the wizard maps it via **`ECO_MODBUS_PORT=/dev/meterbus`**.
  Regenerating `modbus.json` by hand **must** pass that env var — and on Git-Bash/MSYS also
  **`MSYS_NO_PATHCONV=1`** (else `/dev/meterbus` is mangled to `C:/Program Files/Git/dev/...`).
  A wrong port = `could not open port` = **total telemetry loss.**
- tb-gateway **collapses duplicate register addresses within one slave to a single tag**
  (last wins) — you cannot get two telemetry keys from one register in one slave.

## 7. LTE modem (Quectel EC25 / QMI)

- **APN `wsim`**, no user/pass, `ipv4.method=auto` — the field IoT-SIM APN. Driven via
  **ModemManager + a NetworkManager GSM connection** (`type=gsm`), **not** raw AT and **not**
  raw QMI. ModemManager runs as a **snap**. Signal via `mmcli -m any --signal-get`.
- **Do NOT drive the modem with raw AT.** ModemManager owns the AT ports, so opening
  `/dev/ttyUSB2` directly gives "Modem not found". `backend/app/services/modem_service.py` was
  rewritten to use `mmcli` for status/signal/reset (its watchdog previously fired
  `AT+CFUN=1,1`, a full modem reset that would drop LTE).
- **`raw_ip` boot bug (important):** the EC25 QMI netdev can come up with
  `/sys/class/net/wwan0/qmi/raw_ip = N`. Then NetworkManager fails with
  `retrieving IP configuration failed: modem IP method unsupported` and retries forever — no
  default route, `LTE_IP=0.0.0.0`, broker unreachable, **and Tailscale dead** (WAN-dependent).
  It's a chicken-and-egg: NM keeps the iface UP retrying, so MM can never flip `raw_ip` (only
  settable while DOWN). **Fixed durably** by `provisioning/box/install-lte-rawip.sh` (udev rule
  `ATTR{qmi/raw_ip}="Y"` on `wwan0` add + a self-healing systemd oneshot), run by the wizard's
  `net` phase. Manual one-shot recovery on an old box:
  ```
  sudo nmcli dev disconnect cdc-wdm0
  sudo ip link set wwan0 down
  echo Y | sudo tee /sys/class/net/wwan0/qmi/raw_ip
  sudo ip link set wwan0 up
  sudo nmcli --wait 40 con up gsm
  sudo docker restart tb-gateway    # drop the cached DNS-failure state
  ```
- **LTE_\* telemetry mechanism:** the container can't reach ModemManager, so a host systemd
  timer (`eco-lte-signal.timer`, 60s) samples `mmcli` and writes one value per file into
  `/opt/eco/tb-gateway/config/lte/<KEY>` (inside the already bind-mounted config dir). tb-gateway
  **custom statistics** (`statistics/eco_lte.json`) run `printf %s $(cat …)` **inside the
  container** and publish via `send_telemetry()` → they land as **telemetry** on `_gw`.
  `customStatsSendPeriodInSeconds` = **120** (was 900; a box rebooting inside a 900s window
  looked dead for hours). Gotchas: `mmcli --signal-get` returns nothing until
  `--signal-setup=<sec>` arms it (re-arm every run); resolve the modem index from `mmcli -L`
  (never hardcode `-m 0`); never put `\n` in the statistics command JSON.

## 8. Networking — the 3-mode WAN model

`provisioning/setup-networking.sh` (run by the wizard's `net` phase) makes eth0 auto-select,
no operator action — this matches what RESI field units did:

| eth0 situation | Result | Mechanism |
|---|---|---|
| Plugged into a network **with DHCP** | Internet over Ethernet | profile `eth0-wan` (DHCP, autoconnect-priority 20, `route-metric 100`, `may-fail=no`, `dhcp-timeout 15`) |
| Plugged straight into a **PC (no DHCP)** | Box serves `10.10.10.1` + own DHCP; console at `http://10.10.10.1/` | `eth0-wan` fails fast → falls back to `eth0-direct` (shared, priority 10, `never-default`) |
| **No cable** | LTE only | single `gsm` profile, `route-metric 700` |
| Ethernet **and** LTE up | Ethernet preferred, LTE seamless failover | lower metric wins (100 < 700) |

RESI achieved the Ethernet>LTE split for free (empty `NetworkManager.conf` → NM auto-creates a
DHCP "Wired connection"; NM's default per-device metrics are eth 100 < wwan 700). We make it
explicit and add the PC-direct fallback RESI never had. Gotchas baked in:
- A **mode-aware** nft dispatcher (`50-eco-eth0-guard.sh`) blocks cable→SIM forwarding **only**
  while `eth0-direct` is active (in WAN mode eth0 must forward for Docker/Tailscale routes).
- The factory ships **two** autoconnect GSM profiles (`gsm`, `modem`); both on wedges the modem
  in an alternating retry loop — the script disables `modem`.
- `autoconnect-retries` left at NM default (4), not 0 — 0 would flap the console link forever in
  PC-direct mode; a cable re-plug resets the counter so moving to a router re-tries WAN.

The box **deliberately does not forward cable→SIM**, so a laptop on the direct cable keeps its
own default route. See [docs/FIELD_ETHERNET_ACCESS.md](FIELD_ETHERNET_ACCESS.md).

## 9. Migration workflow (the wizard)

`provisioning/migrate/tui.js` — a guided, **idempotent** installer. Each phase has
`detect()` (skip if already done) → `run()`. Full procedure: [RUNBOOK.md](../provisioning/migrate/RUNBOOK.md),
[ENGINEER-GUIDE.md](../provisioning/migrate/ENGINEER-GUIDE.md).

```
node tui.js --kit DBKIT24EU-0010        # or omit --kit for the ThingsBoard kit picker
```
Phase order: **connect → net (WAN model + raw_ip fix) → tb (reprofile + capture creds) →
ecoadmin (key) → harden (lock factory logins) → standdown (mask RESI) → scan (bus) → artifacts
→ docker → config (build tb_gateway.json + modbus.json) → deploy (container) → tailscale →
webconsole → lte → verify.**

Two-stage box auth: bootstrap as `resi` (fleet password) until the `ecoadmin` key is installed,
then key-only. Re-running on an already-migrated kit skips finished phases — see §15 for the
caveat that this can leave an old config on the box.

## 10. Web console (on-box, port 80)

FastAPI backend serving the built Vue frontend directly (no nginx), systemd
`eco-iot-gw-backend`, `uvicorn --host 0.0.0.0 --port 80` **as root**. Reachable over the cable
(`http://10.10.10.1/`) and over Tailscale. Deep dives (WIP): the `webui-*` notes / repo docs.
- **Meters page decodes values from the tb-gateway container DEBUG logs** (pairs "Reading…" /
  "Read with result…" lines) — hence the `logLevel: DEBUG` requirement (§6). It expects the
  **canonical** key names.
- Auth model (planned): Tailscale-trust remote + read-only-local + per-device `ecoadmin` Linux
  login. Not fully reworked yet.
- **The console is WIP.** A "P-Flow not shown / no P-Flow connected" symptom on the dashboard is
  a console bug to fix *here* (read the canonical keys / the connected device), **not** a reason
  to change telemetry (§2).

## 11. Tailscale
`box/install-tailscale.sh`, wizard phase `tailscale`. **Leave Tailscale `--ssh` OFF** — enabling
it makes tailscaled intercept port 22 and reject sessions unless a tailnet ACL authorizes the
tagged box; with it off, port 22 falls through to the box's real sshd (the `ecoadmin` key opens
it). The box's shared-mode DHCP would otherwise **kill a plugged-in laptop's own Tailscale**
(default-route/DNS hijack) — suppressed by the no-gateway dnsmasq drop-in (§8).

## 12. Windows tooling

### 12.1 Reaching a *factory* RESI box over the cable (before `net` runs)
The factory image serves **no DHCP and no 10.10.10.1** — the box is only on an IPv6
**link-local** `fe80::…%zone`; the laptop sits at APIPA `169.254.x`, and the link flaps
(NM DHCP-retry loop) so NDP goes stale every ~30–60s. Baked into `lib/ssh.js`:
1. Use **native Windows OpenSSH** (`C:\Windows\System32\OpenSSH\ssh.exe`) — MSYS ssh can't use a
   Windows IPv6 zone id (`%37`).
2. **`.bat` askpass** (Windows ssh can't exec a `.sh`); factory sshd allows password, our ECO
   image is key-only.
3. **Prime NDP** (ping the `fe80::…%zone`) immediately before each ssh/scp.
4. **Run the terminal elevated** — the `net` phase's `ipconfig /release`+`/renew` needs Admin
   (preflight detects + warns).

### 12.2 SD card access
`tools/sd.ps1` attaches the card via **usbipd + WSL** and mounts boot (vfat) + rootfs (ext4) at
`/mnt/sd`. **The card must be in a USB reader** — the laptop's built-in PCIe reader fails for
both `wsl --mount` and usbipd. `-Rw` seeds a freshly flashed card (userconf, ssh flag,
authorized_keys) before first boot. See the SD-card notes for the traps (usb-storage not
auto-loaded, replug-after-detach, base64 multi-line scripts through PowerShell).

## 13. Offline artifacts
The gateway installs with **no internet on the box** (SIM is metered / may be down). The wizard's
`artifacts` phase builds/caches everything into `provisioning/migrate/cache/`: the docker-static
tarball, the tb-gateway image, the arm64 **wheelhouse** (`pip download`), the frontend **dist**
(`npm run build`), and the **backend** tgz (`backend/app`). See
[ARTIFACTS.md](../provisioning/migrate/ARTIFACTS.md). **Caveat:** the phase only rebuilds when an
artifact is *missing*; a stale cached tgz is reused. After changing `backend/` or `frontend/`,
delete the matching cache tgz (or the phase won't repack it). GitHub's 100 MB/file limit means
the image tarball is handled specially.

## 14. Security & publishing rules

- **Do not `git push` without asking**, and don't commit unasked. The user may create a new org
  repo. Existing remote `github.com/JiriD85/ECO-IOT-GW` is **public**.
- **Customer naming:** only customers named **ECO** or **PKE** may appear publicly. Real kit ids
  (`DBKIT24EU-0010`) and HWIDs are fine. Genericize any other customer name.
- **Never commit secrets:** the RESI fleet default SSH password, the fleet MQTT password, TB
  tenant creds, Tailscale auth keys, generated `ecoadmin` passwords. `.env`, `out/`, `cache/`,
  `credentials.csv`, `*.secrets.json`, `*.img` are gitignored — verify with `git ls-files`
  before proposing a commit.
- **No WiFi hardware** — the WiFi-AP feature was removed (`api/wifi.py`, `wifi_service.py`,
  `WifiConfig.vue`, `config/hostapd/`, hostapd install step). `validate_ssid` was kept (generic).

## 15. Known issues / open items

- **Web console shows the P-Flow as absent / no data** — the connector sends the canonical keys
  fine; the fix is in the console (read canonical keys / detect the connected device). *Open.*
- **P-Flow power + a few `CHC_*` keys missing:** the instantaneous power register address is
  unknown (§4) → `*_Power_*`, the `CHC_C_*` counter set, and `CHC_S_TemperatureDiff` are not
  produced by the connector. Power/TempDiff are better **derived server-side**; `CHC_C_*` map to
  the same firmware variables as `CHC_M_*`.
- **PF2–PF4 unit IDs unverified** (only PF1/unit 88 known). Re-run a bus scan once they're wired.
- **TS1 reading `-999`** on the reference unit (no probe / AIOX channel needs typing); TS2 reads
  real values.
- **Re-running the wizard on an already-migrated kit skips finished phases** (`deploy`,
  `webconsole`, `lte`, `net` detect as done), so a changed `modbus.json`/backend won't
  auto-redeploy — force a redeploy or restart the container/service when you need the new one.
- **Downstream gap-aware consumption calc** (cap implausible one-interval jumps) still TODO in
  the TB rule chain.
- Backend runs as **root** on port 80 — a security smell to revisit.

---

*Provenance: recovered from the original RESI SD card image, live hardware probing (EC25 via
`lsusb`/`mmcli`, the D116 connector config on `pke_AT1100_iotgw01`), and field debugging on
`DBKIT24EU-0010` (Aug–Sep 2026). Treat energy/volume absolute values as provisional until
checked against a meter's own display; do not "tidy" register addresses.*
