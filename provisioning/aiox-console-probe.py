#!/usr/bin/env python3
"""
aiox-console-probe.py  --  RESI-C4 AIOX bring-up probe (reverse-engineered)

Reconstructed from the RESI SD-card source (SVN vmachine tree + the SI-BASIC
`.instance` programs + the vendor Node-RED flow). See docs/RESI_MIGRATION.md and
the memory note eco-gw-001-deployment.

FINDING that drives this script:
  The C4's onboard AIOX (PT1000 temperature channels feeding TS1/TS2) is NOT
  enabled by Modbus register writes. It is enabled by the STM32 *mainboard*,
  which is driven over an internal ASCII console ("Cx" protocol) on the
  `INTERN` serial port at 230400 8N1. The Modbus view (regs 40000/41064/49999
  on the "MODBUSINT" bus) is only a MIRROR and stays offline (isONLINE=0,
  reg 49999) until the mainboard is being driven -- specifically until the
  watchdog `#255,WD:` is served and channels are typed with `#255,SIOTYPS:`.

  Cx frame format (unit 255 == mainboard):
    GET:  #255,<CMD>/            e.g.  #255,VERSION/
    SET:  #255,<CMD>:<args>/     e.g.  #255,SIOTYPS:<types>/
  Responses look like  #255,<...>  /  OK  /  CMD OK  /  CMD ERR  /  :Timeout

This probe is READ-ONLY by default: it only sends GET commands, which are safe.
Its job is to (a) find which /dev/ttyACM* is the console, (b) confirm the
mainboard answers, and (c) dump GIOTYPS (current channel type codes -> lets us
decode the SIOTYPS encoding without disassembly) and GRTDISPT1000C (temps).
The watchdog kick and the SIOTYPS write are behind explicit flags because their
exact argument encoding is still unconfirmed -- do those only after reviewing
the GET responses this prints.

Usage (on the Pi, in the venv that has pyserial, e.g. ~/scanvenv):
    ~/scanvenv/bin/python aiox-console-probe.py                 # auto-discover + read
    ~/scanvenv/bin/python aiox-console-probe.py --port /dev/ttyACM0
    ~/scanvenv/bin/python aiox-console-probe.py --watchdog 10   # also kick WD, loop reads
    ~/scanvenv/bin/python aiox-console-probe.py --mirror /dev/ttyACM1 --mirror-baud 9600
"""
import argparse
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    sys.exit("pyserial not installed. Try: ~/scanvenv/bin/pip install pyserial")

CONSOLE_BAUD = 230400          # INTERN port baud (from INCLUDE.ifaceman.config)
UNIT = 255                     # mainboard unit id in the Cx protocol
CANDIDATE_PORTS = [f"/dev/ttyACM{i}" for i in range(6)]

# GET commands, safe (read-only). Trailing '/' marks a GET in the Cx protocol.
GET_CMDS = [
    "VERSION",      # firmware version -- proves the mainboard answers
    "TYPE",         # controller model, e.g. RESI-C4-A-...AIOX
    "SN",           # serial number
    "INTSTAT",      # internal status
    "GIOTYPS",      # <-- current AIOX channel TYPE codes (decodes SIOTYPS encoding)
    "GRTDISOHM",    # raw RTD ohms per channel
    "GRTDISPT1000C" # <-- PT1000 temperatures in Celsius (what we actually want)
]


def send_cmd(ser, cmd, is_get=True, args=None, settle=0.25):
    """Send one Cx frame and return the raw response bytes."""
    if is_get:
        frame = f"#{UNIT},{cmd}/"
    else:
        frame = f"#{UNIT},{cmd}:{args}/"
    ser.reset_input_buffer()
    # Terminator is unconfirmed; \r\n is the safe superset for line protocols.
    ser.write((frame + "\r\n").encode("ascii", "replace"))
    ser.flush()
    time.sleep(settle)
    buf = bytearray()
    deadline = time.time() + 1.0
    while time.time() < deadline:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            deadline = time.time() + 0.15  # extend while data keeps arriving
        else:
            time.sleep(0.02)
    return frame, bytes(buf)


def show(frame, resp):
    txt = resp.decode("ascii", "replace").strip()
    print(f"  -> {frame}")
    if resp:
        print(f"     raw ({len(resp)}B): {resp!r}")
        if txt:
            print(f"     txt: {txt}")
    else:
        print("     (no response)")


def looks_like_cx(resp):
    if not resp:
        return False
    t = resp.decode("ascii", "replace")
    return ("#%d" % UNIT) in t or "OK" in t.upper() or "ERR" in t.upper()


