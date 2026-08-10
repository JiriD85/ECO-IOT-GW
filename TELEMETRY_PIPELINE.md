# Telemetry Pipeline - End to End

> How a sensor reading travels from the meter to the Measurement asset, which node
> creates which telemetry key, and what happens afterwards.

**Status:** documented from the exported rule chain JSONs in `rule chains/` (on-disk snapshot).
**Related:** [DERIVED_TELEMETRY_LOGIC.md](../analysis/DERIVED_TELEMETRY_LOGIC.md) ·
[rule chains/scripts/README.md](../rule%20chains/scripts/README.md) ·
[ECO_Data_Catalog.md](../analysis/ECO_Data_Catalog.md) ·
[SYSTEM_MODEL.md](SYSTEM_MODEL.md)

---

## 1. Overview

```
Sensor / meter (M-Bus, Modbus)
   |
   v
ECO IoT Gateway (Raspberry Pi, FastAPI)
   |
   v
TB Gateway Docker  --- MQTT gateway API --->  ThingsBoard
   |
   v
GATEWAY DEVICE  (one batched msg for all sub-devices)
   |
   v  Root Rule Chain -> Device Profile Node -> RESI CORE -> RESI DEVICE
   |
   +-- Process Meters      : split per device, compute *_TemperatureDiff
   +-- Change Device       : originator GATEWAY -> physical DEVICE
   +-- Save Timeseries     : raw CHC_* keys stored on the DEVICE
   |
   v  Switch to Measurement (relation "Measurement", direction TO)
   |
MEASUREMENT ASSET
   +-- Save Timeseries     : raw CHC_* keys (again)
   +-- Normalize Data      : CHC_* -> canonical keys (T_flow_C, Vdot_m3h, ...)
   |
   v  Calculated Fields (Asset Profile "Measurement")
   |
   +-- derived_basic / derived_power / derived_schedule / rolling-window CFs
   |
   v  CF output re-enters the rule engine as Post telemetry on the asset
   |
MEASUREMENT CORE rule chain
   +-- 5 alarm switches -> Create/Clear Alarm -> EM Alarm Handler
   |
   v
Dashboards + Widgets (read from the Measurement asset)
```

Entity hierarchy the pipeline relies on:

```
Customer -> Project -> Measurement (ASSET) -> Device
                            ^                    ^
                            |                    |
              relation "Measurement"      relation "Contains" (from Gateway)
```

---

## 2. Stage 0 - Transport

| Hop | Component | Notes |
|-----|-----------|-------|
| Sensor -> Gateway | ECO-IOT-GW (FastAPI + Vue.js on Raspberry Pi) | reads M-Bus / Modbus meters |
| Gateway -> TB Gateway | local | |
| TB Gateway -> ThingsBoard | MQTT gateway API | one connection, many logical devices |

The message that arrives in the rule engine is addressed to the **gateway device** and
carries all sub-devices at once:

```json
{
  "WBS_11_PF2_LTE": [
    { "ts": 1738000000000, "values": { "CHC_S_TemperatureFlow": 62.4,
                                       "CHC_S_TemperatureReturn": 48.1,
                                       "CHC_S_VolumeFlow": 1250,
                                       "CHC_S_Power_Heating": 20.8 } }
  ],
  "WBS_11_TS1": [ { "ts": ..., "values": { "temperature": 21.3 } } ]
}
```

---

## 3. Stage 1 - Rule chain routing

| # | Chain | File | What it does |
|---|-------|------|--------------|
| 1 | **Root Rule Chain** | `rule chains/root_rule_chain.json` | first node is `Device Profile Node` (index 9) -> hands the msg to the profile's chain |
| 2 | **RESI CORE** | `rule chains/resi.json` | `Message Type Switch` (:19); `Post telemetry`, `Post attributes` and `RPC Request from Device` all route to `RESI Device` (:111, `TbRuleChainInputNode`) |
| 3 | **RESI DEVICE** | `rule chains/resi_device.json` | the actual telemetry pipeline (section 4) |

