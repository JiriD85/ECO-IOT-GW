# Migrating a RESI Doctor-Kit site to ECO-IOT-GW

Findings from analysing a decommissioned RESI gateway's SD card and the live ThingsBoard
tenant, on 2026-08-04, plus the tooling built from them.

Read this before configuring a gateway. Several conclusions here are counter-intuitive and
were only reachable by digging; two of them silently corrupt data if you get them wrong.

---

## 1. Summary of decisions

| Decision | Outcome |
|---|---|
| Base OS | **Clean Raspberry Pi OS flash** on a fresh card. The old card's stack is a closed binary with nothing reusable — see §3. |
| Gateway device in ThingsBoard | Create new, modelled on `pke_AT1100_iotgw01` (profile `IoT Gateway`, `additionalInfo.gateway = true`). |
| Device naming | Each Pi **inherits the HWID of the RESI unit it replaces**, so child devices and their history stay continuous. |
| Fleet configuration | Shared attributes in ThingsBoard as source of truth, pulled via `remoteConfiguration`. No SSH needed for connector changes. |
| Temperature sensors | Blocked on a hardware choice — they were never Modbus devices. See §6. |

---

## 2. ⚠️ Before deploying: check the old unit is actually dead

The card analysed here belongs to **HWID `1F0022000D57435535333920`** = project `PKE_3`,
measurement `PKE_3_1`. At the time of writing that site was **still live**, reporting
telemetry the same day from a different LTE IP than the card recorded (`10.48.159.94` vs
the card's `10.50.51.221`).

Because the naming convention inherits the HWID, deploying a new gateway for a site whose
old unit is still running makes **two gateways publish to the same child devices**. The
symptom is subtle: alternating values and inactivity alarms that clear themselves.

Check before every deployment:

```bash
node provisioning/probe-tb.js fleet <HWID>
```

If the newest timestamp is recent, the old unit is alive. Decommission it first.

---

## 3. What was on the old card

A **RESI-C4-LTE-Doctor-Kit, 4xpFlow, 2025 build** — hostname `RESI-C4`, Debian 12
(bookworm), Raspberry Pi CM4. Login user is `resi` (uid 1000, sudo-capable).

### The application

`/home/resivm/RESIvmachine_2_0_05.exe` — a closed-source ARM interpreter that executes
compiled bytecode `.instance` files from `/home/resivm/storage/`, launched by
`pm2-resi.service`. The bytecode headers name their own source files, which exist only on
a RESI developer's Windows machine:

```
C:\RESI-VM-SW-2025\RESI-C4-LTE-Doctor-Kit - 4xpFlow - 2025\Hauptcontroller\*.mc
```

**The software can be reconfigured but not modified or extended.** That is the core reason
not to keep the old OS.

Enabled alongside it at boot: MariaDB (local historian, database `DOCTOR_KIT`, tables
`MQTT` and `MEASUREMENT`), Grafana, Mosquitto, Apache2, snmpd, ser2net, Node-RED, a full
LXDE desktop and wayvnc. Roughly 14 GB in use, on a filesystem with pre-existing
`e2fsck` errors.

The Node-RED flows are a red herring: 766 nodes across 16 tabs, most disabled, all of it
RESI's factory board demo (DIP switches, LEDs, analog IO). Its Modbus nodes address the
C4's own onboard IO at unit 1, registers 10000/40000/65500. **No P-Flow logic, no Docker,
no tb-gateway anywhere on the card.**

### What is worth keeping

- `/home/resivm/ca-root.pem` — the MQTT broker's TLS CA
- `/home/resivm/RESICheckLTE.sh` — scrapes `mmcli -m 0 --signal-get` for rssi/rsrq/rsrp/s-n;
  this is exactly how the fleet's `LTE_*` telemetry is produced, and worth porting
- the HWID and measurement key

### Re-reading the card image

The extractor is committed as [`provisioning/extract-resi-card.sh`](../provisioning/extract-resi-card.sh).
It mounts read-only and copies the config trees out.

```bash
wsl -d Ubuntu -u root -- bash /path/to/extract-resi-card.sh
```

Use `wsl -u root`, not `sudo` — WSL grants root without a password, so no credential is
needed. Clean up afterwards:

```bash
wsl -d Ubuntu -u root -- bash -c "umount /mnt/sdroot /mnt/sdboot; losetup -D"
```

Note WSL cannot mount the physical card on this laptop (PCIe reader, and WSL2 rejects
removable media) — image the card from Windows and loop-mount the image.

---

## 4. ThingsBoard side

| | |
|---|---|
| REST / UI | `https://diagnostics.ecoenergygroup.com` (TB 4.2 PE) |
| MQTT | `lb-mqtt.pke-iot.expert` — **1883 plain** (tb-gateway) / **8883 TLS** (RESI fleet, with `ca-root.pem`) |
| Tenant size | ~711 devices |

**The MQTT host is not the REST host.** The repo's committed default used to be
`demo.thingsboard.io`; pointing it at the REST hostname fails just as silently.

### Naming convention

Child device names must match exactly, or existing dashboards will not bind:

```
ECO_<HWID>_PF1 .. _PF4    P-Flow D116 heat meters   (profile "P-Flow D116")
ECO_<HWID>_TS1 .. _TS2    temperature sensors       (profile "Temperature Sensor")
ECO_<HWID>_gw             gateway health device     (profile "RESI")
```

`<HWID>` is a 24-hex-char STM32 96-bit unique ID from the RESI hardware. A Raspberry Pi
has no equivalent, hence the inheritance rule in §1.

### Telemetry keys

- **P-Flow D116** — 19 `CHC_*` keys. `CHC_M_*` cumulative meter counters, `CHC_S_*`
  instantaneous, `CHC_C_*` a second counter set that maps to the *same* firmware variables
  as `CHC_M_*` and reads 0 everywhere observed.
- **Temperature Sensor** — a single `temperature` key, °C.
- **`_gw`** — `LTE_IP`, `LTE_RSSI`, `LTE_RSRQ`, `LTE_RSRP`, `LTE_SN_RATIO`. `-9999` is the
  no-signal sentinel.
- `criticalAlarmsCount` / `majorAlarmsCount` / `minorAlarmsCount` / `warningAlarmsCount`
  are generated by rule chains, **not** by any gateway. Don't try to send them.

### The fleet's data path differs from tb-gateway's

The RESI publishes with `mosquitto_pub` to **`v1/devices/me/telemetry`** — the
*single-device* topic — while sending a *nested, gateway-shaped* payload:

```json
{ "ECO_<HWID>_PF1": [ { "ts": 1785835362160, "values": { "CHC_M_Volume": 16887.0 } } ] }
```

It authenticates with MQTT basic auth (a **single shared fleet credential**, client id
`ECO_gw_1`) rather than a per-device access token.

A ThingsBoard **rule chain must be fanning that payload out** to the child devices. Two
pieces of evidence: the payload names devices that the topic cannot address, and the
payload's `ECO_<HWID>_LTE` device *does not exist* in the tenant — its keys land on
`ECO_<HWID>_gw` instead, so something is renaming it.

A real tb-gateway instead uses `v1/gateway/telemetry` with a per-device access token and
auto-creates child devices. **That is a different ingestion path.** Inspect the rule chain
before assuming a new gateway is a drop-in replacement, and watch for a rule chain that
now receives nothing.

### Where the register map came from

tb-gateway stores its connector configuration in device attributes when
`remoteConfiguration` is on. That means a decommissioned gateway's configuration survives
in ThingsBoard long after the hardware is gone — which is how the P-Flow map was recovered,
from `pke_AT1100_iotgw01` (tb-gateway 3.5.1, last active 2024-06).

```bash
node provisioning/probe-tb.js dump-attrs ./out/attrs
```

**Two decoys.** The attributes named `RTU PFlow` (on `pkegw05`), `Pflow` (on
`bel_iotgw_resi01`) and `RS485-1` (on `eco-gw-01`) look authoritative but are ThingsBoard's
**stock demo config** — tags `8int_read`, `16uint_read`, `32float_read`. Only
`pke_AT1100_iotgw01`'s `3RS485_PF` / `2RS485_PF` are real. The `127.0.0.1:5021` TCP
transport in the demo ones is, however, a genuine RESI pattern: `ser2net` re-exports the
serial port as a local TCP socket.

---

## 5. The P-Flow D116 register map

Serial RTU, 9600 8N1, `unitId 88`, function code 3 (holding registers), poll 30 s.
Encoded in [`provisioning/device-maps.js`](../provisioning/device-maps.js).

| wordOrder | type | tag | address |
|---|---|---|---|
| BIG/BIG | 32float | `CHC_S_VolumeFlow` | 5 |
| BIG/BIG | 32float | `CHC_S_Velocity` | 7 |
| BIG/BIG | 32float | `CHC_S_TemperatureFlow` | 74 |
| BIG/BIG | 32float | `CHC_S_TemperatureReturn` | 76 |
| BIG/LITTLE | 32int | `CHC_M_Volume` | 8 |
| BIG/LITTLE | 32int | `CHC_M_Volume_Neg` | 11 |
| BIG/LITTLE | 32int | `CHC_M_Volume_Net` | 14 |
| BIG/LITTLE | 32int | `CHC_M_Energy_Heating` | 77 |
| BIG/LITTLE | 32int | `CHC_M_Energy_Cooling` | 80 |

### ⚠️ Trap 1: the meter is mixed-endian

Floats are word-order **BIG**, integer counters word-order **LITTLE**. tb-gateway sets
byte/word order **per slave**, not per register, so every physical meter needs **two slave
entries** sharing one `deviceName` and `unitId`. The generator does this automatically.

Collapsing them into one slave does not error — it byte-swaps half the values into
plausible-looking garbage.

### ⚠️ Trap 2: totals are mantissa + exponent

The counters sit **3** registers apart (8, 11, 14 and 77, 80), not 2. The RESI firmware
explains why: every total exists as a `_MANTISSA` / `_EXPONENT` / `_UNIT` triple
(`POSITIVE_TOTAL`, `NEGATIVE_TOTAL`, `NET_TOTAL`, `HEATING_TOTAL_ENERGY`,
`COOLING_TOTAL_ENERGY`). Two data registers are the mantissa; the third is the exponent.
The meter also reports its own `ENERGY_UNIT` / `TOTAL_UNIT` / `FLOW_UNIT` / `VELOCITY_UNIT`.

So reading a total as a bare 32-bit int and dividing by a constant is correct **only while
the exponent is 0 and the unit register says kJ**. That holds for every meter observed —
`11394.98555556 × 3600 = 41021948` exactly, and the same for three other live values — but
it is not robust. A meter with a different exponent is silently wrong by a power of ten.

tb-gateway's Modbus connector cannot express `mantissa × 10^exponent`. Doing this properly
means either reading the exponent registers as their own telemetry keys and applying the
scaling as a ThingsBoard calculated field, or shipping a custom uplink converter. Until
then **treat energy and volume totals as provisional** and check each meter against its own
display.

### Keys not covered

`CHC_S_TemperatureDiff` is derivable, not a register: `TemperatureFlow − TemperatureReturn`,
verified exact against live fleet data (`28.51 − 28.89 = −0.38`, `28.02 − 29.27 = −1.25`).
Implement it as a ThingsBoard calculated field.

The four `Power_*` keys read 0 on every live device, so their source could not be
identified. The five `CHC_C_*` keys map to the same firmware variables as `CHC_M_*`.

Unit IDs for PF2–PF4 are **unknown** — only unitId 88 was ever configured anywhere, for a
single meter. Resolve per site with the bus scan; do not guess.

---

## 6. The temperature sensors are not Modbus devices

The RESI firmware exposes them only as `PT1000_CELSIUS` / `_FARENHEIT` / `_KELVIN`: they are
PT1000 resistance thermometers wired into the **C4's onboard analog inputs**, read through
the C4's own IO block. There is no Modbus register map for them anywhere because there never
was one. (They do work — `TS1`/`TS2` report `temperature` on the live unit.)

A Raspberry Pi has no equivalent analog input, so this is a hardware decision:

- **A Modbus RTU RTD transmitter** on the existing RS485 bus — cheaper fit for this
  architecture, since the connector then treats it as an ordinary slave and needs only a
  register map in `device-maps.js`.
- **An RTD interface board** (e.g. MAX31865 over SPI) plus a small local service to publish
  the reading — more wiring and more code, but no extra bus device.

Until one is chosen, `provisioning/generate-connector.js` deliberately **refuses** to emit
config for `tempSensors` rather than guessing.

---

## 7. Coexistence on units that cannot be reflashed

For remote sites where the card cannot be swapped, ECO-IOT-GW would have to install
*alongside* the RESI stack. One concrete blocker found: **Apache2 holds port 80**, which
collides with ECO-IOT-GW's nginx. MariaDB, Grafana (3000) and Mosquitto (1883) are also
resident. This path has not been scoped further.

---

## 8. Security notes

- The fleet uses **one shared MQTT credential** across all gateways. Worth raising with
  whoever owns the broker.
- The card holds that credential in cleartext inside the `.instance` bytecode, so any
  extract directory contains it and must not be shared.
- `remoteShell` is set to `false` in the committed gateway config even though the fleet runs
  it enabled. ECO-IOT-GW already ships VPN plus a web terminal, and an always-on shell over
  MQTT is real attack surface for an NIS2-scoped system. Flip it per-device if you disagree.

---

## 9. Tooling built from these findings

| Tool | Purpose |
|---|---|
| [`provisioning/probe-tb.js`](../provisioning/probe-tb.js) | Read-only ThingsBoard inspector: profiles, gateways, devices, fleets, attribute dumps |
| [`provisioning/device-maps.js`](../provisioning/device-maps.js) | The register map, with provenance and every caveat inline |
| [`provisioning/generate-connector.js`](../provisioning/generate-connector.js) | Site definition → tb-gateway Modbus connector |
| [`provisioning/provision-gateway.js`](../provisioning/provision-gateway.js) | Creates the TB device, pushes shared attributes, writes boot configs (dry-run by default) |
| [`provisioning/scan-modbus.py`](../provisioning/scan-modbus.py) | Read-only RS485 bus scan; resolves unit IDs, confirms endianness and scaling |
| [`provisioning/extract-resi-card.sh`](../provisioning/extract-resi-card.sh) | Mounts a RESI card image read-only and extracts its config |

The per-gateway workflow is in [`provisioning/README.md`](../provisioning/README.md).

---

## 10. Open items

| Item | Blocked on |
|---|---|
| Unit IDs for PF2–PF4 | `scan-modbus.py` against real hardware, per site |
| Temperature sensor hardware | decision in §6 |
| Mantissa/exponent scaling done properly | exponent registers + TB calculated field, or a custom converter |
| `Power_*` register sources | bus scan; all observed values are 0 |
| Rule-chain behaviour on the new ingestion path | inspecting the chain that fans out `v1/devices/me/telemetry` |
| Coexistence install for remote units | §7, not scoped |
| End-to-end verification | fresh card + Pi + meters |
