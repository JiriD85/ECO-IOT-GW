# eco-gw-001 hardware bring-up runbook

Everything to do the next time you can physically connect to the C4 (eco-gw-001).
Covers the two open items — **PF2/PF3/PF4 meters** and **TS1/TS2 temperatures** — with
exact commands, expected results, and what to do at each fork. Self-contained: read this,
don't re-derive.

> Written 2026-08 after fully reverse-engineering the RESI stack from the SD card
> (source tree + SI-BASIC firmware disassembly). The facts below are firmware-verified,
> not guessed. See the memory note `eco-gw-001-deployment` and `docs/RESI_MIGRATION.md`.

---

## 0. The one thing that probably fixes PF2 (do this first)

**Power-cycle both P-Flow meters after they are finally wired and addressed.**

The GENTOS/P-Flow D116 latches its Modbus slave address and re-scans the RS485 line
**at power-on**. If PF2 was set to address 80 and chained into the bus *while powered*, it
keeps its old state and stays silent — exactly the symptom we saw. This is very likely the
whole PF2 problem; the address (80) is firmware-confirmed correct, so it is not an
addressing mistake.

Procedure:
1. Confirm final wiring (see §2) and that each meter's address is set (PF1=88, PF2=80,
   PF3=81, PF4=82) on the meter's own display/config.
2. **Remove power from all P-Flow meters, wait ~10 s, re-apply power to all of them.**
3. Give them ~5 s to boot, then run the bus check (§3).

---

## 1. Bus topology (firmware-verified)

Everything telemetry-related is on **one** RS485 bus, addressed by Modbus unit id:

| unit | device | Modbus | registers | notes |
|-----:|--------|--------|-----------|-------|
| 88 | P-Flow **PF1** | FC03 holding | D116 map (see `device-maps.js`) | confirmed live |
| 80 | P-Flow **PF2** | FC03 holding | D116 map | under test — power-cycle! |
| 81 | P-Flow **PF3** | FC03 holding | D116 map | only when wired |
| 82 | P-Flow **PF4** | FC03 holding | D116 map | only when wired |
| 255 | **AIOX** (TS1/TS2) | FC04 **input** | reg0=TS1, reg1=TS2 (°C = int16/10) | onboard C4 analog module |