Chain IDs referenced by the input nodes in `resi.json`:

| Target | ruleChainId |
|--------|-------------|
| RESI Device | `43153980-737f-11ef-8a75-b31459678eb5` |
| EM Alarm Handler | `88aee890-6f6c-11ef-8170-db057079800d` |
| Inactivity Alarm Handler | `8f873a50-6f6c-11ef-8a75-b31459678eb5` |
| set relation | `060a9640-ec50-11ee-aec0-2f1fd908e9e8` |

---

## 4. Stage 2 - `resi_device.json` node by node

Entry point is node **4 `Device Profile`** (`firstNodeIndex: 4`).

### 4.1 Node inventory

| # | Type | Name | Line |
|---|------|------|------|
| 0 | TbMsgTypeSwitchNode | Post Telemetry | |
| 1 | TbTransformMsgNode (JS) | Process Meters | `:76` |
| 2 | TbChangeOriginatorNode | Change Device | `:108` |
| 3 | TbTransformMsgNode (JS) | Process Datapoints Multi | *(unreachable, see 7.3)* |
| 4 | TbDeviceProfileNode | Device Profile | `:180` |
| 5 / 6 | TbCreateAlarmNode / TbClearAlarmNode | Inactivity Alarm | |
| 7 | TbGetTelemetryNode | Get Last Meter Telemetry | *(unreachable)* |
| 8 / 9 / 10 | Log / Log / RPC | RPC + Other | |
| 11 | TbJsSwitchNode | Check if msg empty | `:401` |
| 12 / 13 | TbChangeOriginatorNode | Switch To Kit -> Switch to Measurement | *(unreachable)* |
| 14 | TbMsgTimeseriesNode | Save Timeseries | `:517` |
| 15 | TbMsgTimeseriesNode | Save Timeseries | `:547` |
| 16 | TbRenameKeysNode | Rename Power Keys | `:581` |
| 17 | TbChangeOriginatorNode | Switch to Measurement | `:615` |
| 18 | TbTransformMsgNode (JS) | Rename Temperature Keys for TS1&TS2 | `:661` |
| 19 | TbChangeOriginatorNode | Switch to Measurement VR Device | `:693` |
| 20 | TbMsgTimeseriesNode | Save Timeseries | `:739` |
| 21 | TbCheckRelationNode | Check relation to Measurement (VR) | `:773` |
| 22 | TbDeviceStateNode | Set Activity | `:807` |
| 23 | TbTransformMsgNode | Skip negative Consumption/Energy/Power | `:833` |
| 24 | TbCheckRelationNode | Check relation to Measurement | `:865` |
| 25 | TbChangeOriginatorNode | Switch to Measurement | `:897` |
| 26 | TbMsgTimeseriesNode | Save Timeseries | `:943` |
| 27 | TbTransformMsgNode (TBEL) | Normalize Data | `:977` |
| 28 | TbGetAttributesNode | Get Measurement Attributes | `:1009` |

### 4.2 Flow graph

```
 4 Device Profile
   |
 0 Post Telemetry (msg type switch)
   |  [Post telemetry]
 11 Check if msg empty
   |  [msg]
 1 Process Meters            <-- splits batch, computes CHC_S_TemperatureDiff
   |
 2 Change Device             <-- originator: GATEWAY -> DEVICE
   |
   +--> 22 Set Activity
   |
   +--> 16 Rename Power Keys
          |
        23 Skip negative (no-op)
          |
        15 Save Timeseries   <-- raw CHC_* on the DEVICE
          |
          +----------------------------+
          |                            |
    21 Check relation "VR"      24 Check relation "Measurement"
          |                            |  [True]
    [True]|      [False]          25 Switch to Measurement   <-- originator = MEASUREMENT ASSET
          |         |                  |
  19 Switch to    18 Rename Temp   28 Get Measurement Attributes
     Measurement     TS1/TS2            |
     VR Device       |                  +--> 26 Save Timeseries   <-- raw CHC_* on the ASSET
          |        17 Switch to         |
    20 Save Ts       Measurement        +--> 27 Normalize Data
                     |                          |
                   14 Save Ts                 26 Save Timeseries  <-- canonical keys on the ASSET
                   (raw keys on the ASSET)
```

