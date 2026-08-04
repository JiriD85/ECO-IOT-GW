#!/usr/bin/env python3
"""Scan an RS485 bus for Modbus RTU devices and decode the P-Flow D116 registers.

Run this ON the gateway, with the real meters connected. It answers the three things
that could not be recovered from ThingsBoard or the SD card:

  1. which unit IDs are actually present (needed for sites/<site>.json)
  2. whether the mixed byte/word order in device-maps.js is right for these meters
  3. whether the energy registers really need the /3600 kJ->kWh divider

    sudo python3 scan-modbus.py --port /dev/ttyAMA1
    sudo python3 scan-modbus.py --port /dev/ttyAMA1 --units 88 --verbose

Read-only: it issues nothing but function-code 3 reads.

Needs pymodbus 3.x  (pip install 'pymodbus>=3.0,<4')
"""

import argparse
import struct
import sys
import time

def _load_client_class():
    """Imported lazily so --help still works on a machine without pymodbus."""
    try:
        from pymodbus.client import ModbusSerialClient
    except ImportError:
        sys.exit("pymodbus 3.x not found. Install with: pip install 'pymodbus>=3.0,<4'")
    return ModbusSerialClient

# From device-maps.js. (tag, address, kind) -- kind picks the decoder.
FLOAT_REGS = [
    ("CHC_S_VolumeFlow", 5),
    ("CHC_S_Velocity", 7),
    ("CHC_S_TemperatureFlow", 74),
    ("CHC_S_TemperatureReturn", 76),
]
INT_REGS = [
    ("CHC_M_Volume", 8, 1),
    ("CHC_M_Volume_Neg", 11, 1),
    ("CHC_M_Volume_Net", 14, 1),
    ("CHC_M_Energy_Heating", 77, 3600),
    ("CHC_M_Energy_Cooling", 80, 3600),
]

# A register we expect every live D116 to answer, used as the probe during scanning.
PROBE_ADDRESS = 74
PROBE_COUNT = 2


def decode32(regs, byte_order, word_order, as_float):
    """Decode two 16-bit registers into a 32-bit value under a given endianness."""
    hi, lo = (regs[0], regs[1]) if word_order == "BIG" else (regs[1], regs[0])
    endian = ">" if byte_order == "BIG" else "<"
    raw = struct.pack(f"{endian}HH", hi, lo)
    fmt = f"{endian}f" if as_float else f"{endian}i"
    return struct.unpack(fmt, raw)[0]


def read_regs(client, unit, address, count):
    try:
        rr = client.read_holding_registers(address=address, count=count, slave=unit)
    except Exception as exc:                      # transport-level failure
        return None, str(exc)
    if rr is None or rr.isError():
        return None, str(rr)
    return rr.registers, None


def scan(client, units, verbose):
    found = []
    for unit in units:
        regs, err = read_regs(client, unit, PROBE_ADDRESS, PROBE_COUNT)
        if regs is not None:
            print(f"  unit {unit:3d}: RESPONDS  raw={regs}")
            found.append(unit)
        elif verbose:
            print(f"  unit {unit:3d}: -         ({err})")
        time.sleep(0.05)
    return found


def dump(client, unit):
    print(f"\n{'=' * 72}\nunit {unit}\n{'=' * 72}")

    print("\n-- 32-bit floats (device-maps.js expects byteOrder BIG / wordOrder BIG)")
    print(f"{'tag':<26}{'BIG/BIG':>16}{'BIG/LITTLE':>16}{'LITTLE/LITTLE':>16}")
    for tag, addr in FLOAT_REGS:
        regs, err = read_regs(client, unit, addr, 2)
        if regs is None:
            print(f"{tag:<26}{'read failed':>16}   {err}")
            continue
        bb = decode32(regs, "BIG", "BIG", True)
        bl = decode32(regs, "BIG", "LITTLE", True)
        ll = decode32(regs, "LITTLE", "LITTLE", True)
        print(f"{tag:<26}{bb:>16.3f}{bl:>16.3f}{ll:>16.3f}")

    print("\n-- 32-bit counters (device-maps.js expects byteOrder BIG / wordOrder LITTLE)")
    print(f"{'tag':<26}{'BIG/BIG':>16}{'BIG/LITTLE':>16}{'/divider':>18}")
    for tag, addr, divider in INT_REGS:
        regs, err = read_regs(client, unit, addr, 2)
        if regs is None:
            print(f"{tag:<26}{'read failed':>16}   {err}")
            continue
        bb = decode32(regs, "BIG", "BIG", False)
        bl = decode32(regs, "BIG", "LITTLE", False)
        scaled = f"{bl / divider:.6f}" if divider != 1 else "-"
        print(f"{tag:<26}{bb:>16d}{bl:>16d}{scaled:>18}")

    print(
        "\n  Sanity checks:\n"
        "   * TemperatureFlow / TemperatureReturn should read as plausible water\n"
        "     temperatures (roughly 5-90 C). Whichever column does is the right order.\n"
        "   * Compare the /divider energy column against the meter's own display. If it\n"
        "     matches, the kJ->kWh divider of 3600 is correct; if the undivided column\n"
        "     matches instead, drop the divider in device-maps.js."
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyAMA1", help="serial device (default /dev/ttyAMA1)")
    ap.add_argument("--baudrate", type=int, default=9600)
    ap.add_argument("--parity", default="N", choices=["N", "E", "O"])
    ap.add_argument("--stopbits", type=int, default=1)
    ap.add_argument("--bytesize", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=1.0, help="per-request timeout in seconds")
    ap.add_argument("--units", type=int, nargs="*",
                    help="specific unit IDs to inspect; omit to scan 1-247")
    ap.add_argument("--verbose", action="store_true", help="also log units that do not answer")
    args = ap.parse_args()

    ModbusSerialClient = _load_client_class()
    client = ModbusSerialClient(
        port=args.port,
        baudrate=args.baudrate,
        parity=args.parity,
        stopbits=args.stopbits,
        bytesize=args.bytesize,
        timeout=args.timeout,
    )
    if not client.connect():
        sys.exit(f"Could not open {args.port}. Check the port exists, that nothing else "
                 f"holds it (stop tb-gateway first), and that you have permission.")

    print(f"port {args.port} @ {args.baudrate} {args.bytesize}{args.parity}{args.stopbits}, "
          f"timeout {args.timeout}s")

    try:
        if args.units:
            units = args.units
            print(f"\ninspecting unit(s): {units}")
        else:
            print(f"\nscanning unit IDs 1-247 (probe: FC3 @ {PROBE_ADDRESS})...")
            units = scan(client, range(1, 248), args.verbose)
            if not units:
                sys.exit("\nNo devices answered. Check wiring/termination, A-B polarity, "
                         "baud rate, and that tb-gateway is stopped.")
            print(f"\nresponding unit IDs: {units}")

        for unit in units:
            dump(client, unit)

        print(f"\n{'=' * 72}")
        print("Put the responding unit IDs into provisioning/sites/<site>.json as")
        print("pflows[].unitId, in the PF1..PF4 order the site's dashboards expect.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
