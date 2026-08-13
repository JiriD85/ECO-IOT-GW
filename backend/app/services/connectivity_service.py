"""
Fast, accurate connectivity status for the dashboard.

The backend runs on the HOST (systemd, not Docker), so kernel state is the source
of truth: network routes, NetworkManager connections, and — for ThingsBoard — the
tb-gateway container's OWN socket table read from the host via /proc. No AT
commands to the modem, no log scraping. Each check reads the truth directly and
returns in milliseconds; the four run concurrently and the assembled result is
cached briefly so 5s dashboard polling stays cheap.

This is deliberately separate from modem_service / vpn_service (which drive the
detailed device pages): here we only need a fast, reliable up/down for each tile.
"""
import logging
import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_CACHE_TTL = 3.0
_cache = {"ts": 0.0, "value": None}


def _nmcli_active() -> List[Tuple[str, str, str]]:
    """(device, type, state) for each active NM connection; [] on failure."""
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "con", "show", "--active"],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception as e:  # nmcli missing / timeout
        logger.warning("nmcli active-connections failed: %s", e)
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def _default_iface() -> Optional[str]:
    """Interface of the current default route, from /proc/net/route (no subprocess)."""
    try:
        with open("/proc/net/route") as f:
            next(f)  # header
            for line in f:
                p = line.split()
                if len(p) > 1 and p[1] == "00000000":  # destination 0.0.0.0
                    return p[0]
    except Exception:
        pass
    return None


def _check_modem(active: List[Tuple[str, str, str]]) -> bool:
    """LTE up = an activated GSM/cellular NM connection, or wwan0 is the uplink."""
    for dev, typ, state in active:
        if state == "activated" and ("gsm" in typ or "cdma" in typ or dev in ("wwan0", "cdc-wdm0")):
            return True
    return _default_iface() == "wwan0"


def _check_vpn() -> bool:
    """VPN feature up = an OpenVPN/WireGuard interface exists. Tailscale excluded
    (it's a separate transport, not the VPN feature)."""
    try:
        for iface in os.listdir("/sys/class/net"):
            if iface == "tailscale0":
                continue
            if iface.startswith(("tun", "wg")):
                return True
    except Exception:
        pass
    return False


def _check_internet() -> bool:
    """Reachability via a short TCP connect to a public DNS resolver (no ICMP)."""
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            socket.create_connection((host, 53), timeout=1.2).close()
            return True
        except Exception:
            continue
    return False


def _check_thingsboard() -> bool:
    """Gateway connected = tb-gateway running AND holding a live MQTT socket.

    Read the container's own TCP table from the host (/proc/<pid>/net/tcp[,6]) and
    look for an ESTABLISHED connection to an MQTT port. This reflects the actual
    gateway->broker link, not a container restart or a stale log line.
    """
    try:
        import docker
        container = docker.from_env().containers.get("tb-gateway")
        if container.status != "running":
            return False
        pid = container.attrs.get("State", {}).get("Pid")
        if not pid:
            return False
        for proc in (f"/proc/{pid}/net/tcp", f"/proc/{pid}/net/tcp6"):
            try:
                with open(proc) as f:
                    next(f)  # header
                    for line in f:
                        cols = line.split()
                        if len(cols) < 4 or cols[3] != "01":  # 01 = ESTABLISHED
                            continue
                        rport = int(cols[2].rsplit(":", 1)[1], 16)
                        if rport in (1883, 8883):
                            return True
            except FileNotFoundError:
                continue
    except Exception as e:
        logger.warning("thingsboard connectivity check failed: %s", e)
    return False


def get_status(use_cache: bool = True) -> dict:
    """{'modem','vpn','internet','thingsboard': bool}. Fast; cached ~3s."""
    now = time.monotonic()
    if use_cache and _cache["value"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["value"]

    active = _nmcli_active()  # one call; modem/vpn derive from it instantly
    # Only the two checks with real latency (network I/O) run in threads.
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_net = ex.submit(_check_internet)
        f_tb = ex.submit(_check_thingsboard)
        result = {
            "modem": _check_modem(active),
            "vpn": _check_vpn(),
            "internet": f_net.result(),
            "thingsboard": f_tb.result(),
        }

    _cache["value"] = result
    _cache["ts"] = now
    return result