### 4.3 Node details

#### Node 11 - `Check if msg empty` (`:401`)
JS switch. Empty object -> `empty msg` (dead end), otherwise -> `msg` -> Process Meters.

#### Node 1 - `Process Meters` (`:76`) — **creates `*_TemperatureDiff`**
`TbTransformMsgNode`, JS. Three jobs:

1. **Temperature difference** for each configured pair:

   ```js
   var temperaturePairs = [
     { flow: "CHC_S_TemperatureFlow", return: "CHC_S_TemperatureReturn", difference: "CHC_S_TemperatureDiff" },
     { flow: "H_S_TemperatureFlow",   return: "H_S_TemperatureReturn",   difference: "H_S_TemperatureDiff" }
   ];
   // tempDifference = (flowTemp - returnTemp).toFixed(3)
   ```

   The meter does **not** send `CHC_S_TemperatureDiff` — it is created here.
2. **Split** the gateway batch into one message per device (`splitMessage`).
3. **Metadata**: `deviceName` (with `_LTE` rewritten to `_gw`), `ts`, `ts_end = ts`,
   `ts_start = ts_end - 1800000` (30 min window, used by the unreachable
   `Get Last Meter Telemetry` node).

#### Node 2 - `Change Device` (`:108`) — **originator hop 1**
```json
{ "originatorSource": "ENTITY", "entityType": "DEVICE",
  "entityNamePattern": "${deviceName}",
  "relationsQuery": { "direction": "FROM", "maxLevel": 1,
                      "filters": [{ "relationType": "Contains" }] },
  "preserveOriginatorIfCustomer": true }
```
Resolves the gateway's `Contains` children by name. From here on the originator is the
physical device.

#### Node 22 - `Set Activity` (`:807`)
`ACTIVITY_EVENT` — keeps the device online, drives the inactivity alarm path (nodes 5/6).

#### Node 16 - `Rename Power Keys` (`:581`)
`TbRenameKeysNode`, `renameIn: DATA`:

| From | To |
|------|----|
| `CHC_C_Power_Cooling` | `CHC_S_Power_Cooling` |
| `CHC_C_Power_Heating` | `CHC_S_Power_Heating` |

The `CHC_C_*` inputs were produced by `Process Datapoints Multi`, which is currently
unreachable (see 7.3), so this node is effectively a pass-through today.

#### Node 23 - `Skip negative Consumption/Energy/Power` (`:833`)
Despite the name, **both** `jsScript` and `tbelScript` are
`return {msg: msg, metadata: metadata, msgType: msgType};` — nothing is filtered.

#### Node 15 - `Save Timeseries` (`:547`)
`defaultTTL: 0`, `useServerTs: false`, `processingSettings: ON_EVERY_MESSAGE`.
**First persistence: raw `CHC_*` keys on the DEVICE.** All Save Timeseries nodes in
this chain use the same config.

#### Node 21 - `Check relation to Measurement` (VR) (`:773`)
```json
{ "direction": "TO", "entityType": "DEVICE", "relationType": "VR",
  "checkForSingleEntity": false }
```
Detects virtual/repeater devices.

- **True** -> node 19 `Switch to Measurement VR Device` (relation `VR`, `TO`, `DEVICE`)
  -> node 20 Save Timeseries.
- **False** -> node 18.

#### Node 18 - `Rename Temperature Keys for TS1&TS2` (`:661`)
JS. If `metadata.deviceName` contains `_TS1` / `_TS2`, renames `temperature` to
`temperature1` / `temperature2`. Note this is the **legacy** naming — `Normalize Data`
uses `auxT1_C` / `auxT2_C` instead.

Then node 17 `Switch to Measurement` (relation `Measurement`, `TO`, `ASSET`)
-> node 14 Save Timeseries: **raw keys on the Measurement asset.**