def open_console(port):
    return serial.Serial(port, CONSOLE_BAUD, bytesize=8, parity="N",
                         stopbits=1, timeout=0.2, write_timeout=1.0)


def discover(port_arg):
    ports = [port_arg] if port_arg else CANDIDATE_PORTS
    for p in ports:
        try:
            ser = open_console(p)
        except Exception as e:
            print(f"[skip] {p}: {e}")
            continue
        try:
            frame, resp = send_cmd(ser, "VERSION")
            hit = looks_like_cx(resp)
            print(f"[probe] {p} @ {CONSOLE_BAUD}: "
                  f"{'CONSOLE FOUND' if hit else 'no Cx reply'}")
            show(frame, resp)
            if hit:
                return ser, p
            ser.close()
        except Exception as e:
            print(f"[err] {p}: {e}")
            try:
                ser.close()
            except Exception:
                pass
    return None, None


def read_all(ser):
    print("\n== Cx GET sweep ==")
    for cmd in GET_CMDS:
        frame, resp = send_cmd(ser, cmd)
        show(frame, resp)


def mirror_check(port, baud, unit):
    """Optional: read the Modbus mirror (isONLINE / TYPE / PT1000)."""
    try:
        from pymodbus.client import ModbusSerialClient
    except ImportError:
        print("\n[mirror] pymodbus not installed; skipping Modbus mirror check.")
        return
    print(f"\n== Modbus mirror {port} @ {baud}, unit {unit} ==")
    cli = ModbusSerialClient(port=port, baudrate=baud, bytesize=8,
                             parity="N", stopbits=1, timeout=1)
    if not cli.connect():
        print("  could not open mirror port")
        return

    def rd(addr, count):
        # pymodbus 3.x kwarg drifted unit->slave->device_id; try each.
        for kw in ("device_id", "slave", "unit"):
            try:
                rr = cli.read_holding_registers(addr, count=count, **{kw: unit})
                if rr and not rr.isError():
                    return rr.registers
            except TypeError:
                continue
            except Exception:
                return None
        return None

    online = rd(49999, 1)
    print(f"  isONLINE (49999): {online}")
    types = rd(40000, 16)
    print(f"  TYPE   (40000-15): {types}")
    pt = rd(41064, 16)
    if pt:
        temps = [(v - 65536 if v > 32767 else v) / 100.0 for v in pt]
        print(f"  PT1000 (41064-79): {temps}")
    else:
        print("  PT1000 (41064-79): <no data>")
    cli.close()


def main():
    ap = argparse.ArgumentParser(description="RESI-C4 AIOX console probe")
    ap.add_argument("--port", help="console port (default: auto-discover ttyACM0-5)")
    ap.add_argument("--watchdog", type=float, metavar="SEC",
                    help="ALSO kick #255,WD:<arg> and loop reads. ARG ENCODING "
                         "UNCONFIRMED -- inspect GET output first. Value passed "
                         "verbatim as the WD argument.")
    ap.add_argument("--wd-arg", default="10",
                    help="argument sent in #255,WD:<arg> (default 10; unconfirmed units)")
    ap.add_argument("--loops", type=int, default=10,
                    help="number of watchdog/read cycles (with --watchdog)")
    ap.add_argument("--mirror", help="also read the Modbus mirror on this port")
    ap.add_argument("--mirror-baud", type=int, default=9600,
                    help="mirror baud (Node-RED said 9600; ifaceman said 115200)")
    ap.add_argument("--mirror-unit", type=int, default=1)
    args = ap.parse_args()

    ser, port = discover(args.port)
    if not ser:
        print("\nNo Cx console found. The mainboard may need the port held open, "
              "a different baud, or a different ttyACM. Meters/AIOX-mirror are "
              "separate buses.")
        if args.mirror:
            mirror_check(args.mirror, args.mirror_baud, args.mirror_unit)
        return 1

    print(f"\nUsing console: {port}")
    read_all(ser)

    if args.watchdog:
        print(f"\n== Watchdog loop: #{UNIT},WD:{args.wd_arg}/ every "
              f"{args.watchdog}s x{args.loops} ==")
        for i in range(args.loops):
            f, r = send_cmd(ser, "WD", is_get=False, args=args.wd_arg)
            show(f, r)
            f, r = send_cmd(ser, "GRTDISPT1000C")
            show(f, r)
            if args.mirror:
                mirror_check(args.mirror, args.mirror_baud, args.mirror_unit)
            time.sleep(args.watchdog)
    elif args.mirror:
        mirror_check(args.mirror, args.mirror_baud, args.mirror_unit)

    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
