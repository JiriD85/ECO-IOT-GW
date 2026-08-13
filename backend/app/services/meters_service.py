"""
ECO-IOT-GW Meters Service

Read-only view of the child-device telemetry the ThingsBoard gateway is producing,
plus a connector health summary. Everything here is derived from the gateway's own
config + container logs -- it never touches the RS485 bus directly (that would
collide with the gateway's polling) and never edits config (editing lives in
ThingsBoard).

Data sources (all local to the device):
  * the connector JSON (e.g. 3Rs485Pf.json) and connected_devices.json in the
    gateway's config Docker volume  -> device list, per-tag register map, port/baud
  * the tb-gateway container DEBUG log -> latest raw register reads, decoded here
    per each tag's type / word order / divider (matching the connector's own decode)

The connector must be at logLevel DEBUG for live values to appear in the log
(that is how this fleet is configured). Without DEBUG lines a device still shows
up from config, just without fresh values.
"""
import json
import logging
import re
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import settings

logger = logging.getLogger(__name__)

# A device's newest value older than this is considered stale (poll period is 60s).
STALE_SECONDS = 180
# How many recent gateway log lines to scan (one 60s cycle is a few hundred DEBUG lines).
LOG_LINES = 8000

# unit hints derived from a tag's suffix, for display only
_UNIT_SUFFIX = [
    ("_m3h", "m³/h"), ("_m3", "m³"), ("_ms", "m/s"),
    ("_kwh", "kWh"), ("_c", "°C"), ("_exp", ""),
]

# ---- log line patterns ------------------------------------------------------
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_READING_RE = re.compile(r"Reading (\d+) registers from address (\d+) with function code (\d+)")
_RESULT_RE = re.compile(r"Read with result: Read\w+RegistersResponse\(dev_id=(\d+),.*?registers=\[([0-9,\s-]*)\], status=(\d+)\)")
_FAIL_RE = re.compile(r"Failed to poll (\S+) device")