#### Node 24 - `Check relation to Measurement` (`:865`)
```json
{ "direction": "TO", "relationType": "Measurement", "checkForSingleEntity": false }
```
Runs in parallel to node 21, from the same Save Timeseries.

#### Node 25 - `Switch to Measurement` (`:897`) — **originator hop 2 (the important one)**
```json
{ "originatorSource": "RELATED", "preserveOriginatorIfCustomer": false,
  "relationsQuery": { "direction": "TO", "maxLevel": 1,
                      "filters": [{ "relationType": "Measurement",
                                    "entityTypes": ["ASSET"] }] } }
```
The relation is `Measurement asset --Measurement--> Device`; direction `TO` walks it
backwards from the device to the asset. **This is how telemetry reaches the Measurement.**

> If this relation is missing, everything downstream silently stops — no canonical keys,
> no Calculated Fields, no alarms. See the `copy-project.js` caveat in section 7.4.

#### Node 28 - `Get Measurement Attributes` (`:1009`)
```json
{ "fetchTo": "METADATA", "tellFailureIfAbsent": false,
  "serverAttributeNames": ["installationType"] }
```
Server attributes are prefixed with `ss_` in metadata -> `metadata.ss_installationType`.

**Only `installationType` is fetched.** The other `ss_*` attributes referenced by the
old TBEL script (`ss_flowOnThreshold`, `ss_designPower`, `ss_designDeltaT`,
`ss_calculatePower`, `ss_fluidType`, `ss_weeklySchedule`) are no longer needed here —
they are read by the Calculated Fields instead.

Two outputs on `Success`:
- -> node 26 Save Timeseries (raw `CHC_*` on the asset)
- -> node 27 Normalize Data -> node 26 Save Timeseries (canonical keys on the asset)

#### Node 27 - `Normalize Data` (`:977`) — **creates the canonical keys**
`TbTransformMsgNode`, TBEL. Pure key mapping; no derived calculations.

| Input | Output | Conversion |
|-------|--------|------------|
| `CHC_S_TemperatureFlow` | `T_flow_C` | - |
| `CHC_S_TemperatureReturn` | `T_return_C` | - |
| `CHC_S_TemperatureDiff` | `dT_K` | `Math.abs()` |
| *(fallback)* `T_flow_C - T_return_C` | `dT_K` | `abs`, rounded to 3 decimals |
| `CHC_S_VolumeFlow` | `Vdot_m3h` | **/ 1000** (input is l/h) |
| `CHC_S_Velocity` | `v_ms` | - |
| `CHC_S_Power_Heating` | `P_th_kW` | if `installationType != "cooling"` |
| `CHC_S_Power_Cooling` | `P_th_kW` | if `installationType == "cooling"` |
| `CHC_M_Energy_Heating` | `E_th_kWh` | if `installationType != "cooling"` |
| `CHC_M_Energy_Cooling` | `E_th_kWh` | if `installationType == "cooling"` |
| `CHC_M_Volume` | `V_m3` | - |
| `temperature` (device ends `_TS1`) | `auxT1_C` | - |
| `temperature` (device ends `_TS2`) | `auxT2_C` | - |
| `temperature` (other) | `temperature` | passthrough |

Output rules:
- `msg.ts` is preserved if present.
- If `newValues` is empty the node returns `{}` — nothing is written.
- Default `installationType` is `"heating"` when the attribute is absent.

---

## 5. Stage 3 - Calculated Fields on the Measurement asset

Defined on **Asset Profile "Measurement"**, so they apply to every Measurement
automatically. They read the canonical keys plus Measurement server attributes, and have
access to rolling windows of history.

