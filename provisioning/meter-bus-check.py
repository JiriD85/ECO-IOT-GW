#!/usr/bin/env python3
"""
meter-bus-check.py  --  one-shot health check of the C4 external RS485 meter bus

Everything the RESI-C4 reads for telemetry lives on ONE serial bus (MODBUSEXT =
/dev/ttyACM2 @ 9600 8N1), addressed by Modbus unit id -- firmware-verified from
MB.HandlePFLOW / MB.Handle2RTDSensors:

  unit  88  P-Flow PF1   FC03 (holding)  meter register map (see device-maps.js)
  unit  80  P-Flow PF2   FC03 (holding)
  unit  81  P-Flow PF3   FC03 (holding)
  unit  82  P-Flow PF4   FC03 (holding)
  unit 255  AIOX TS1/TS2 FC04 (input)    reg0=TS1 degC/10, reg1=TS2 degC/10

This script probes each expected unit and prints a PASS/FAIL table with a sanity
value, so one command tells you the whole bus state. Use --scan to also sweep a
range of unit ids (useful when a meter's address is unknown after a power cycle).

Usage (Pi venv with pymodbus, e.g. ~/scanvenv):
    ~/scanvenv/bin/python meter-bus-check.py                     # check expected units
    ~/scanvenv/bin/python meter-bus-check.py --port /dev/ttyACM0 # if enumeration differs
    ~/scanvenv/bin/python meter-bus-check.py --scan 1-100        # sweep unit ids 1..100
    ~/scanvenv/bin/python meter-bus-check.py --scan 70-90,255    # sweep a custom set
"""
import argparse
import struct
import sys

try:
    from pymodbus.client import ModbusSerialClient
except ImportError:
    sys.exit("pymodbus not installed. Try: ~/scanvenv/bin/pip install pymodbus")

# (unit, label, function_code, address, count) for the sanity read of each device.
# P-Flow: Vdot at holding reg 5 (32float, BIG/BIG). AIOX: input regs 0..7.
EXPECTED = [
    (88, "PF1 (P-Flow)", 3, 5, 2),
    (80, "PF2 (P-Flow)", 3, 5, 2),
    (81, "PF3 (P-Flow)", 3, 5, 2),
    (82, "PF4 (P-Flow)", 3, 5, 2),
    (255, "TS1/TS2 (AIOX)", 4, 0, 8),
]


def signed16(v):
    return v - 65536 if v > 32767 else v


def f32_big(regs):
    """Decode two 16-bit regs as a big-endian float (high word first, BIG/BIG)."""
    raw = struct.pack(">HH", regs[0], regs[1])
    return struct.unpack(">f", raw)[0]


def read(cli, fc, addr, count, unit):
    fn = cli.read_input_registers if fc == 4 else cli.read_holding_registers
    for kw in ("device_id", "slave", "unit"):
        try:
            rr = fn(addr, count=count, **{kw: unit})
        except TypeError:
            continue
        except Exception as e:
            return None, f"exc: {e}"
        if rr is None:
            return None, "no response"
        if rr.isError():
            return None, "no response / error"
        return rr.registers, None
    return None, "kwarg mismatch"


def sanity(unit, fc, regs):
    if unit == 255:  # AIOX
        ts1 = signed16(regs[0]) / 10.0
        ts2 = signed16(regs[1]) / 10.0
        err1, err2 = regs[6], regs[7]
        return f"TS1={ts1:.1f}C TS2={ts2:.1f}C  err=({err1},{err2})"
    # P-Flow Vdot (m3/h) = float/1000 per our map
    try:
        return f"Vdot~={f32_big(regs) / 1000.0:.4f} m3/h (raw f32={f32_big(regs):.3f})"
    except Exception:
        return f"regs={regs}"


def parse_scan(spec):
    units = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            units.update(range(int(a), int(b) + 1))
        elif part:
            units.add(int(part))
    return sorted(u for u in units if 0 <= u <= 255)


# Common P-Flow / Modbus RTU line settings to try when a meter can't be found at 9600 8N1.
HUNT_BAUDS = [9600, 19200, 38400, 4800, 57600, 115200]
HUNT_PARITIES = [("N", 1), ("E", 1), ("O", 1)]


