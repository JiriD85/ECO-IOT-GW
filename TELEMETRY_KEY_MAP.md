# Telemetry Key Map — from raw meter register to Measurement asset

**Reference case:** `EPI_8_15` (label "Kälteverteilung Ost"), an **active** Measurement, fed by a single
flow device `ECO_1C0034000E57435535333920_PF1` (`P-Flow D116`) behind kit `DBKIT24EU-0009`.

**Verified against the live server on 2026-08-06.** Every formula in this document was read from the
running system (rule chain metadata + `GET /api/ASSET_PROFILE/{id}/calculatedFields`), not from the
on-disk exports — the exports are behind, see [§9](#9-known-divergences-from-the-on-disk-exports).

| | |
|---|---|
| Measurement asset | `59000920-89b0-11f1-8f56-1bdafa1b1051` |
| Source device | `b55a7300-da74-11ef-ac46-b3e2970cc2a5` |
| Kit asset | `e7b33e40-da74-11ef-ac46-b3e2970cc2a5` (`DBKIT24EU-0009`) |
| Asset profile (carries the CFs) | `fe06fd60-5a4c-11ef-9653-5b043856d68a` |
| Rule chain `RESI Device` | `43153980-737f-11ef-8a75-b31459678eb5` |

Companion documents:

* [TELEMETRY_PIPELINE.md](TELEMETRY_PIPELINE.md) — the transport/rule-engine path (how a message
  physically travels from gateway to Measurement asset)
* [../analysis/ECO_Data_Catalog.md](../analysis/ECO_Data_Catalog.md) — attribute catalog and thresholds

This document answers a narrower question: **for each of the 32 telemetry keys on the Measurement
asset, what exactly computes it, from which inputs?**

---

## 1. The four layers

```
LAYER 0   DEVICE  ECO_1C0034000E57435535333920_PF1
          27 raw keys (CHC_*), written by "Save Timeseries" while the
          originator is still the DEVICE
                |
                |  originator switch: Measurement --[Measurement]--> Device, direction TO
                v
LAYER 1   Normalize Data   (RESI Device, live node 23, TBEL)
          rename + unit conversion only -> 8 keys on the ASSET
                |
                v
LAYER 2   10 Calculated Fields on asset profile "Measurement"
          -> 20 keys.  CF output re-enters the rule engine as
          POST_TELEMETRY_REQUEST, so CFs can consume other CFs' output.
                |
                v
LAYER 3   measurement.json (5 alarm switches) -> em_alarm_handler.json
          -> 4 *AlarmsCount keys + the `state` server attribute

          8 + 20 + 4 = 32 keys
```

---

## 2. Layer 0 — raw keys on the device

All 27 keys carry the same timestamp cadence (~1 min, latest 2026-08-06T09:59).
Only **9** are consumed downstream:

| Device key | Latest | Consumed by |
|---|---|---|
| `CHC_S_TemperatureFlow` | 12.79 | `T_flow_C` |
| `CHC_S_TemperatureReturn` | 9.78 | `T_return_C` |
| `CHC_S_TemperatureDiff` | 3.01 | `dT_K` |
| `CHC_S_VolumeFlow` | 15220.90722656 | `Vdot_m3h` |
| `CHC_S_Velocity` | 0.82456601 | `v_ms` |
| `CHC_S_Power_Heating` | 53.3333245 | `P_th_measured_kW` (installationType heating) |
| `CHC_S_Power_Cooling` | 0 | `P_th_measured_kW` (installationType cooling) |
| `CHC_M_Energy_Heating` | 20649.24444444 | `E_th_kWh` (heating) |
| `CHC_M_Energy_Cooling` | 462.40333333 | `E_th_kWh` (cooling) |
| `CHC_M_Volume` | 87506 | `V_m3` |

**Not consumed anywhere:** `CHC_C_Energy_Cooling`, `CHC_C_Energy_Heating`, `CHC_C_Volume`,
`CHC_C_Volume_Neg`, `CHC_C_Volume_Net`, `CHC_M_Power_Heating`, `CHC_M_Power_Cooling`,
`CHC_M_Volume_Neg`, `CHC_M_Volume_Net`.

**Legacy batch blobs**, frozen at 2025-01-24T17:18, from the pre-split gateway payload format —
`ECO_1C0034000E57435535333920_LTE`, `_PF1`, `_TS1`, `_TS2`. Each holds a whole
`[{ts, values:{...}}]` array as a single value. Dead data, no consumer.

### `CHC_S_TemperatureDiff` is created by the rule chain, not by the meter

Live node 1 `Process Meters` (JS) computes it before the originator ever changes:

```js
var temperaturePairs = [
  { flow: "CHC_S_TemperatureFlow", return: "CHC_S_TemperatureReturn", difference: "CHC_S_TemperatureDiff" },
  { flow: "H_S_TemperatureFlow",   return: "H_S_TemperatureReturn",   difference: "H_S_TemperatureDiff" }
];
var tempDifference = (flowTemp - returnTemp).toFixed(3);   // signed, 3 decimals
```

The same node also splits the gateway batch into one message per device, rewrites the `_LTE` suffix
to `_gw`, and sets `metadata.deviceName / ts / ts_end / ts_start (= ts_end - 1800000)`.

Live node 12 `Rename Power Keys` (`TbRenameKeysNode`) then normalises two vendor variants:
`CHC_C_Power_Cooling -> CHC_S_Power_Cooling`, `CHC_C_Power_Heating -> CHC_S_Power_Heating`.

Live node 19 `Skip negative Consumption/Energy/Power` is a **no-op** —
`return {msg: msg, metadata: metadata, msgType: msgType};`. The name is misleading.

---

## 3. Layer 1 — `Normalize Data` → 8 keys on the asset

Pure key mapping and unit conversion. No thresholds, no derivation. `installationType` reaches the
script as `metadata.ss_installationType`, fetched by live node 24 `Get Measurement Attributes`
(`fetchTo: METADATA`, `serverAttributeNames: ["installationType"]`, `tellFailureIfAbsent: false`,
so the script defaults to `"heating"` when the attribute is missing).

| Asset key | Unit | Formula | EPI_8_15 latest |
|---|---|---|---|
| `T_flow_C` | °C | `CHC_S_TemperatureFlow` | 12.79 |
| `T_return_C` | °C | `CHC_S_TemperatureReturn` | 9.78 |
| `dT_K` | K | `abs(CHC_S_TemperatureDiff)`; fallback `abs(round(T_flow_C - T_return_C, 3))` | 3.01 |
| `Vdot_m3h` | m³/h | `CHC_S_VolumeFlow / 1000` (input is l/h) | 15.220907226560001 |
| `v_ms` | m/s | `CHC_S_Velocity` | 0.82456601 |
| `P_th_measured_kW` | kW | `installationType == "cooling" ? CHC_S_Power_Cooling : CHC_S_Power_Heating` | 53.3333245 |
| `E_th_kWh` | kWh | `installationType == "cooling" ? CHC_M_Energy_Cooling : CHC_M_Energy_Heating` | 20649.24444444 |
| `V_m3` | m³ | `CHC_M_Volume` | 87506 |

Also defined in the script but **not produced for EPI_8_15**, because only a `_PF1` device is
assigned (no temperature sensors):

| Asset key | Formula |
|---|---|
| `auxT1_C` | `temperature`, when `metadata.deviceName` ends with `_TS1` |
| `auxT2_C` | `temperature`, when `metadata.deviceName` ends with `_TS2` |
| `temperature` | `temperature` from any other device (passthrough) |

If `newValues` ends up empty the node emits `{}` — the following `Save Timeseries` writes nothing.

> **Note:** `dT_K` is stored as an **absolute** value here, while Layer 2 recomputes a *signed* dT
> from `T_flow_C - T_return_C`. See [§8](#8-behavioural-notes-and-pitfalls).

---

## 4. Layer 2 — 10 Calculated Fields → 20 keys

All CFs live on the **asset profile** `Measurement` (`fe06fd60-5a4c-11ef-9653-5b043856d68a`), so they
apply to every Measurement automatically. All are `SCRIPT` type with `output.type = TIME_SERIES` and
stamp `ts: ctx.latestTs`.

Every single CF begins with the same two guards:

```js
if (reprocessing == true) { return {}; }
if (progress != 'active')  { return {}; }
```

`reprocessing` and `progress` are `SERVER_SCOPE` attributes on the Measurement, with CF defaults
`"false"` and `"active"`.

### 4.1 `derived_power` — `8d2f1a50-0211-11f1-9979-9f3434877bb4`

**Outputs:** `P_th_kW`, `P_deviation_pct`, `P_sensor_flag`

| Argument | Type | Default |
|---|---|---|
| `Vdot_m3h`, `T_flow_C`, `T_return_C`, `P_th_measured_kW` | TS_LATEST | — |
| `calculatePower` | ATTRIBUTE SERVER_SCOPE | `false` |
| `fluidType` | ATTRIBUTE SERVER_SCOPE | `water` |
| `installationType` | ATTRIBUTE SERVER_SCOPE | `heating` |
| `reprocessing`, `progress` | ATTRIBUTE SERVER_SCOPE | `false` / `active` |

```
if calculatePower == true and Vdot/T_flow/T_return all present:
    cp, rho  by fluidType:  water 4.18 / 998
                            glycol20 3.95 / 1032
                            glycol30 3.74 / 1045
                            glycol40 3.55 / 1058
    dT_eff = (installationType == "cooling") ? T_return - T_flow : T_flow - T_return
    P_calc = (dT_eff > 0) ? rho * cp * Vdot_m3h * dT_eff / 3600 : 0
    P_th_kW = round(P_calc, 3)

    if P_th_measured_kW != null and P_calc > 0.1:
        P_deviation_pct = round((P_th_measured_kW - P_calc) / P_calc * 100, 1)
        P_sensor_flag   = abs(dev) < 10 ? "ok" : abs(dev) < 25 ? "warn" : "error"

else if P_th_measured_kW != null:
    P_th_kW = P_th_measured_kW          # verbatim passthrough

if P_th_kW == null: return {}
```

**`P_th_kW` is a computed value, not the meter reading.** The meter's own power survives only as
`P_th_measured_kW`. Flipping `calculatePower` to false silently changes the provenance of `P_th_kW`
without changing the key name.

Wrong-direction flow (`dT_eff <= 0`) yields `P_th_kW = 0`, never a negative power.

### 4.2 `derived_basic` — `6cac3240-0211-11f1-9b0a-33b9bcf3ddd0`

**Outputs:** `is_on`, `load_class`, `dT_flag`, `data_quality`, `temp_inversion_flag`

| Argument | Type | Default |
|---|---|---|
| `T_flow_C`, `T_return_C`, `Vdot_m3h`, `P_th_kW` | TS_LATEST | — |
| `designDeltaT`, `designPower` | ATTRIBUTE SERVER_SCOPE | (empty) |
| `flowOnThreshold` | ATTRIBUTE SERVER_SCOPE | `0.05` |
| `reprocessing`, `progress` | ATTRIBUTE SERVER_SCOPE | `false` / `active` |

```
if Vdot_m3h == null: return {}
dT_K = (T_flow_C != null and T_return_C != null) ? T_flow_C - T_return_C : null   # SIGNED
threshold = flowOnThreshold ?? 0.1

is_on = Vdot_m3h > threshold

# load_class  (only if P_th_kW and designPower > 0)
loadPct = P_th_kW / designPower * 100
    < 30  -> "low"
    < 60  -> "mid"
    else  -> "high"

# dT_flag  (only if dT_K, designDeltaT > 0 AND load_class was set)
dTRatio = dT_K / designDeltaT
    load_class == "low":   >= 0.30 ok | >= 0.15 warn | else severe
    otherwise:             >= 0.50 ok | >= 0.30 warn | else severe

# data_quality — hard plausibility bounds
error if  T_flow_C  outside [-50, 150]
      or  T_return_C outside [-50, 150]
      or  dT_K      outside [-50, 100]
      or  Vdot_m3h  outside [0, 1000]
      or  P_th_kW   outside [-10000, 10000]
else ok

# temp_inversion_flag
is_on ? (dT_K < -0.5) : false
```

Note the chain: **no `P_th_kW` → no `load_class` → no `dT_flag`.**

### 4.3 `derived_energy` — `d236add0-080a-11f1-9c7a-33b9bcf3ddd0`

**Output:** `E_th_delta_kWh` — per-interval energy by trapezoidal integration of power.

| Argument | Type | Window |
|---|---|---|
| `P_th_kW` | TS_ROLLING | 300 000 ms (5 min), limit **2** |
| `reprocessing`, `progress` | ATTRIBUTE | — |

```
if P_th_kW.count() < 2: return {}
iterate the rolling window, keep the last two (value, ts) pairs
dt_ms = currTs - prevTs
if dt_ms <= 0 or dt_ms > 600000: return {}       # gap > 10 min -> skip
E_th_delta_kWh = round((prevVal + currVal) / 2 * dt_ms / 3600000, 4)
```

This is the only *incremental* energy key. `E_th_kWh` is the raw meter **counter** and never resets.

### 4.4 `derived_schedule` — `aee1f6e0-0211-11f1-9979-9f3434877bb4`

**Output:** `schedule_violation`

| Argument | Type | Default |
|---|---|---|
| `Vdot_m3h` | TS_LATEST | — |
| `flowOnThreshold` | ATTRIBUTE | `0.05` |
| `weeklySchedule` | ATTRIBUTE | `null` |
| `reprocessing`, `progress` | ATTRIBUTE | `false` / `active` |

```
is_on = Vdot_m3h > (flowOnThreshold ?? 0.1)          # recomputed locally, not read from telemetry
if weeklySchedule empty: return {}
schedule = isMap(weeklySchedule) ? weeklySchedule : JSON.parse(weeklySchedule)
tzOffset = schedule.timezoneOffset ?? 60             # minutes

# hand-rolled calendar + DST (no date library in TBEL)
derive year/month/dayOfMonth from ctx.latestTs by subtracting day counts
isDST = (month 4..9) or (month == 3 and day >= 25) or (month == 10 and day < 25)
effectiveOffset = tzOffset + (isDST ? 60 : 0)
localTs = ctx.latestTs + effectiveOffset * 60000
dayName = ["sunday",...][ (localTs/86400000 + 4) % 7 ]
currentMinutes = (localTs % 86400000) / 60000

todayValue = schedule[dayName]
  "true"                      -> within schedule
  object with enabled == true -> within if start <= currentMinutes <= end  ("HH:MM" parsed by substring)
  otherwise                   -> outside

schedule_violation = is_on and not withinSchedule
```

`weeklySchedule` format: see [weekly-schedule-format.md](weekly-schedule-format.md).
The DST rule is an approximation (fixed day-of-month cutoffs, not "last Sunday in March/October"),
so it can be off by up to ~6 days around the transitions.

### 4.5 `dT_collapse_flag` — `684c01c0-0127-11f1-9979-9f3434877bb4`

**Outputs:** `dT_collapse_flag`, `frozen_sensor_flag` (two unrelated detectors in one CF)

| Argument | Type | Window / Default |
|---|---|---|
| `T_flow_C`, `T_return_C`, `Vdot_m3h` | TS_ROLLING | 1 800 000 ms (30 min), limit 100 |
| `collapseThreshold` | ATTRIBUTE | `0.5` |
| `flowOnThreshold` | ATTRIBUTE | `0.05` |
| `reprocessing`, `progress` | ATTRIBUTE | `false` / `active` |

```
# --- frozen_sensor_flag ---
available = count of {T_flow_C, T_return_C, Vdot_m3h} having >= 6 samples
if available >= 2:
    if Vdot_m3h.last() > (flowOnThreshold ?? 0.05):
        frozen_sensor_flag = ALL available series have std() == 0     # AND logic
    else:
        frozen_sensor_flag = false

# --- dT_collapse_flag ---
if T_flow_C.count() >= 3 and T_return_C.count() >= 3:
    currentDT = T_flow_C.last() - T_return_C.last()
    avgDT     = T_flow_C.mean() - T_return_C.mean()
    if avgDT != 0:
        dT_collapse_flag = currentDT < avgDT * (collapseThreshold ?? 0.5)

if neither was set: return {}
```

### 4.6 `flow_spike_flag` — `685884e0-0127-11f1-9979-9f3434877bb4`

| Argument | Type | Window / Default |
|---|---|---|
| `Vdot_m3h` | TS_ROLLING | 300 000 ms (5 min), limit 50 |
| `spikeThreshold` | ATTRIBUTE | `2.0` |

```
if Vdot_m3h.count() < 3 or Vdot_m3h.mean() == 0: return {}
flow_spike_flag = Vdot_m3h.last() > Vdot_m3h.mean() * (spikeThreshold ?? 2.0)
```

### 4.7 `cycling_flag` — `aedba340-012a-11f1-9979-9f3434877bb4`

**Outputs:** `cycling_flag`, `cycle_count`

| Argument | Type | Window / Default |
|---|---|---|
| `Vdot_m3h` | TS_ROLLING | 1 800 000 ms (30 min), limit 200 |
| `flowOnThreshold` | ATTRIBUTE | `0.05` |
| `cyclingThreshold` | ATTRIBUTE | `5` |

```
if Vdot_m3h.count() < 3: return {}
walk the window, isOn = value > (flowOnThreshold ?? 0.1)
cycle_count  = number of isOn transitions (on->off or off->on)
cycling_flag = cycle_count > (cyclingThreshold ?? 6)
```

Note the default mismatch: the CF argument default is `"5"`, the in-script fallback is `6`. The
argument default wins whenever the attribute is absent, so effectively 5.

### 4.8 `power_stability` — `a065a960-0129-11f1-9979-9f3434877bb4`

**Outputs:** `power_stability` (coefficient of variation), `power_unstable_flag`

| Argument | Type | Window / Default |
|---|---|---|
| `P_th_kW`, `Vdot_m3h` | TS_ROLLING | 900 000 ms (15 min), limit 50 |
| `flowOnThreshold` | ATTRIBUTE | `0.05` |
| `stabilityThreshold` | ATTRIBUTE | `0.5` |

```
if P_th_kW.count() < 5: return {}
if P_th_kW.mean() < 1.0: return {}                       # ignore near-off periods
runtimePct = count(Vdot_m3h > flowOnThreshold) / Vdot_m3h.count() * 100
if runtimePct < 80: return {}                            # only judge steady operation

power_stability     = round(P_th_kW.std() / P_th_kW.mean(), 3)
power_unstable_flag = power_stability > (stabilityThreshold ?? 0.5)
```

### 4.9 `runtime_pct` — `a06e8300-0129-11f1-9979-9f3434877bb4`

| Argument | Type | Window / Default |
|---|---|---|
| `Vdot_m3h` | TS_ROLLING | 3 600 000 ms (60 min), limit 200 |
| `flowOnThreshold` | ATTRIBUTE | `0.05` |

```
if Vdot_m3h.count() < 2: return {}
runtime_pct = round(count(Vdot_m3h > flowOnThreshold) / Vdot_m3h.count() * 100, 1)
```

### 4.10 `oscillation_detection` — `30eb6890-0133-11f1-9979-9f3434877bb4`

**Outputs:** `oscillation_count`, `oscillation_flag`

| Argument | Type | Window / Default |
|---|---|---|
| `P_th_kW`, `Vdot_m3h` | TS_ROLLING | 900 000 ms (15 min), limit 60 |
| `flowOnThreshold` | ATTRIBUTE | `0.05` |
| `oscillationThreshold` | ATTRIBUTE | `8` |

```
if P_th_kW.count() < 10: return {}
runtimePct = count(Vdot_m3h > flowOnThreshold) / Vdot_m3h.count() * 100
if runtimePct < 80: return {}
if P_th_kW.mean() < 1.0: return {}

walk P_th_kW:
    diff = value - prevValue
    direction = diff > 0.1 ? +1 : diff < -0.1 ? -1 : 0     # ABSOLUTE 0.1 kW deadband
    count a change whenever direction != 0 and flips sign

oscillation_count = directionChanges
oscillation_flag  = directionChanges > (oscillationThreshold ?? 8)
```

The deadband is absolute — see [§8.2](#82-the-oscillation-deadband-is-power-scale-dependent).

---

## 5. Layer 3 — alarms and alarm counts

`measurement.json` ("Measurement CORE") receives the CF output as `POST_TELEMETRY_REQUEST` and runs
five independent `TbJsSwitchNode`s, one per flag, all with the same shape:

```js
var v = msg.get('values');
var f = (v != null) ? v.get('<flag_key>') : null;
if (f == null) return ['skip'];
return f == true ? ['create'] : ['clear'];
```

| Flag key | Alarm type | Severity |
|---|---|---|
| `dT_collapse_flag` | `dT_Collapse` | MINOR |
| `cycling_flag` | `Cycling` | MINOR |
| `flow_spike_flag` | `Flow_Spike` | MINOR |
| `power_unstable_flag` | `Power_Unstable` | MINOR |
| `oscillation_flag` | `Oscillation` | MINOR |

`em_alarm_handler.json` then produces the four count keys via `TbAlarmsCountNodeV2` (node 2),
counting alarms in status `ACTIVE_UNACK` + `ACTIVE_ACK`:

| Key | Counts severity |
|---|---|
| `criticalAlarmsCount` | CRITICAL |
| `majorAlarmsCount` | MAJOR |
| `minorAlarmsCount` | MINOR |
| `warningAlarmsCount` | WARNING |

Node 1 `Update state attributes` (TBEL) then derives the `state` **server attribute**:
`critical > 0 -> "critical"`, else `major > 0 -> "major"`, else minor/warning, else `"normal"`.

---

## 6. Complete key inventory (32 keys)

| # | Key | Layer | Produced by | Inputs |
|---|---|---|---|---|
| 1 | `T_flow_C` | 1 | Normalize Data | `CHC_S_TemperatureFlow` |
| 2 | `T_return_C` | 1 | Normalize Data | `CHC_S_TemperatureReturn` |
| 3 | `dT_K` | 1 | Normalize Data | `CHC_S_TemperatureDiff` (abs) |
| 4 | `Vdot_m3h` | 1 | Normalize Data | `CHC_S_VolumeFlow / 1000` |
| 5 | `v_ms` | 1 | Normalize Data | `CHC_S_Velocity` |
| 6 | `P_th_measured_kW` | 1 | Normalize Data | `CHC_S_Power_Heating\|Cooling` |
| 7 | `E_th_kWh` | 1 | Normalize Data | `CHC_M_Energy_Heating\|Cooling` |
| 8 | `V_m3` | 1 | Normalize Data | `CHC_M_Volume` |
| 9 | `P_th_kW` | 2 | `derived_power` | `Vdot_m3h`, `T_flow_C`, `T_return_C`, `fluidType`, `installationType`, `calculatePower` |
| 10 | `P_deviation_pct` | 2 | `derived_power` | `P_th_measured_kW` vs `P_calc` |
| 11 | `P_sensor_flag` | 2 | `derived_power` | `P_deviation_pct` |
| 12 | `is_on` | 2 | `derived_basic` | `Vdot_m3h`, `flowOnThreshold` |
| 13 | `load_class` | 2 | `derived_basic` | `P_th_kW`, `designPower` |
| 14 | `dT_flag` | 2 | `derived_basic` | signed dT, `designDeltaT`, `load_class` |
| 15 | `data_quality` | 2 | `derived_basic` | plausibility bounds on all raw keys |
| 16 | `temp_inversion_flag` | 2 | `derived_basic` | signed dT `< -0.5` while `is_on` |
| 17 | `E_th_delta_kWh` | 2 | `derived_energy` | `P_th_kW` rolling(2), trapezoid |
| 18 | `schedule_violation` | 2 | `derived_schedule` | `Vdot_m3h`, `weeklySchedule` |
| 19 | `dT_collapse_flag` | 2 | `dT_collapse_flag` | `T_flow_C`/`T_return_C` 30 min, `collapseThreshold` |
| 20 | `frozen_sensor_flag` | 2 | `dT_collapse_flag` | `std() == 0` on ≥2 series, 30 min |
| 21 | `flow_spike_flag` | 2 | `flow_spike_flag` | `Vdot_m3h` 5 min, `spikeThreshold` |
| 22 | `cycling_flag` | 2 | `cycling_flag` | `Vdot_m3h` 30 min, `cyclingThreshold` |
| 23 | `cycle_count` | 2 | `cycling_flag` | on/off transitions, 30 min |
| 24 | `power_stability` | 2 | `power_stability` | `std/mean` of `P_th_kW`, 15 min |
| 25 | `power_unstable_flag` | 2 | `power_stability` | `power_stability > stabilityThreshold` |
| 26 | `runtime_pct` | 2 | `runtime_pct` | `Vdot_m3h` 60 min, `flowOnThreshold` |
| 27 | `oscillation_count` | 2 | `oscillation_detection` | `P_th_kW` direction changes, 15 min |
| 28 | `oscillation_flag` | 2 | `oscillation_detection` | `oscillation_count > oscillationThreshold` |
| 29 | `criticalAlarmsCount` | 3 | `em_alarm_handler` node 2 | active CRITICAL alarms |
| 30 | `majorAlarmsCount` | 3 | `em_alarm_handler` node 2 | active MAJOR alarms |
| 31 | `minorAlarmsCount` | 3 | `em_alarm_handler` node 2 | active MINOR alarms |
| 32 | `warningAlarmsCount` | 3 | `em_alarm_handler` node 2 | active WARNING alarms |

Possible on other Measurements but absent on EPI_8_15: `auxT1_C`, `auxT2_C`, `temperature`
(no `_TS*` device assigned), `outsideTemp` / weather context keys.

---

## 7. Dependency graph

```
CHC_S_TemperatureFlow ─┬────────────────────> T_flow_C ──┐
CHC_S_TemperatureReturn┴─(Process Meters)──> T_return_C ─┤
                            └─> CHC_S_TemperatureDiff ──> dT_K
CHC_S_VolumeFlow  ──/1000──────────────────> Vdot_m3h ───┤
CHC_S_Velocity ────────────────────────────> v_ms        │
CHC_S_Power_*  ────────────────────────────> P_th_measured_kW
CHC_M_Energy_* ────────────────────────────> E_th_kWh
CHC_M_Volume   ────────────────────────────> V_m3
                                                         │
        ┌────────────────────────────────────────────────┘
        │
        ├─> derived_power ──> P_th_kW ─┬─> derived_basic       (load_class -> dT_flag)
        │                     │        ├─> derived_energy      (E_th_delta_kWh)
        │                     │        ├─> power_stability     (power_unstable_flag)
        │                     │        └─> oscillation_detection
        │                     └──────────> P_deviation_pct, P_sensor_flag
        │
        ├─> derived_basic ────> is_on, data_quality, temp_inversion_flag
        ├─> derived_schedule ─> schedule_violation
        ├─> runtime_pct ──────> runtime_pct
        ├─> cycling_flag ─────> cycling_flag, cycle_count
        ├─> flow_spike_flag ──> flow_spike_flag
        └─> dT_collapse_flag ─> dT_collapse_flag, frozen_sensor_flag
                                        │
        5 flags ──> measurement.json Create/Clear Alarm (all MINOR)
                                        │
                    em_alarm_handler ──> *AlarmsCount + state attribute
```

`P_th_kW` is the hinge: it is a CF output that four other CFs consume as input. This works because
CF results are re-published as `POST_TELEMETRY_REQUEST` into the rule engine.

---

## 8. Behavioural notes and pitfalls

### 8.1 `P_th_kW` is recomputed, not measured

Its provenance depends on the `calculatePower` attribute:

* `calculatePower = true`  → `ρ·cp·Vdot·dT_eff/3600` (the meter value is only used for the deviation check)
* `calculatePower = false` → verbatim copy of `P_th_measured_kW`

Same key, two different meanings, no marker in the data. Anything reading `P_th_kW` historically
across a `calculatePower` change is comparing apples to oranges.

### 8.2 The oscillation deadband is power-scale dependent

`oscillation_detection` counts a direction change whenever consecutive `P_th_kW` samples differ by
more than **0.1 kW absolute**. At 5 kW that is a 2 % move; at 53 kW it is 0.2 % — i.e. sensor noise.

EPI_8_15 demonstrates this exactly: `power_stability = 0` (std/mean rounds to zero over 15 min — the
plant is genuinely flat) while `oscillation_count = 10 > 8` → `oscillation_flag = true` → the single
active MINOR alarm and `state = minor`.

A relative deadband, e.g. `max(0.1, 0.02 * P_th_kW.mean())`, would remove this class of false
positive. **Not changed** — recorded here as a finding.

### 8.3 The `progress != 'active'` guard leaves gaps

Every CF returns `{}` unless `progress == 'active'`. On EPI_8_15 the raw keys start
**2026-07-23T22:10** but every CF key starts **2026-07-31T07:03** — an 8-day window with raw data and
no derived data at all. (`startTimeMs` is 2026-07-20T11:00Z.)

The fix is reprocessing (`Trigger CF Reprocessing`, `measurement.json` nodes 24/25 via the
`reprocessRequest` telemetry key). The `reprocessing` guard exists so the CFs do not fight the
reprocessing job while it runs.

### 8.4 One-cycle lag and cold start in `derived_basic`

`derived_basic` reads `P_th_kW` as `TS_LATEST`, but `P_th_kW` is written by `derived_power` in
response to the *same* incoming message. Consequences:

* On the very first message of a measurement, `P_th_kW` does not exist yet → `load_class` is absent →
  `dT_flag` is absent too (it requires `load_class`).
* Steady state: `load_class` and `dT_flag` are evaluated against the **previous** sample's power.

At a 1-minute cadence this is harmless; on sparse data it matters.

### 8.5 `dT_K` is unsigned, the flags use a signed dT

`Normalize Data` stores `dT_K = abs(...)`. `derived_basic` and `derived_power` recompute
`T_flow_C - T_return_C` **signed**. So a hydraulically inverted circuit can show a perfectly healthy
`dT_K` on a dashboard while `temp_inversion_flag = true` and `P_th_kW = 0`.

### 8.6 EPI_8_15 has a heating/cooling inconsistency

| Evidence | Says |
|---|---|
| label "Kälteverteilung Ost" | cooling |
| `designFlowTemp = 7`, `designReturnTemp = 13` | cooling (supply colder than return) |
| `installationType = heating` | heating |
| meter: `CHC_S_Power_Heating = 53.3`, `CHC_S_Power_Cooling = 0` | heating |
| measured: `T_flow_C = 12.79 > T_return_C = 9.78` | heating direction |

Power computation is self-consistent (heating branch, `dT_eff > 0`), so `P_th_kW` is fine. But
`dT_flag` and `load_class` are judged against `designDeltaT = 6` / `designPower = 113` taken from a
cooling design profile. Current `dT_flag = ok` sits at `3.01/6 = 0.502`, one hundredth above the
`0.50` "warn" boundary. Worth a decision by whoever commissioned the measurement.

### 8.7 Stale device attribute

`ECO_1C0034000E57435535333920_PF1` carries `measurement = EPI_4_1` while `assignedTo = EPI_8_15`.
`measurement`/`project` are leftovers from the old "Add Device" dialog; the current code path uses
`assignedTo`. Nothing reads `measurement`, so this is cosmetic — but it is misleading when debugging.

### 8.8 `cyclingThreshold` default mismatch

CF argument default `"5"`, in-script fallback `6`. The argument default is what actually applies when
the attribute is unset, so the effective threshold is 5.

---

## 9. Known divergences from the on-disk exports

| Artifact | Status |
|---|---|
| `rule chains/resi_device.json` | **stale** — 29 nodes on disk vs **25 live**. The export still contains `Get Last Meter Telemetry`, `Process Datapoints Multi` and `Switch To Kit`, which no longer exist on the server. |
| `docs/TELEMETRY_PIPELINE.md` §7.1 | **wrong** — claims the Measurement is written multiple times per message. Live has no `Get Measurement Attributes -> Save Timeseries` edge, so the Measurement receives **only** `Normalize Data` output. Confirmed by EPI_8_15 holding zero `CHC_*` keys. |
| `docs/TELEMETRY_PIPELINE.md` §7.3 | **stale** — describes dead branches that only exist in the export. |
| `rule chains/scripts/normalize_data.tbel` | **stale** — 484 lines with the pre-CF derived logic (`is_on`, `load_class`, `P_th_calc`, `MAX_POWER_KW`). The deployed node 23 is the cleaned 3836-character mapping-only version. |
| `analysis/ECO_Data_Catalog.md` §8 | **out of date** — says "12 Raw + 2 Kontext + 17 Calculated Fields = 31 keys". Live is **8 normalized + 20 CF + 4 alarm counts = 32**. |
| `analysis/ECO_Data_Catalog.md` §15 | **wrong** — says the derived telemetry is computed in `Normalize Data`. It moved to Calculated Fields. |
| `analysis/ECO_Data_Catalog.md` §16 | **incomplete** — missing the `derived_energy` CF and the keys `P_th_measured_kW`, `E_th_delta_kWh`, `temp_inversion_flag`, `frozen_sensor_flag`. Also names the power key `P_th_calc_kW`; live writes `P_th_kW`. |

The live VR branch (`Check relation to Measurement` on relation type `VR` → `Switch to Measurement VR
Device`) is still present as nodes but has **no inbound edge**, so it is unreachable. VR devices are
a legacy path and cannot receive telemetry any more.

---

## 10. How to re-derive this map

`scripts/_map-epi815-telemetry.js` (read-only) dumps everything used here — measurement keys with
first/last timestamps, server attributes, all CF definitions with arguments and full expressions,
device raw keys, and the live rule-chain transform scripts:

```bash
node scripts/_map-epi815-telemetry.js /tmp/epi815-map.txt
```

The endpoint that lists the CFs (not obvious from the docs):

```
GET /api/ASSET_PROFILE/{assetProfileId}/calculatedFields?pageSize=200&page=0
GET /api/calculatedField/{calculatedFieldId}
```

Note that `GET /api/ASSET/{measurementId}/calculatedFields` returns **0** — the CFs are attached to
the profile, not to individual measurements.

---

## 11. Worked example — sample at 2026-08-06T09:59

```
device:   CHC_S_TemperatureFlow   = 12.79
          CHC_S_TemperatureReturn =  9.78
          CHC_S_TemperatureDiff   =  3.01        (Process Meters)
          CHC_S_VolumeFlow        = 15220.90722656
          CHC_S_Power_Heating     = 53.3333245
          CHC_M_Energy_Heating    = 20649.24444444
          CHC_M_Volume            = 87506

Normalize Data:
          T_flow_C          = 12.79
          T_return_C        =  9.78
          dT_K              =  3.01
          Vdot_m3h          = 15220.90722656 / 1000  = 15.220907226560001
          v_ms              =  0.82456601
          P_th_measured_kW  = 53.3333245
          E_th_kWh          = 20649.24444444
          V_m3              = 87506

derived_power   (calculatePower=true, fluidType=water, installationType=heating)
          dT_eff  = 12.79 - 9.78                      = 3.01
          P_th_kW = 998 * 4.18 * 15.2209 * 3.01/3600  = 53.09          [stored 53.09]
          P_deviation_pct = (53.3333245-53.09)/53.09*100 = 0.46 -> 0.5  [stored 0.5]
          P_sensor_flag   = |0.5| < 10                = ok

derived_basic   (designPower=113, designDeltaT=6, flowOnThreshold=0.05)
          is_on      = 15.22 > 0.05                   = true
          load_class = 53.09/113*100 = 47.0 %         = mid
          dT_flag    = 3.01/6 = 0.502 >= 0.50         = ok    (0.002 from "warn")
          data_quality = all within bounds            = ok
          temp_inversion_flag = 3.01 < -0.5           = false

derived_energy  dt ~ 60.7 s
          E_th_delta_kWh = 53.2 * 60.7/3600           = 0.8971

rolling CFs
          runtime_pct         = 100
          cycle_count / cycling_flag        = 0 / false
          power_stability / unstable_flag   = 0 / false
          flow_spike_flag                  = false
          dT_collapse_flag / frozen_sensor  = false / false
          oscillation_count / flag          = 10 / true      <- see 8.2

alarms    Oscillation (MINOR) active  ->  minorAlarmsCount = 1, state = minor
```

---

## 12. Reference attribute values on EPI_8_15

Only attributes that feed a formula are listed. All CF thresholds
(`collapseThreshold`, `spikeThreshold`, `cyclingThreshold`, `stabilityThreshold`,
`oscillationThreshold`, `reprocessing`) are **unset** on this measurement and therefore run on the
CF argument defaults.

| Attribute | Value | Used by |
|---|---|---|
| `progress` | `active` | all CFs (guard) |
| `installationType` | `heating` | Normalize Data, `derived_power` |
| `calculatePower` | `true` | `derived_power` |
| `fluidType` | `water` | `derived_power` (cp 4.18 / ρ 998) |
| `designPower` | `113` | `derived_basic` → `load_class` |
| `designDeltaT` | `6` | `derived_basic` → `dT_flag` |
| `flowOnThreshold` | `0.05` | 6 CFs |
| `weeklySchedule` | Mon–Sun 00:00–22:00, `timezoneOffset: 60` | `derived_schedule` |
| `designFlow` | `16.19` | not read by any CF |
| `designFlowTemp` / `designReturnTemp` | `7` / `13` | not read by any CF |
| `systemType` | `other` | not read by any CF |
| `measurementRole` | `subDistribution` | dashboards only |
| `state` | `minor` | written by `em_alarm_handler` |

---

## Appendix A — verbatim Calculated Field sources

Read from the live server on 2026-08-06 via `GET /api/calculatedField/{id}`.
Kept verbatim so future changes can be diffed against this snapshot.

### A.1 `derived_power`

`8d2f1a50-0211-11f1-9979-9f3434877bb4` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `Vdot_m3h` | TS_LATEST | `Vdot_m3h` | - | - | - |
| `T_flow_C` | TS_LATEST | `T_flow_C` | - | - | - |
| `T_return_C` | TS_LATEST | `T_return_C` | - | - | - |
| `calculatePower` | ATTRIBUTE | `calculatePower` | SERVER_SCOPE | `false` | - |
| `fluidType` | ATTRIBUTE | `fluidType` | SERVER_SCOPE | `water` | - |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `P_th_measured_kW` | TS_LATEST | `P_th_measured_kW` | - | - | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |
| `installationType` | ATTRIBUTE | `installationType` | SERVER_SCOPE | `heating` | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

var result = {};

if (calculatePower == true && Vdot_m3h != null && T_flow_C != null && T_return_C != null) {
  var cp = 4.18;
  var rho = 998;
  if (fluidType == "glycol20") { cp = 3.95; rho = 1032; }
  else if (fluidType == "glycol30") { cp = 3.74; rho = 1045; }
  else if (fluidType == "glycol40") { cp = 3.55; rho = 1058; }

  // Effective dT in the operating direction: heating -> VL-RL, cooling -> RL-VL.
  // Wrong direction (dT_eff <= 0) means no thermal transfer -> power = 0.
  var dT_eff = T_flow_C - T_return_C;
  if (installationType == "cooling") { dT_eff = T_return_C - T_flow_C; }

  var P_calc = 0;
  if (dT_eff > 0) { P_calc = rho * cp * Vdot_m3h * dT_eff / 3600.0; }
  result["P_th_kW"] = Math.round(P_calc * 1000.0) / 1000.0;

  if (P_th_measured_kW != null && P_calc > 0.1) {
    var deviation = ((P_th_measured_kW - P_calc) / P_calc) * 100.0;
    result["P_deviation_pct"] = Math.round(deviation * 10.0) / 10.0;
    var absDeviation = deviation;
    if (deviation < 0) { absDeviation = -deviation; }
    if (absDeviation < 10) { result["P_sensor_flag"] = "ok"; }
    else if (absDeviation < 25) { result["P_sensor_flag"] = "warn"; }
    else { result["P_sensor_flag"] = "error"; }
  }
} else if (P_th_measured_kW != null) {
  result["P_th_kW"] = P_th_measured_kW;
}

if (result["P_th_kW"] == null) { return {}; }

return {"ts": ctx.latestTs, "values": result};
```

### A.2 `derived_basic`

`6cac3240-0211-11f1-9b0a-33b9bcf3ddd0` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `designDeltaT` | ATTRIBUTE | `designDeltaT` | SERVER_SCOPE | - | - |
| `designPower` | ATTRIBUTE | `designPower` | SERVER_SCOPE | - | - |
| `flowOnThreshold` | ATTRIBUTE | `flowOnThreshold` | SERVER_SCOPE | `0.05` | - |
| `P_th_kW` | TS_LATEST | `P_th_kW` | - | - | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `T_flow_C` | TS_LATEST | `T_flow_C` | - | - | - |
| `T_return_C` | TS_LATEST | `T_return_C` | - | - | - |
| `Vdot_m3h` | TS_LATEST | `Vdot_m3h` | - | - | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

// Guards
if (Vdot_m3h == null) {
  return {};
}

// Calculate dT from raw sensors
var dT_K = null;
if (T_flow_C != null && T_return_C != null) {
  dT_K = T_flow_C - T_return_C;
}

// Ensure threshold has valid value
var threshold = flowOnThreshold;
if (threshold == null) {
  threshold = 0.1;
}

var result = {};

// --- is_on ---
if (Vdot_m3h > threshold) {
  result["is_on"] = true;
} else {
  result["is_on"] = false;
}

// --- load_class ---
if (P_th_kW != null && designPower != null && designPower > 0) {
  var loadPct = (P_th_kW / designPower) * 100;
  if (loadPct < 30) {
    result["load_class"] = "low";
  } else if (loadPct < 60) {
    result["load_class"] = "mid";
  } else {
    result["load_class"] = "high";
  }
}

// --- dT_flag ---
if (dT_K != null && designDeltaT != null && designDeltaT > 0 && result["load_class"] != null) {
  var dTRatio = dT_K / designDeltaT;
  if (result["load_class"] == "low") {
    if (dTRatio >= 0.3) {
      result["dT_flag"] = "ok";
    } else if (dTRatio >= 0.15) {
      result["dT_flag"] = "warn";
    } else {
      result["dT_flag"] = "severe";
    }
  } else {
    if (dTRatio >= 0.5) {
      result["dT_flag"] = "ok";
    } else if (dTRatio >= 0.3) {
      result["dT_flag"] = "warn";
    } else {
      result["dT_flag"] = "severe";
    }
  }
}

// --- data_quality ---
var isOutlier = false;
if (T_flow_C != null && (T_flow_C < -50 || T_flow_C > 150)) { isOutlier = true; }
if (T_return_C != null && (T_return_C < -50 || T_return_C > 150)) { isOutlier = true; }
if (dT_K != null && (dT_K < -50 || dT_K > 100)) { isOutlier = true; }
if (Vdot_m3h != null && (Vdot_m3h < 0 || Vdot_m3h > 1000)) { isOutlier = true; }
if (P_th_kW != null && (P_th_kW < -10000 || P_th_kW > 10000)) { isOutlier = true; }

if (isOutlier) {
  result["data_quality"] = "error";
} else {
  result["data_quality"] = "ok";
}

// --- temp_inversion_flag ---
if (T_flow_C != null && T_return_C != null) {
  if (result["is_on"] == true) {
    // dT_K < -0.5 means T_return > T_flow by more than 0.5K
    var inverted = (dT_K < -0.5);
    result["temp_inversion_flag"] = inverted;
  } else {
    result["temp_inversion_flag"] = false;
  }
}

return {"ts": ctx.latestTs, "values": result};
```

### A.3 `derived_energy`

`d236add0-080a-11f1-9c7a-33b9bcf3ddd0` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `P_th_kW` | TS_ROLLING | `P_th_kW` | - | - | 300000 ms / 2 |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

var count = P_th_kW.count();
if (count < 2) { return {}; }

// Iterate to get last two values with timestamps
var prevVal = null;
var prevTs = null;
var currVal = null;
var currTs = null;

foreach(v: P_th_kW) {
  prevVal = currVal;
  prevTs = currTs;
  currVal = v.value;
  currTs = v.ts;
}

if (prevVal == null || currVal == null || prevTs == null) { return {}; }

// Time delta in milliseconds
var dt_ms = currTs - prevTs;
if (dt_ms <= 0 || dt_ms > 600000) { return {}; }

// Trapezoidal integration: E = P_avg * dt
var dt_hours = dt_ms / 3600000.0;
var P_avg = (prevVal + currVal) / 2.0;
var E_delta = P_avg * dt_hours;

return {"ts": ctx.latestTs, "values": {"E_th_delta_kWh": Math.round(E_delta * 10000.0) / 10000.0}};
```

### A.4 `derived_schedule`

`aee1f6e0-0211-11f1-9979-9f3434877bb4` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `Vdot_m3h` | TS_LATEST | `Vdot_m3h` | - | - | - |
| `flowOnThreshold` | ATTRIBUTE | `flowOnThreshold` | SERVER_SCOPE | `0.05` | - |
| `weeklySchedule` | ATTRIBUTE | `weeklySchedule` | SERVER_SCOPE | `null` | - |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

// Calculate is_on from raw Vdot_m3h
if (Vdot_m3h == null) { return {}; }

var threshold = flowOnThreshold;
if (threshold == null) { threshold = 0.1; }
var is_on = (Vdot_m3h > threshold);

if (weeklySchedule == null || weeklySchedule == "") { return {}; }

var schedule = isMap(weeklySchedule) ? weeklySchedule : JSON.parse(weeklySchedule);
if (schedule == null) { return {}; }

var tzOffset = 60;
if (schedule["timezoneOffset"] != null) { tzOffset = toInt(schedule["timezoneOffset"]); }

var ts = ctx.latestTs;
var msPerDay = 86400000;

// DST detection
var daysSince1970 = toInt(ts / msPerDay);
var year = 1970;
var days = daysSince1970;
while (days >= 365) {
  var daysInYear = 365;
  if (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)) { daysInYear = 366; }
  if (days >= daysInYear) { days = days - daysInYear; year = year + 1; } else { break; }
}
var daysInMonths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
if (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)) { daysInMonths[1] = 29; }
var month = 0;
while (month < 12 && days >= daysInMonths[month]) { days = days - daysInMonths[month]; month = month + 1; }
month = month + 1;
var dayOfMonth = days + 1;

var isDST = false;
if (month >= 4 && month <= 9) { isDST = true; }
else if (month == 3 && dayOfMonth >= 25) { isDST = true; }
else if (month == 10 && dayOfMonth < 25) { isDST = true; }

var effectiveOffset = tzOffset;
if (isDST) { effectiveOffset = tzOffset + 60; }

var localTs = ts + effectiveOffset * 60000;
var dayIndex = (toInt(localTs / msPerDay) + 4) % 7;
var dayNames = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
var dayName = dayNames[dayIndex];
var msInDay = localTs % msPerDay;
var currentMinutes = toInt(msInDay / 60000);

var isWithinSchedule = false;
var todayValue = schedule[dayName];

if (todayValue != null) {
  var todayStr = "" + todayValue;
  if (todayStr == "true") { isWithinSchedule = true; }
  else if (todayStr != "false") {
    var enabled = todayValue["enabled"];
    if (("" + enabled) == "true") {
      var startStr = todayValue["start"];
      var endStr = todayValue["end"];
      if (startStr != null && endStr != null) {
        var startH = toInt(parseLong(startStr.substring(0, 2)));
        var startM = toInt(parseLong(startStr.substring(3, 5)));
        var startMinutes = startH * 60 + startM;
        var endH = toInt(parseLong(endStr.substring(0, 2)));
        var endM = toInt(parseLong(endStr.substring(3, 5)));
        var endMinutes = endH * 60 + endM;
        if (currentMinutes >= startMinutes && currentMinutes <= endMinutes) { isWithinSchedule = true; }
      } else { isWithinSchedule = true; }
    }
  }
}

var scheduleViolation = false;
if (is_on == true && !isWithinSchedule) { scheduleViolation = true; }

return {"ts": ctx.latestTs, "values": {"schedule_violation": scheduleViolation}};
```

### A.5 `dT_collapse_flag`

`684c01c0-0127-11f1-9979-9f3434877bb4` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `T_flow_C` | TS_ROLLING | `T_flow_C` | - | - | 1800000 ms / 100 |
| `T_return_C` | TS_ROLLING | `T_return_C` | - | - | 1800000 ms / 100 |
| `collapseThreshold` | ATTRIBUTE | `collapseThreshold` | SERVER_SCOPE | `0.5` | - |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |
| `Vdot_m3h` | TS_ROLLING | `Vdot_m3h` | - | - | 1800000 ms / 100 |
| `flowOnThreshold` | ATTRIBUTE | `flowOnThreshold` | SERVER_SCOPE | `0.05` | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

var result = {};

// ---- Frozen Sensor Detection (30min rolling window) ----
// Need at least 2 sensor columns with enough data
var hasFlow = (T_flow_C.count() >= 6);
var hasReturn = (T_return_C.count() >= 6);
var hasVdot = (Vdot_m3h.count() >= 6);

var sensorCount = 0;
if (hasFlow) { sensorCount = sensorCount + 1; }
if (hasReturn) { sensorCount = sensorCount + 1; }
if (hasVdot) { sensorCount = sensorCount + 1; }

if (sensorCount >= 2) {
  // Check if system is running
  var flowThreshold = flowOnThreshold;
  if (flowThreshold == null) { flowThreshold = 0.05; }
  var lastFlow = Vdot_m3h.last();

  if (lastFlow != null && lastFlow > flowThreshold) {
    // AND logic: ALL available sensors must be frozen simultaneously
    var allFrozen = true;
    if (hasFlow) {
      var stdFlow = T_flow_C.std();
      if (stdFlow == null || stdFlow > 0) { allFrozen = false; }
    }
    if (hasReturn) {
      var stdReturn = T_return_C.std();
      if (stdReturn == null || stdReturn > 0) { allFrozen = false; }
    }
    if (hasVdot) {
      var stdVdot = Vdot_m3h.std();
      if (stdVdot == null || stdVdot > 0) { allFrozen = false; }
    }
    result["frozen_sensor_flag"] = allFrozen;
  } else {
    result["frozen_sensor_flag"] = false;
  }
}

// ---- dT Collapse Detection ----
var countFlow = T_flow_C.count();
var countReturn = T_return_C.count();

if (countFlow >= 3 && countReturn >= 3) {
  var currentDT = T_flow_C.last() - T_return_C.last();
  var avgDT = T_flow_C.mean() - T_return_C.mean();

  if (avgDT != 0) {
    var threshold = collapseThreshold;
    if (threshold == null) { threshold = 0.5; }
    var collapsed = false;
    if (currentDT < avgDT * threshold) { collapsed = true; }
    result["dT_collapse_flag"] = collapsed;
  }
}

if (result["dT_collapse_flag"] == null && result["frozen_sensor_flag"] == null) { return {}; }

return {"ts": ctx.latestTs, "values": result};
```

### A.6 `flow_spike_flag`

`685884e0-0127-11f1-9979-9f3434877bb4` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `Vdot_m3h` | TS_ROLLING | `Vdot_m3h` | - | - | 300000 ms / 50 |
| `spikeThreshold` | ATTRIBUTE | `spikeThreshold` | SERVER_SCOPE | `2.0` | - |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

var currentFlow = Vdot_m3h.last();
var avgFlow = Vdot_m3h.mean();
var countFlow = Vdot_m3h.count();
if (countFlow < 3 || avgFlow == 0) { return {}; }

var threshold = spikeThreshold;
if (threshold == null) { threshold = 2.0; }

var spiked = false;
if (currentFlow > avgFlow * threshold) { spiked = true; }

return {"ts": ctx.latestTs, "values": {"flow_spike_flag": spiked}};
```

### A.7 `cycling_flag`

`aedba340-012a-11f1-9979-9f3434877bb4` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `Vdot_m3h` | TS_ROLLING | `Vdot_m3h` | - | - | 1800000 ms / 200 |
| `flowOnThreshold` | ATTRIBUTE | `flowOnThreshold` | SERVER_SCOPE | `0.05` | - |
| `cyclingThreshold` | ATTRIBUTE | `cyclingThreshold` | SERVER_SCOPE | `5` | - |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

var countAll = Vdot_m3h.count();
if (countAll < 3) { return {}; }

var flowThreshold = flowOnThreshold;
if (flowThreshold == null) { flowThreshold = 0.1; }

var threshold = cyclingThreshold;
if (threshold == null) { threshold = 6; }

var transitions = 0;
var prevIsOn = null;
foreach(v: Vdot_m3h) {
  var isOn = (v.value > flowThreshold);
  if (prevIsOn != null && prevIsOn != isOn) {
    transitions = transitions + 1;
  }
  prevIsOn = isOn;
}

var isCycling = false;
if (transitions > threshold) { isCycling = true; }

return {"ts": ctx.latestTs, "values": {"cycling_flag": isCycling, "cycle_count": transitions}};
```

### A.8 `power_stability`

`a065a960-0129-11f1-9979-9f3434877bb4` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `P_th_kW` | TS_ROLLING | `P_th_kW` | - | - | 900000 ms / 50 |
| `Vdot_m3h` | TS_ROLLING | `Vdot_m3h` | - | - | 900000 ms / 50 |
| `flowOnThreshold` | ATTRIBUTE | `flowOnThreshold` | SERVER_SCOPE | `0.05` | - |
| `stabilityThreshold` | ATTRIBUTE | `stabilityThreshold` | SERVER_SCOPE | `0.5` | - |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

var avgPower = P_th_kW.mean();
var stdPower = P_th_kW.std();
var countPower = P_th_kW.count();
if (countPower < 5) { return {}; }
if (avgPower < 1.0) { return {}; }

var flowThreshold = flowOnThreshold;
if (flowThreshold == null) { flowThreshold = 0.1; }

var onCount = 0;
foreach(v: Vdot_m3h) {
  if (v.value > flowThreshold) { onCount = onCount + 1; }
}
var runtimePct = (onCount / Vdot_m3h.count()) * 100;
if (runtimePct < 80) { return {}; }

var threshold = stabilityThreshold;
if (threshold == null) { threshold = 0.5; }

var stability = stdPower / avgPower;
var isUnstable = false;
if (stability > threshold) { isUnstable = true; }

return {"ts": ctx.latestTs, "values": {"power_stability": Math.round(stability * 1000) / 1000, "power_unstable_flag": isUnstable}};
```

### A.9 `runtime_pct`

`a06e8300-0129-11f1-9979-9f3434877bb4` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `Vdot_m3h` | TS_ROLLING | `Vdot_m3h` | - | - | 3600000 ms / 200 |
| `flowOnThreshold` | ATTRIBUTE | `flowOnThreshold` | SERVER_SCOPE | `0.05` | - |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

var countAll = Vdot_m3h.count();
if (countAll < 2) { return {}; }

var flowThreshold = flowOnThreshold;
if (flowThreshold == null) { flowThreshold = 0.1; }

var onCount = 0;
foreach(v: Vdot_m3h) {
  if (v.value > flowThreshold) { onCount = onCount + 1; }
}

var runtimePct = (onCount / countAll) * 100;
return {"ts": ctx.latestTs, "values": {"runtime_pct": Math.round(runtimePct * 10) / 10}};
```

### A.10 `oscillation_detection`

`30eb6890-0133-11f1-9979-9f3434877bb4` — type `SCRIPT`, output `TIME_SERIES`

| Argument | Type | Key | Scope | Default | Window / Limit |
|---|---|---|---|---|---|
| `P_th_kW` | TS_ROLLING | `P_th_kW` | - | - | 900000 ms / 60 |
| `Vdot_m3h` | TS_ROLLING | `Vdot_m3h` | - | - | 900000 ms / 60 |
| `flowOnThreshold` | ATTRIBUTE | `flowOnThreshold` | SERVER_SCOPE | `0.05` | - |
| `oscillationThreshold` | ATTRIBUTE | `oscillationThreshold` | SERVER_SCOPE | `8` | - |
| `reprocessing` | ATTRIBUTE | `reprocessing` | SERVER_SCOPE | `false` | - |
| `progress` | ATTRIBUTE | `progress` | SERVER_SCOPE | `active` | - |

```javascript
// Guard: Skip during reprocessing or for finished measurements
if (reprocessing == true) { return {}; }
if (progress != 'active') { return {}; }

var countPower = P_th_kW.count();
if (countPower < 10) { return {}; }

var flowThreshold = flowOnThreshold;
if (flowThreshold == null) { flowThreshold = 0.1; }

var onCount = 0;
foreach(v: Vdot_m3h) {
  if (v.value > flowThreshold) { onCount = onCount + 1; }
}
var runtimePct = (onCount / Vdot_m3h.count()) * 100;
if (runtimePct < 80) { return {}; }

var avgPower = P_th_kW.mean();
if (avgPower < 1.0) { return {}; }

var threshold = oscillationThreshold;
if (threshold == null) { threshold = 8; }

var directionChanges = 0;
var prevValue = null;
var prevDirection = null;
foreach(v: P_th_kW) {
  if (prevValue != null) {
    var diff = v.value - prevValue;
    var currentDirection = 0;
    if (diff > 0.1) { currentDirection = 1; }
    else if (diff < -0.1) { currentDirection = -1; }
    if (prevDirection != null && currentDirection != 0 && prevDirection != currentDirection) {
      directionChanges = directionChanges + 1;
    }
    if (currentDirection != 0) { prevDirection = currentDirection; }
  }
  prevValue = v.value;
}

var oscillationFlag = false;
if (directionChanges > threshold) { oscillationFlag = true; }

return {"ts": ctx.latestTs, "values": {"oscillation_count": directionChanges, "oscillation_flag": oscillationFlag}};
```
