#!/usr/bin/env python3
# Minimal, fast Modbus-RTU presence probe. Prints "PRESENT <unit>" for each unit id
# that answers an FC03 read of 1 register at address 0. Read-only, tight timeout.
# Only run when the meter bus is FREE (no tb-gateway container holding it) — a
# concurrent open corrupts the live bus.
#
#   bus-probe.py <port> <baud> <unit,unit,...>
import sys, struct
try:
    import serial
except Exception as e:
    print("NOSERIAL %s" % e); sys.exit(2)

def crc(d):
    c = 0xFFFF
    for b in d:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return struct.pack('<H', c)

port = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyACM2'
baud = int(sys.argv[2]) if len(sys.argv) > 2 else 9600
units = [int(x) for x in (sys.argv[3].split(',') if len(sys.argv) > 3 else ['88'])]

try:
    s = serial.Serial(port, baud, timeout=0.3)
except Exception as e:
    print("OPENFAIL %s" % e); sys.exit(3)

for u in units:
    try:
        req = struct.pack('>BBHH', u, 3, 0, 1)
        req += crc(req)
        s.reset_input_buffer()
        s.write(req)
        r = s.read(7)
        if len(r) >= 5 and r[0] == u and r[1] in (3, 0x83):
            print("PRESENT %d" % u)
    except Exception:
        pass
s.close()
print("DONE")