| CF | Outputs | Main inputs |
|----|---------|-------------|
| `derived_basic` | `is_on`, `load_class`, `dT_flag`, `data_quality` | `Vdot_m3h`, `P_th_kW`, `dT_K`, `ss_flowOnThreshold`, `ss_designPower`, `ss_designDeltaT` |
| `derived_power` | `P_th_calc_kW`, `P_deviation_pct`, `P_sensor_flag` | `Vdot_m3h`, `dT_K`, `T_flow_C`, `ss_fluidType`, `ss_calculatePower` |
| `derived_schedule` | `schedule_violation` | `is_on`, `ss_weeklySchedule` |
| rolling window | `dT_collapse_flag` (15 min), `flow_spike_flag` (5 min), `cycling_flag` + `cycle_count` (30 min), `power_stability` + `power_unstable_flag` (15 min), `oscillation_count` + `oscillation_flag` (15 min), `runtime_pct` (1 h) | `dT_K`, `Vdot_m3h`, `is_on`, `P_th_kW` |

Total on a Measurement: **12 raw + 2 context + 17 CF = 31 telemetry keys**
(`analysis/ECO_Data_Catalog.md:520`).

Full formulas, thresholds, CF IDs and TBEL gotchas (boolean/map handling, `foreach`,
attribute guards): `analysis/ECO_Data_Catalog.md` section 16.

Provisioning scripts:

| Script | Creates |
|--------|---------|
| `scripts/create-derived-basic-cf.js` | `derived_basic` |
| `scripts/create-derived-power-cf.js` | `derived_power` |
| `scripts/create-derived-schedule-cf.js` | `derived_schedule` |
| `scripts/inspect-cfs.js`, `scripts/dump-cf-expr.js` | inspection |
| `scripts/reprocess-all-measurements.js` | backfill |

### Context telemetry (not from the device)

| Key | Source |
|-----|--------|
| `T_outside_C` | Weather API -> Project -> propagated |
| `RH_outside_pct` | same |

Chains: `rule chains/get_open_meteo_data.json`, `get_historical_weather.json`,
`weather_calculations_hdd_cdd.json`, and `sensor_weather_propagation.json`
(`Check Temperature Key` -> `Check WeatherSensor Relation` -> `Transform to Weather Keys`
-> `Switch to Project` -> `Get Project Attributes` -> `Check Source and Active`
-> `Save Weather Telemetry`).

---

## 6. Stage 4 - `measurement.json` (Measurement CORE) and alarms

The `Save Timeseries` nodes in `resi_device` write directly to the DB — they do **not**
re-enter a rule chain. The `Post telemetry` branch of Measurement CORE is fed by
**Calculated Field output**, which is dispatched through the rule engine as a
`POST_TELEMETRY_REQUEST` on the asset. That is why the alarm switches can see CF-only
keys such as `dT_collapse_flag`, which never appear in any `resi_device` message.

```
 6 Device Profile Node (:224)
   |
 2 Message Type Switch (:103)
   |  [Post telemetry]
 0 Save Timeseries (:35)
   |
   +--> 7  Check dT Collapse    (:255) -> 8/9   Create/Clear dT Collapse Alarm
   +--> 10 Check Cycling        (:362) -> 11/12 Create/Clear Cycling Alarm
   +--> 13 Check Flow Spike     (:469) -> 14/15 Create/Clear Flow Spike Alarm
   +--> 16 Check Power Unstable (:576) -> 17/18 Create/Clear Power Unstable Alarm
   +--> 20 Check Oscillation    (:711) -> 21/22 Create/Clear Oscillation Alarm
                                              |
                                        19 EM Alarm Handler
```

All five switches share the same shape:

```js
var v = msg.get('values');
var f = (v != null) ? v.get('dT_collapse_flag') : null;
if (f == null) return ['skip'];
return f == true ? ['create'] : ['clear'];
```

So the CF produces the flag; the rule chain only turns the flag into an alarm.

Other branches of Measurement CORE:

| Trigger | Target |
|---------|--------|
| `Post attributes` / `Attributes Updated` | `Check reprocessRequest` (:845) -> `Trigger CF Reprocessing` (:877) |
| `Alarm Created/Updated/Cleared`, `Entity Created` | `EM Alarm Handler` (:681, :814) |