- **Meter bus = `MODBUSEXT` = `/dev/ttyACM2` @ 9600 8N1.** The P-Flows *and* the AIOX temps
  all live here. There is **no** second internal Modbus bus in use (the old "unit 1 on
  ttyACM1" idea was wrong — see §7).
- `INTERN` = `/dev/ttyACM0` @ **230400** 8N1 is the STM32 mainboard **ASCII console** (Cx
  protocol). Only needed if the AIOX channels have lost their RTD typing (§5, branch B).
- **`ttyACMx` numbering is not stable** across reboots/rebuilds (the Cinterion LTE modem also
  enumerates as ttyACM*). Always confirm which node is the meter bus (§3). Pin it later with a
  udev-by-USB-path rule.

### RS485 chaining (extension kits)
Up to 4 kits chain in series via the RS485 **IN**/**OUT** pair. Base kit's RS485 → extension
kit **IN**; the extension's **OUT** goes to the next kit's IN. Terminate the **two physical
ends** of the run (base kit + last extension) if the run is long/noisy. (You had PF2 on the
extension's IN, which is correct.)

### Bring-up ORDER (base vs extensions)
**Electrically, order does not matter.** RS485 is a shared multi-drop bus, not a positional
daisy-chain — each meter just answers its own Modbus address (88/80/81/82) whenever powered.
The only real rules:
1. **Unique address before sharing the bus.** If two meters sit at the same address (e.g. a
   factory default), they collide when both powered on the bus → address them **one at a time
   in isolation** first, then chain. Once each is unique, order is irrelevant.
2. **Power-cycle all meters after the chain is fully wired** (§0 — the D116 latches its address
   at power-on).
3. Terminate the two ends (above).

**Recommended (diagnostic, not electrical):** bring up **base PF1 (unit 88) first** as the
known-good anchor, verify it answers, then add **one extension meter at a time** (wire it,
power-cycle all, re-run `meter-bus-check.py`). If the bus dies the moment a specific kit is
added, that kit is the culprit (wiring/polarity/duplicate address) — you've isolated it instead
of debugging all four at once.

---

## 2. The scripts (all in `provisioning/`, run on the Pi)

They talk to `/dev/ttyACM*` on the Pi, so they must run **on the Pi**, in the venv that has
`pymodbus`/`pyserial` (`~/scanvenv`). Copy them over first (§3, step 1).

| script | purpose |
|--------|---------|
| `meter-bus-check.py` | **Start here.** One-shot PASS/FAIL of the whole bus (all P-Flows + AIOX) with a sanity value. `--scan 1-100` sweeps unit ids when an address is unknown. |
| `aiox-modbus-probe.py` | Focused AIOX read: unit 255, FC04, all 8 input regs, shown raw / signed / ÷10 / ÷100. Confirms TS1/TS2 and the scaling. |
| `aiox-console-probe.py` | Fallback only: opens the STM32 console (ttyACM0 @230400), sends safe GET commands incl. `GIOTYPS` (current channel types) and `GRTDISPT1000C` (temps). Use if TS reads are zero and channels need re-typing. |
| `generate-connector.js` | Regenerates the tb-gateway Modbus connector JSON from `sites/eco-gw-001.json` (run on the laptop). |
| `scan-modbus.py` | Generic open-ended scanner (already on the Pi), if you need more than `meter-bus-check.py --scan`. |

---

## 3. Test sequence

### Step 1 — get the scripts onto the Pi and confirm the port
```bash
# from the laptop (adjust host/user to whatever is live: eco@192.168.137.2 over the
# direct cable, or pi@192.168.1.69 over the LAN)
scp provisioning/meter-bus-check.py provisioning/aiox-modbus-probe.py \
    provisioning/aiox-console-probe.py <user>@<host>:/tmp/

# on the Pi: which ttyACM nodes exist?
ls -l /dev/ttyACM*
```
If unsure which node is the meter bus, the fastest tell is that PF1 (unit 88) answers there
(Step 2). The console is the one that answers the Cx handshake at 230400 (Step 5).

### Step 2 — bus health (do this after the power cycle in §0)
```bash
~/scanvenv/bin/python /tmp/meter-bus-check.py
# if ttyACM2 is not the bus, try: --port /dev/ttyACM0  (etc.)
```
Expected after a good power cycle:
```
  88  PF1 (P-Flow)     PASS   FC03 addr5: Vdot~=... m3/h
  80  PF2 (P-Flow)     PASS   FC03 addr5: Vdot~=... m3/h
  81  PF3 (P-Flow)     FAIL   ...        (only if PF3 not wired — expected)
  82  PF4 (P-Flow)     FAIL   ...        (only if PF4 not wired — expected)
 255  TS1/TS2 (AIOX)   PASS   FC04 addr0: TS1=..C TS2=..C  err=(..)
```

**Decision fork on PF2:**
- **PF2 PASS** → good, proceed.
- **PF2 FAIL** → work the tree below. (Note: as of last attempt the extension was power-cycled
  several times at address 80 and stayed silent, so a missing power-cycle is NOT the whole story
  — treat baud/parity/polarity as the prime suspects.)

  **First, isolate: is PF1 (unit 88) still PASSing with the extension connected?**
  - **PF1 also FAILs when the extension is attached** → the extension wiring is faulting the
    whole bus (A/B polarity swap, a short, or bad/missing termination). Fix the physical link;
    disconnect the extension to confirm PF1 comes back.
  - **PF1 still PASSes, only PF2 silent** → PF2-specific. Hunt for it across line settings:
    ```bash
    ~/scanvenv/bin/python /tmp/meter-bus-check.py --hunt
    # or widen the address set: --hunt 1-100,247
    ```
    This sweeps baud (9600/19200/38400/4800/57600/115200) × parity (N/E/O) × unit id.
    - **A HIT at some baud/parity/unit** → PF2 is alive but mis-set. Either reconfigure the
      meter to **9600 8N1 addr 80**, or (temporary) match the connector to what it answers at.
    - **No hit anywhere** → not a line-setting issue. Physical: swap **A/B (D+/D-) polarity**
      (the #1 cause), verify base RS485 → extension **IN** (not OUT) with A→A/B→B/GND→GND,
      confirm the meter's own display/LED is powered, and check termination (120 Ω at the two
      ends only).

### Step 3 — temperatures (TS1/TS2)
```bash
~/scanvenv/bin/python /tmp/aiox-modbus-probe.py
```
This reads unit 255, FC04, 8 input registers. `reg[0]÷10 = TS1`, `reg[1]÷10 = TS2`.

**Decision fork on TS:**
- **Plausible temperatures at reg[0]/reg[1] (÷10 column)** → done. No console/bring-up needed.
  The AIOX channels are typed as RTD in the mainboard and answer over Modbus. Go to §4.
- **All zeros / no response** → the AIOX channels have lost their RTD typing (or the mainboard
  isn't answering at 255). Go to §5.

---

## 4. Deploy (once PF2 and/or TS pass)

Only add devices to the deployed connector that **actually answered** — an unreachable slave
times out every poll cycle and stalls the whole bus. `sites/eco-gw-001.json` currently defines
PF1, PF2, TS1, TS2. Add PF3/PF4 only after they pass §2.

1. Regenerate the connector JSON (laptop):
   ```bash
   cd provisioning
   node -e "const {buildModbusConnector}=require('./generate-connector'); \
     console.log(JSON.stringify(buildModbusConnector(require('./sites/eco-gw-001.json')).connector.configurationJson,null,2))"
   ```
   Expect 6 slaves: PF1×2 (endianness groups) unit 88, PF2×2 unit 80, TS1 unit 255 (auxT1_C),
   TS2 unit 255 (auxT2_C).
2. Push it as the connector's **shared attribute** in ThingsBoard (keyed by the connector's
   name — check the Gateway UI for the live name; historically `3RS485_PF`). Writing the attr
   only **stages** it (UI shows *OUT OF SYNC*).
3. **Apply it:** in the TB Gateway UI, **disable then re-enable the connector**. The gateway
   re-reads the stored config and restarts the connector (status → *SYNC*). This is fully
   remote — no bench needed.
4. Verify latest telemetry on the scratch devices `eco-gw-001-ts1` / `eco-gw-001-ts2` (keys
   `auxT1_C` / `auxT2_C`) and `eco-gw-001-pf2`.

> The scratch `deviceName` overrides in the site file keep this off the real fleet entities.
> Only point the connector at `ECO_<HWID>_TS1/TS2/PF2...` once validated (that's the real
> cutover, done separately).

---

## 5. TS branch B — re-typing the AIOX channels (only if §3 read zero)

The firmware only *reads* the AIOX; it never sets channel type — so the RTD typing normally
persists in the mainboard. If it was lost, set it once via the console:

```bash
~/scanvenv/bin/python /tmp/aiox-console-probe.py            # auto-finds console @230400
```
1. Confirm the mainboard answers: the probe prints a reply to `#255,VERSION/`.
2. Read current channel types: the probe dumps `#255,GIOTYPS/`. **Record the exact token
   strings** — the RTD token is a mnemonic string (e.g. in the `PT1000`/`OHM`/`VO[0-10V]`
   family), not the integer 13 (13 is only the Modbus-mirror encoding). We could not recover
   the exact RTD mnemonic from the card, so this live read is how we learn it.
3. Once the RTD mnemonic is known, set the temperature channels:
   `#255,SIOTYPS:<tok1>,<tok2>,...,<tokN>/` (one comma-separated token per channel; reply
   `#255,OK`). The probe has a guarded path for this; **do the read (step 2) first** and
   confirm the token before writing.
4. Re-run `aiox-modbus-probe.py` (§3). Temps should now read.

Watchdog note: the firmware only ever sent `#255,WD:0` (once, at setup — not a high-rate
kick). Don't expect to need a periodic watchdog for reads.

If the console path is needed regularly, the clean long-term fix is a tiny Python sidecar that
types the channels once at boot; but the expectation is the typing persists and this branch is
a one-time repair.

---

## 6. Safety / rollback

- All probe scripts are **read-only** except the guarded `SIOTYPS` write in §5 (which you
  trigger explicitly). GET commands and Modbus reads cannot harm the meters.
- Adding a bad/unreachable slave to the connector degrades polling (timeouts) but is reversible:
  remove it from the site file, regenerate, re-sync (§4).
- Do **not** delete or repoint the real fleet `ECO_<HWID>_*` entities during validation — the
  site file uses scratch `deviceName`s on purpose.
- The RESI SD card is read-only reference; nothing here writes to it.

---

## 7. Reference — corrected facts (what changed and why)

Earlier notes/docs said temps were *"PT1000 on the onboard AIOX at unit 1, over a second
internal serial port, holding registers 41064–41079, ÷100."* **All of that was wrong** — it
came from a generic Node-RED demo on the card, not the field firmware. The production program
(`MB.Handle2RTDSensors`, disassembled) reads:

- **unit 255**, **`/dev/ttyACM2`** meter bus (same as P-Flows), **FC04 input registers**,
  addr 0, count 8, signed-16, **÷10**.
- `reg[0]/reg[1]` = TS1/TS2 instantaneous °C; `reg[2]/[3]`=T_REAL, `reg[4]/[5]`=T_AVG (÷10);
  `reg[6]/[7]`=error counters (raw int, non-zero = fault). No sentinel for a missing sensor.

P-Flow addresses were also confirmed from firmware (`MB.HandlePFLOW`): PF1=88, PF2=80, PF3=81,
PF4=82, FC03 holding registers.

Reverse-engineering artifacts (RESI SD card, read-only): full C++ source tree under
`sdcard/extracted/.../linuxvm/vmachine/`; SI-BASIC programs
`sdcard/extracted/rootfs/home/resivm/storage/MCS.*.instance`; bytecode disassembler left in the
session scratchpad (`disasm.ps1`). The `RESIvmachine_*.exe` is an aarch64 Linux binary (not
.NET), built from that source.

---

## 8. Session checklist

- [ ] Wire PF2 (and PF3/PF4 if adding) into the RS485 chain (base → ext IN → next IN…).
- [ ] Set/verify meter addresses: PF1=88, PF2=80, PF3=81, PF4=82.
- [ ] **Power-cycle all P-Flow meters** (§0).
- [ ] Copy scripts to Pi; confirm meter-bus node (§3.1).
- [ ] `meter-bus-check.py` → PF1/PF2 PASS (§3.2). Scan if PF2 fails.
- [ ] `aiox-modbus-probe.py` → TS1/TS2 plausible (§3.3). Console re-type if zero (§5).
- [ ] Record: which ttyACM was the bus; any address surprises; the RTD mnemonic from GIOTYPS.
- [ ] Regenerate connector, push shared attr, disable/re-enable to sync (§4).
- [ ] Verify `auxT1_C`/`auxT2_C` and PF2 telemetry on the scratch devices.
- [ ] (Later, separate) cut over to real `ECO_<HWID>_*` entities; add udev port pin.