def hunt(port, unit_spec):
    """Find a 'lost' meter: sweep baud x parity x unit id looking for a P-Flow (FC03).

    Use when a meter is set up but silent at the expected 9600/8N1/address -- a baud or
    parity mismatch makes it invisible to the normal check. If nothing answers at ANY
    combination, the problem is physical (A/B polarity, wiring terminals, power, termination),
    not a line-setting mismatch.
    """
    units = parse_scan(unit_spec)
    print(f"== HUNT on {port}: bauds {HUNT_BAUDS} x parity N/E/O x units {units} ==")
    print("   (looking for a P-Flow via FC03 read at holding reg 5)")
    found = []
    for baud in HUNT_BAUDS:
        for par, stop in HUNT_PARITIES:
            cli = ModbusSerialClient(port=port, baudrate=baud, bytesize=8,
                                     parity=par, stopbits=stop, timeout=0.3)
            if not cli.connect():
                continue
            for u in units:
                regs, _ = read(cli, 3, 5, 2, u)
                if regs is not None:
                    print(f"  HIT  baud={baud} 8{par}{stop}  unit={u}  FC03 reg5={regs}")
                    found.append((baud, par, u))
            cli.close()
    if not found:
        print("\n  NOTHING answered at any baud/parity/unit.")
        print("  -> Not a line-setting issue. Check the PHYSICAL link:")
        print("     - A/B (D+/D-) polarity: swap the two RS485 data wires and retry.")
        print("     - Wiring terminals: base RS485 out -> extension IN (not OUT); A->A, B->B, GND->GND.")
        print("     - Meter power: is the extension meter's own display/LED on?")
        print("     - Termination: 120R at the two physical ends only; remove extras.")
        print("     - Does connecting the extension also kill PF1 (unit 88)? If so the ext")
        print("       wiring is faulting the whole bus (short/polarity/termination).")
    else:
        print(f"\n  Found {len(found)} responder(s). If PF2 is at a non-9600/8N1 setting,")
        print("  either reconfigure the meter to 9600 8N1 or match the connector to it.")
    return found


def main():
    ap = argparse.ArgumentParser(description="C4 meter-bus health check")
    ap.add_argument("--port", default="/dev/ttyACM2")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--scan", help="also sweep unit ids, e.g. '1-100' or '70-90,255'")
    ap.add_argument("--hunt", nargs="?", const="1,80,81,82,88,247",
                    help="find a lost meter: sweep baud x parity x unit for a P-Flow. "
                         "Optional unit spec (default common addresses 1,80,81,82,88,247).")
    args = ap.parse_args()

    if args.hunt is not None:
        hunt(args.port, args.hunt)
        return

    cli = ModbusSerialClient(port=args.port, baudrate=args.baud, bytesize=8,
                             parity="N", stopbits=1, timeout=0.7)
    if not cli.connect():
        sys.exit(f"could not open {args.port}")

    print(f"== bus {args.port} @ {args.baud} 8N1 ==\n")
    print(f"{'unit':>4}  {'device':<16} {'result':<8} detail")
    print("-" * 72)
    for unit, label, fc, addr, count in EXPECTED:
        regs, err = read(cli, fc, addr, count, unit)
        if regs is not None:
            print(f"{unit:>4}  {label:<16} {'PASS':<8} FC{fc:02d} addr{addr}: {sanity(unit, fc, regs)}")
        else:
            print(f"{unit:>4}  {label:<16} {'FAIL':<8} FC{fc:02d} addr{addr}: {err}")

    if args.scan:
        print(f"\n== scan {args.scan} (FC03 addr 0 + FC04 addr 0, count 2) ==")
        for unit in parse_scan(args.scan):
            hits = []
            for fc in (3, 4):
                regs, _ = read(cli, fc, 0, 2, unit)
                if regs is not None:
                    hits.append(f"FC{fc:02d}={regs}")
            if hits:
                print(f"  unit {unit:>3}: {' | '.join(hits)}")
        print("  (units not listed did not answer)")

    cli.close()


if __name__ == "__main__":
    main()