### EM Alarm Handler (`rule chains/em_alarm_handler.json`)
Entry node 9 `Input Switch`. Counts alarms (`TbAlarmsCountNodeV2`), writes state
attributes, and for `Post telemetry` walks
`Check Measurement Relation` -> `Switch to Measurement` -> `Get Measurement Progress`
-> `Filter Active Measurement` -> `Switch back to Device`, so alarm state is only
maintained for Measurements whose progress is active.

### CF Reprocess Handler (`rule chains/cf_reprocess_handler.json`)
Triggered by a `reprocessRequest` attribute. Sets `reprocessing=true`, logs in via REST,
creates a temporary Calculated Field, triggers reprocessing, polls status
(30 s / 60 s / 60 s), deletes the temp CF, sets `reprocessing=false`.

---

## 7. Known issues and discrepancies

### 7.1 The Measurement is written multiple times per message
Three `Save Timeseries` nodes can target the same Measurement asset for one incoming
message:

| Path | Payload |
|------|---------|
| 21(False) -> 18 -> 17 -> 14 | raw `CHC_*` (+ `temperature1/2`) |
| 24(True) -> 25 -> 28 -> 26 | raw `CHC_*` |
| 24(True) -> 25 -> 28 -> 27 -> 26 | canonical keys |

Result: both key namespaces coexist on the asset, and the raw keys are written twice.

### 7.2 `Skip negative Consumption/Energy/Power` does nothing
Node 23 is a pass-through. Negative meter deltas are **not** filtered anywhere in this
chain.

### 7.3 Two unreachable branches
In the exported JSON these nodes have no inbound connection:

- `7 Get Last Meter Telemetry` -> `3 Process Datapoints Multi` — the consumption-delta
  calculation. It would map meter readings to `*_C_*` consumption keys
  (`CHC_M_Energy_Heating` -> `CHC_C_Energy_Heating`, `CHC_M_Volume` -> `CHC_C_Volume`,
  `H_M_*`, `E_M_ActiveEnergyTotal`, `W_M_Volume`, `WW_M_Volume`, `CW_M_Volume`,
  `G_M_Volume`), apply `ss_energyUnit` conversion (`Wh` 0.001, `kJ` 0.0002777777,
  `kWh` 1, `GWh` 1000) and derive power from energy deltas.
- `12 Switch To Kit` -> `13 Switch to Measurement` (relation `Contains`).

`Process Meters` also still sets `metadata.ts_start`/`ts_end` for the dead
`Get Last Meter Telemetry` node, and `Rename Power Keys` still maps the `CHC_C_Power_*`
keys that only the dead branch produced.

> This reflects the on-disk export. Pull the live chain
> (`node sync/sync.js pull-rulechain "RESI Device"`) before acting on it.

### 7.4 The `Measurement` relation is the single point of failure
Node 25 is the only route to the asset. `scripts/copy-project.js` copies `Owns` but not
all hierarchy relations, which is how copied projects end up with devices that store
telemetry but produce no canonical keys.

### 7.5 Documentation drift
| File | State |
|------|-------|
| `rule chains/scripts/normalize_data.tbel` | **stale** — 484 lines, still contains `is_on`, `load_class`, `dT_flag`, `P_th_calc_kW`, `schedule_violation`, outlier detection. The deployed node (`resi_device.json:977`) is the cleaned mapping-only version. |
| `analysis/DERIVED_TELEMETRY_LOGIC.md` | key-mapping table accurate; the derived-value sections describe the pre-CF TBEL version |
| `rule chains/scripts/rename_temperature_keys.js` / `.tbel` | legacy, superseded by Normalize Data |

---

## 8. Where each telemetry key is created

