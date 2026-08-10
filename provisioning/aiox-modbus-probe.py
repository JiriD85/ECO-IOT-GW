#!/usr/bin/env python3
"""
aiox-modbus-probe.py  --  read the C4 AIOX temperatures the way RESI's firmware did

DEFINITIVE finding (from disassembling the production SI-BASIC program
MCS.DoctorKit.instance for this exact HWID, ground-truthed against 613 log
samples): the two RTD temperature sensors (TS1/TS2, internal names IO01/IO02)
are the ONBOARD C4 AIOX, read as **Modbus unit 255 on the EXTERNAL meter bus**
(the SAME RS485 / same port as the P-Flow meters, 9600 8N1) via:

    FC04 (read INPUT registers), start address 0, count 8, signed-16, value/10 = °C

This is NOT unit 1, NOT a second internal serial port, and NOT the FC03
holding-register 41064 window (that was a generic Node-RED demo's map, never
what this firmware used). P-Flows on the same bus: FC03 holding, units
88/80/81/82.

This probe reads all 8 input registers from unit 255 and prints each raw,
signed, ÷10 and ÷100, so we can see immediately which indices are the temps and
confirm the scaling. Run it on the meter-bus port (the one already working for
the P-Flows).

Usage (Pi venv with pymodbus, e.g. ~/scanvenv):
    ~/scanvenv/bin/python aiox-modbus-probe.py                       # /dev/ttyACM2, unit 255
    ~/scanvenv/bin/python aiox-modbus-probe.py --port /dev/ttyACM0   # if enumeration differs
    ~/scanvenv/bin/python aiox-modbus-probe.py --also-holding        # also dump FC03 0..7 (compare)
"""
import argparse
import sys

try:
    from pymodbus.client import ModbusSerialClient
except ImportError:
    sys.exit("pymodbus not installed. Try: ~/scanvenv/bin/pip install pymodbus")


def signed16(v):
    return v - 65536 if v > 32767 else v


def read_fc(cli, fc, addr, count, unit):
    """Call read_input_registers (fc=4) or read_holding_registers (fc=3),
    coping with pymodbus 3.x kwarg drift (unit->slave->device_id)."""
    fn = cli.read_input_registers if fc == 4 else cli.read_holding_registers
    for kw in ("device_id", "slave", "unit"):
        try:
            rr = fn(addr, count=count, **{kw: unit})
        except TypeError:
            continue
        except Exception as e:
            return None, str(e)
        if rr is None:
            return None, "no response"
        if rr.isError():
            return None, str(rr)
        return rr.registers, None
    return None, "no compatible unit/slave/device_id kwarg"


def dump(regs, addr0):
    print(f"    {'idx':>3} {'addr':>5} {'raw':>7} {'signed':>7} {'/10':>9} {'/100':>9}")
    for i, v in enumerate(regs):
        s = signed16(v)
        print(f"    {i:>3} {addr0 + i:>5} {v:>7} {s:>7} {s / 10.0:>9.2f} {s / 100.0:>9.2f}")


def main():
    ap = argparse.ArgumentParser(description="RESI-C4 AIOX temperature probe (Modbus)")
    ap.add_argument("--port", default="/dev/ttyACM2",
                    help="meter-bus serial port (default /dev/ttyACM2 = MODBUSEXT)")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--unit", type=int, default=255,
                    help="AIOX/mainboard Modbus unit id (default 255)")
    ap.add_argument("--addr", type=int, default=0, help="start address (default 0)")
    ap.add_argument("--count", type=int, default=8, help="register count (default 8)")
    ap.add_argument("--also-holding", action="store_true",
                    help="also read FC03 holding registers at the same addr (comparison)")
    args = ap.parse_args()

    cli = ModbusSerialClient(port=args.port, baudrate=args.baud, bytesize=8,
                             parity="N", stopbits=1, timeout=1)
    if not cli.connect():
        sys.exit(f"could not open {args.port}")

    print(f"== unit {args.unit} @ {args.port} {args.baud} 8N1 ==")

    print(f"\nFC04 read INPUT registers  addr {args.addr} count {args.count}  "
          f"(this is the RESI firmware's RTD path -> IO01/IO02, /10 = degC)")
    regs, err = read_fc(cli, 4, args.addr, args.count, args.unit)
    if regs is not None:
        dump(regs, args.addr)
    else:
        print(f"    ERROR: {err}")
        print("    (all-zero or no response can mean the AIOX channels are not "
              "typed as RTD yet, or the mainboard/bus is not answering at 255.)")

    if args.also_holding:
        print(f"\nFC03 read HOLDING registers addr {args.addr} count {args.count}  (comparison)")
        regs, err = read_fc(cli, 3, args.addr, args.count, args.unit)
        if regs is not None:
            dump(regs, args.addr)
        else:
            print(f"    ERROR: {err}")

    cli.close()


if __name__ == "__main__":
    main()