class MetersService:
    def __init__(self):
        self._fallback_config_dir: Path = settings.TB_GATEWAY_CONFIG_DIR

    # ---- public -------------------------------------------------------------

    def get_latest(self) -> Dict[str, Any]:
        container = self._find_gateway_container()
        config_dir = self._config_dir_host(container)
        slaves = self._load_slaves(config_dir)
        disconnected = self._load_connected_devices(config_dir)

        # regkey (unitId, functionCode, address) -> tag descriptor
        regmap: Dict[Tuple[int, int, int], Dict[str, Any]] = {}
        # deviceName -> merged descriptor
        devices: Dict[str, Dict[str, Any]] = {}
        port = baud = None
        for s in slaves:
            name = s.get("deviceName")
            if not name:
                continue
            port = port or s.get("port")
            baud = baud or s.get("baudrate")
            dev = devices.setdefault(name, {
                "name": name,
                "model": s.get("deviceType") or "",
                "address": s.get("unitId"),
                "tags": [],  # ordered tag descriptors
            })
            word_order = s.get("wordOrder", "BIG")
            for group in ("timeseries", "attributes"):
                for t in s.get(group, []):
                    desc = {
                        "tag": t.get("tag") or t.get("key"),
                        "type": t.get("type", "16int"),
                        "fc": t.get("functionCode", 3),
                        "address": t.get("address"),
                        "divider": t.get("divider"),
                        "word_order": word_order,
                    }
                    if desc["tag"] is None or desc["address"] is None:
                        continue
                    dev["tags"].append(desc)
                    regmap[(s.get("unitId"), desc["fc"], desc["address"])] = {
                        "device": name, **desc,
                    }

        # Drop default/template slaves: when the gateway reports its connected
        # devices, keep only those (excludes tb-gateway's shipped example slaves).
        if disconnected:
            devices = {n: d for n, d in devices.items() if n in disconnected}

        values, last_seen, failed = self._parse_logs(container, regmap)

        now = datetime.now(timezone.utc)
        out_devices = [
            self._build_device(name, dev, values, last_seen, failed, disconnected, now)
            for name, dev in devices.items()
        ]
        out_devices.sort(key=lambda d: (d["role"] != "meter", d["key"]))

        return {
            "updated_at": now.isoformat(),
            "connector": {
                "name": self._connector_name(config_dir) or "RS485 Modbus",
                "type": "Modbus RTU",
                "running": bool(container and container.status == "running"),
                "container": container.name if container else None,
                "thingsboard_linked": self._tb_linked(container),
                "serial_port": port,
                "baudrate": baud,
            },
            "devices": out_devices,
        }

    # ---- docker / config ----------------------------------------------------

    def _find_gateway_container(self):
        try:
            from .docker_service import docker_service
            for c in docker_service.get_containers():
                if "thingsboard" in c.name.lower() or "gateway" in c.name.lower():
                    # need the raw SDK object for .attrs/.logs
                    return docker_service.client.containers.get(c.name)
        except Exception as e:
            logger.warning(f"gateway container lookup failed: {e}")
        return None

    def _config_dir_host(self, container) -> Path:
        try:
            if container:
                for m in container.attrs.get("Mounts", []):
                    if m.get("Destination") == "/thingsboard_gateway/config":
                        return Path(m["Source"])
        except Exception as e:
            logger.debug(f"mount resolve failed: {e}")
        return self._fallback_config_dir

    def _connector_files(self, config_dir: Path) -> List[Path]:
        try:
            return sorted(p for p in config_dir.glob("*.json"))
        except Exception:
            return []

    def _load_slaves(self, config_dir: Path) -> List[Dict[str, Any]]:
        slaves: List[Dict[str, Any]] = []
        for path in self._connector_files(config_dir):
            try:
                with open(path) as f:
                    cfg = json.load(f)
            except Exception:
                continue
            if not isinstance(cfg, dict):
                continue
            master = cfg.get("master")
            if isinstance(master, dict) and isinstance(master.get("slaves"), list):
                slaves.extend(master["slaves"])
        return slaves

    def _connector_name(self, config_dir: Path) -> Optional[str]:
        for path in self._connector_files(config_dir):
            try:
                with open(path) as f:
                    cfg = json.load(f)
            except Exception:
                continue
            if not isinstance(cfg, dict):
                continue
            if isinstance(cfg.get("master"), dict) and cfg["master"].get("slaves"):
                return cfg.get("name")
        return None

    def _load_connected_devices(self, config_dir: Path) -> Dict[str, bool]:
        """deviceName -> disconnected flag."""
        out: Dict[str, bool] = {}
        path = config_dir / "connected_devices.json"
        try:
            with open(path) as f:
                data = json.load(f)
            for name, info in data.items():
                out[name] = bool(info.get("disconnected", False))
        except Exception:
            pass
        return out

    def _tb_linked(self, container) -> Optional[bool]:
        """Best-effort: scan recent log for a platform connect/disconnect signal."""
        try:
            if not container:
                return None
            text = container.logs(tail=1500).decode("utf-8", "replace")
            linked = None
            for line in text.splitlines():
                low = line.lower()
                if "mqtt" in low or "platform" in low or "thingsboard" in low:
                    if "connected" in low and "disconnect" not in low:
                        linked = True
                    elif "disconnect" in low or "connection lost" in low:
                        linked = False
            return linked
        except Exception:
            return None

    # ---- log parsing / decode -----------------------------------------------

    def _parse_logs(self, container, regmap):
        values: Dict[Tuple[int, int, int], float] = {}
        last_seen: Dict[str, datetime] = {}
        failed: Dict[str, datetime] = {}
        if not container:
            return values, last_seen, failed
        try:
            text = container.logs(tail=LOG_LINES).decode("utf-8", "replace")
        except Exception as e:
            logger.warning(f"reading gateway logs failed: {e}")
            return values, last_seen, failed

        pending: Optional[Tuple[int, int]] = None  # (fc, address) from last "Reading" line
        for line in text.splitlines():
            ts = self._ts(line)
            rd = _READING_RE.search(line)
            if rd:
                pending = (int(rd.group(3)), int(rd.group(2)))  # (fc, address)
                continue
            res = _RESULT_RE.search(line)
            if res and pending is not None:
                unit = int(res.group(1))
                regs = [int(x) for x in res.group(2).split(",") if x.strip() != ""]
                fc, addr = pending
                pending = None
                desc = regmap.get((unit, fc, addr))
                if not desc or res.group(3) != "1" or not regs:
                    continue
                val = self._decode(regs, desc["type"], desc["word_order"], desc["divider"])
                if val is None:
                    continue
                values[(unit, fc, addr)] = val
                if ts:
                    dev = desc["device"]
                    if dev not in last_seen or ts > last_seen[dev]:
                        last_seen[dev] = ts
                continue
            fail = _FAIL_RE.search(line)
            if fail and ts:
                failed[fail.group(1)] = ts
        return values, last_seen, failed

    def _ts(self, line: str) -> Optional[datetime]:
        m = _TS_RE.match(line)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _decode(self, regs, typ, word_order, divider):
        try:
            typ = (typ or "16int").lower()
            if typ in ("16int", "16uint"):
                b = struct.pack(">H", regs[0] & 0xFFFF)
                val = struct.unpack(">h" if typ == "16int" else ">H", b)[0]
            else:
                if len(regs) < 2:
                    return None
                if (word_order or "BIG").upper() == "LITTLE":
                    hi, lo = regs[1], regs[0]
                else:
                    hi, lo = regs[0], regs[1]
                b = struct.pack(">HH", hi & 0xFFFF, lo & 0xFFFF)
                if typ == "32float":
                    val = struct.unpack(">f", b)[0]
                elif typ == "32uint":
                    val = struct.unpack(">I", b)[0]
                else:  # 32int
                    val = struct.unpack(">i", b)[0]
            if divider:
                val = val / divider
            if isinstance(val, float):
                val = round(val, 3)
            return val
        except Exception:
            return None

    # ---- shaping ------------------------------------------------------------

    def _build_device(self, name, dev, values, last_seen, failed, disconnected, now):
        suffix = name.split("-")[-1].lower()  # e.g. pf1, ts1
        role = "temperature" if "temperature" in (dev["model"] or "").lower() or suffix.startswith("ts") else "meter"
        label = self._label(suffix)

        readings = []
        for t in dev["tags"]:
            key = (dev["address"], t["fc"], t["address"])
            if key in values:
                readings.append({
                    "tag": t["tag"],
                    "value": values[key],
                    "unit": self._unit_for(t["tag"]),
                })

        seen = last_seen.get(name)
        fail = failed.get(name)
        status = "no_report"
        if disconnected.get(name):
            status = "error"
        elif seen:
            age = (now - seen).total_seconds()
            status = "ok" if age <= STALE_SECONDS else "stale"
        elif fail:
            status = "error"

        return {
            "key": suffix,
            "name": name,
            "label": label,
            "role": role,
            "model": dev["model"],
            "address": dev["address"],
            "configured": True,
            "status": status,
            "last_seen": seen.isoformat() if seen else None,
            "readings": readings,
        }

    def _label(self, suffix: str) -> str:
        m = re.match(r"([a-z]+)(\d+)", suffix)
        if not m:
            return suffix
        base, num = m.group(1), m.group(2)
        return {"pf": "P-Flow", "ts": "Temp"}.get(base, base.upper()) + " " + num

    def _unit_for(self, tag: str) -> str:
        low = (tag or "").lower()
        for suf, unit in _UNIT_SUFFIX:
            if low.endswith(suf):
                return unit
        return ""


meters_service = MetersService()