| Key | Created by | Location |
|-----|-----------|----------|
| `CHC_S_TemperatureFlow`, `CHC_S_TemperatureReturn`, `CHC_S_VolumeFlow`, `CHC_S_Velocity`, `CHC_S_Power_*`, `CHC_M_*` | the meter | via IoT Gateway |
| `CHC_S_TemperatureDiff`, `H_S_TemperatureDiff` | **rule chain** | `resi_device.json:76` Process Meters |
| `CHC_S_Power_Heating/Cooling` (from `CHC_C_*`) | rule chain | `resi_device.json:581` Rename Power Keys |
| `temperature1`, `temperature2` | rule chain (legacy) | `resi_device.json:661` |
| `T_flow_C`, `T_return_C`, `dT_K`, `Vdot_m3h`, `v_ms`, `P_th_kW`, `E_th_kWh`, `V_m3`, `auxT1_C`, `auxT2_C` | rule chain | `resi_device.json:977` Normalize Data |
| `is_on`, `load_class`, `dT_flag`, `data_quality` | Calculated Field | asset profile `derived_basic` |
| `P_th_calc_kW`, `P_deviation_pct`, `P_sensor_flag` | Calculated Field | asset profile `derived_power` |
| `schedule_violation` | Calculated Field | asset profile `derived_schedule` |
| `dT_collapse_flag`, `flow_spike_flag`, `cycling_flag`, `cycle_count`, `power_stability`, `power_unstable_flag`, `oscillation_count`, `oscillation_flag`, `runtime_pct` | Calculated Field | asset profile, rolling windows |
| `T_outside_C`, `RH_outside_pct` | weather chains | Project -> propagated |

---

## 9. Adding a new telemetry key

**A) New raw key from the meter**
1. Confirm the gateway sends it.
2. Add the mapping in `Normalize Data` (`resi_device.json:977`) — and mirror it in
   `rule chains/scripts/normalize_data.tbel`.
3. Add unit + label in `js library/ECO Project Wizard.js` (~`:4846` units, `:4863`
   labels, `:5236` per-systemType key lists).
4. Document it in `analysis/ECO_Data_Catalog.md`.
5. Push: `node sync/sync.js push-rulechain "RESI Device"`.

**B) New derived key**
1. Write it as a **Calculated Field**, not as rule chain logic — that is the current
   architecture.
2. Model it on `scripts/create-derived-basic-cf.js`.
3. Mind the TBEL rules in `ECO_Data_Catalog.md` section 16 (use `if/else` for booleans,
   `!=` not `!==`, `argName.count()`, guard missing attributes).
4. If it should raise an alarm, add a `TbJsSwitchNode` + Create/Clear pair in
   `measurement.json` following the five existing switches.
5. Backfill history with `scripts/reprocess-all-measurements.js`.

**C) Rule chain workflow reminder** (see CLAUDE.md)
```
1. PULL    node sync/sync.js pull-rulechain "RESI Device"
2. BACKUP  cp "rule chains/resi_device.json" "backups/manual/resi_device_$(date +%Y%m%d_%H%M%S).json"
3. EDIT
4. PUSH    node sync/sync.js push-rulechain "RESI Device"
```

---

## 10. File index

| File | Role |
|------|------|
| `rule chains/root_rule_chain.json` | tenant root, routes to device profile chains |
| `rule chains/resi.json` | RESI CORE — profile chain, entry to the device pipeline |
| `rule chains/resi_device.json` | **the telemetry pipeline** |
| `rule chains/measurement.json` | Measurement CORE — alarms on CF flags |
| `rule chains/em_alarm_handler.json` | alarm counting + state attributes |
| `rule chains/inactivity_alarm_handler.json` | device offline alarms |
| `rule chains/cf_reprocess_handler.json` | CF backfill orchestration |
| `rule chains/sensor_weather_propagation.json` | sensor temperature -> Project weather |
| `rule chains/get_open_meteo_data.json`, `get_historical_weather.json`, `weather_calculations_hdd_cdd.json` | weather ingestion |
| `rule chains/scripts/normalize_data.tbel` | *(stale)* Normalize Data source |
| `rule chains/scripts/README.md` | mapping + derived telemetry reference |
| `analysis/ECO_Data_Catalog.md` | full key catalog, CF formulas, thresholds |
| `analysis/DERIVED_TELEMETRY_LOGIC.md` | derived telemetry reference (partly pre-CF) |
| `analysis/ECO_Alarming_Concept.md` | thresholds and escalation |
