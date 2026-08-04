# Gateway Provisioning

Tooling to bring up a Raspberry-Pi-based gateway against ThingsBoard, repeatably, for
many units.

## Why it is shaped this way

The existing fleet reports through **RESI** hardware, not through tb-gateway. Only three
devices in the tenant are real tb-gateway instances, and none of them was ever fully
configured. So there was no working reference deployment to copy — the register map and
the fleet's naming/telemetry conventions had to be recovered from device attributes
stored in ThingsBoard. `device-maps.js` records where each fact came from; read its
header before changing addresses.

Two facts that are easy to get wrong and expensive to debug:

- **MQTT goes to `lb-mqtt.pke-iot.expert:1883`**, not to the REST/UI host
  (`diagnostics.ecoenergygroup.com`). The repo's old committed default was
  `demo.thingsboard.io`.
- **The P-Flow D116 is mixed-endian.** 32-bit floats are word-order BIG, 32-bit counters
  are word-order LITTLE. tb-gateway sets endianness per *slave*, so each physical meter
  needs two slave entries sharing one `deviceName` and `unitId`. Collapsing them into one
  slave silently byte-swaps half the values into plausible-looking garbage.

## Device naming

Child device names must match the fleet convention exactly, or the existing dashboards
will not bind to them:

```
ECO_<HWID>_PF1 .. _PF4    P-Flow D116 heat meters
ECO_<HWID>_TS1 .. _TS2    temperature sensors
ECO_<HWID>_gw             the gateway's own health device (RESI profile)
```

`<HWID>` is a 24-hex-char STM32 unique ID from the original RESI hardware. A Raspberry Pi
has no equivalent, so **each Pi inherits the HWID of the RESI unit it replaces**. Read it
off the `ECO_<HWID>_gw` device of the unit being decommissioned. This keeps every child
device — and all of its history — continuous in ThingsBoard.

## Per-gateway workflow

### 1. Discover the bus

Unit IDs were never recorded. Only `unitId 88` is known, from a single meter on one
gateway. Determine them per site, on the Pi, with the meters connected:

```bash
sudo systemctl stop thingsboard-gateway
sudo python3 provisioning/scan-modbus.py --port /dev/ttyAMA1
```

The scan is read-only (function code 3 only). It prints which unit IDs answer and decodes
the P-Flow registers under each candidate endianness, so it also confirms the byte/word
order and the kJ→kWh divider against real hardware.

### 2. Write the site definition

Copy `sites/example.json` to `sites/<gatewayName>.json` and fill in the inherited `hwid`
and the unit IDs from step 1. Site files are gitignored — they identify customer sites.

### 3. Provision

```bash
node provisioning/provision-gateway.js provisioning/sites/<gatewayName>.json
```

Dry run by default: it validates the site file, prints the child device names it would
create, and writes a connector preview. Nothing touches ThingsBoard.

When the output looks right:

```bash
node provisioning/provision-gateway.js provisioning/sites/<gatewayName>.json --apply
```

That creates the gateway device (profile `IoT Gateway`, `additionalInfo.gateway = true`,
following the schema of the existing `pke_AT1100_iotgw01`), reads back its access token,
pushes `general_configuration` + the connector + `active_connectors` as **shared
attributes**, and writes `tb_gateway.yaml` and `modbus.json` into `provisioning/out/`.

Credentials are read from `../ECO-TB/.env` (or `.env.local`, or `$ECO_TB_ENV`) so there is
only one copy of the ThingsBoard password.

### 4. Deploy to the Pi

```bash
scp provisioning/out/<gatewayName>.tb_gateway.yaml pi@<ip>:/tmp/tb_gateway.yaml
scp provisioning/out/<gatewayName>.modbus.json      pi@<ip>:/tmp/modbus.json
ssh pi@<ip> 'sudo cp /tmp/tb_gateway.yaml /tmp/modbus.json /etc/thingsboard-gateway/config/ \
  && sudo systemctl restart thingsboard-gateway'
```

`provisioning/out/` is gitignored — those files contain a live access token.

### 5. Verify

The gateway device should go `active` in ThingsBoard, and `ECO_<HWID>_PF1..PF4` should
appear beneath it with `CHC_*` telemetry. Cross-check one meter's `CHC_M_Energy_Heating`
against its physical display before signing the site off.

## Order matters

**Provision ThingsBoard before starting the gateway for the first time.** With
`remoteConfiguration: true` and the shared attributes still empty, tb-gateway pushes its
own local placeholder config *up* to the server, and you have to clear it out again. This
is how `eco-gw-01` and `pkegw05` ended up storing ThingsBoard's stock demo config.

Once provisioned, shared attributes are the source of truth: to change a connector across
the fleet, update the attribute and the gateways pull it within
`checkConnectorsConfigurationInSeconds` (60 s). No SSH needed — which matters for units
that are only reachable remotely.

## Before deploying: check the old unit is dead

Because each Pi inherits the HWID of the RESI unit it replaces, deploying while the old
unit still runs makes two gateways publish to the same child devices — which shows up as
alternating values and self-clearing inactivity alarms, not as an obvious error.

```bash
node provisioning/probe-tb.js fleet <HWID>
```

A recent timestamp means the old unit is alive. Decommission it first.

## Known gaps

| Gap | Effect | How to close it |
|---|---|---|
| Unit IDs for PF2–PF4 | site files cannot be completed from the desk | `scan-modbus.py` per site |
| Which AIOX channels the PT1000 sensors occupy | `TS1`/`TS2` may read an unpopulated channel | `scan-modbus.py --port <internal> --aiox` |
| Whether the AIOX channel TYPE survives the software swap | RTD registers read dead after reflashing | the `--aiox` scan prints the TYPE block; rewrite it if reset |
| `internalSerial` port is not stable | AIOX and the Cinterion modem both enumerate as `ttyACM*` | pin the port with a udev rule by USB path |
| LTE modem is Cinterion, not Quectel | `modem_service.py` targets Quectel AT commands | verify against this hardware; prefer ModemManager (`mmcli`) |
| Totals are mantissa + exponent | energy/volume silently wrong by a power of ten if a meter's exponent is not 0 | read the exponent registers as their own keys + a TB calculated field, or a custom uplink converter |
| 10 of 19 `CHC_*` keys unmapped | those keys stay absent on new gateways | see the table in `device-maps.js` |
| `CHC_S_TemperatureDiff` | derivable, not a register | `Flow - Return`, verified exact against live data; add as a ThingsBoard calculated field |
| Fleet ingests via `v1/devices/me/telemetry` + a rule chain | tb-gateway uses `v1/gateway/telemetry` instead — a different path | inspect the fan-out rule chain before assuming a drop-in swap |

Full analysis, including where each of these facts came from:
[`docs/RESI_MIGRATION.md`](../docs/RESI_MIGRATION.md).
