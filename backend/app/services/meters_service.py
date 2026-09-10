"""Configured meter inventory plus local read-boundary snapshots.

Never queries the bus, logs, MQTT or ThingsBoard. See docs/LIVE_UI.md for the
observer installation and the hardware acceptance checks required before rollout.
"""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import settings

logger = logging.getLogger(__name__)

# unit hints derived from a tag's suffix, for display only
_UNIT_SUFFIX = [
    ("_m3h", "m³/h"), ("_m3", "m³"), ("_ms", "m/s"),
    ("_kwh", "kWh"), ("_c", "°C"), ("_exp", ""),
]

class MetersService:
    def __init__(self):
        from threading import Lock
        self._lock = Lock()
        self._cached = None
        self._cached_at = self._config_at = 0
        self._fallback_config_dir: Path = settings.TB_GATEWAY_CONFIG_DIR

    # ---- public -------------------------------------------------------------

    def get_latest(self) -> Dict[str, Any]:
        # One inexpensive sample shared by all callers, blocking Docker discovery
        # at most once every 30 seconds, never on FastAPI's event-loop thread.
        import time
        from .live_meters import read_snapshot
        with self._lock:
            now = time.monotonic()
            if self._cached is not None and now - self._cached_at < 0.5:
                return self._cached
            if now - self._config_at > 30 or self._config_at == 0:
                container = self._find_gateway_container()
                self._config_dir = self._config_dir_host(container) if container else getattr(self, '_config_dir', self._fallback_config_dir)
                self._inventory_notice = None
                try:
                    # Keep the known inventory on transient Docker/config errors.
                    # An explicit empty active list still removes the devices.
                    active = json.loads((self._config_dir / 'tb_gateway.json').read_text())['connectors']
                    for entry in active:
                        if entry.get('type') in ('modbus', 'eco_modbus'):
                            json.loads((self._config_dir / entry['configuration']).read_text())
                    self._slaves = self._load_slaves(self._config_dir)
                except (OSError, ValueError, KeyError, TypeError):
                    self._slaves = getattr(self, '_slaves', [])
                    self._inventory_notice = 'Connector configuration unavailable. Showing the last known device list.'
                self._connector = {
                    "name": self._connector_name(self._config_dir) or "RS485 Modbus",
                    "type": "Modbus RTU",
                    "running": bool(container and container.status == "running"),
                    "container": container.name if container else None,
                    "thingsboard_linked": None,
                    "serial_port": next((s.get("port") for s in self._slaves if s.get("port")), None),
                    "baudrate": next((s.get("baudrate") for s in self._slaves if s.get("baudrate")), None),
                }
                self._config_at = now
            devices, available = read_snapshot(self._slaves, self._label, self._unit_for)
            devices.sort(key=lambda d: (d["role"] != "meter", d["name"]))
            self._cached = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "local_modbus" if available else "unavailable",
                "notice": self._inventory_notice or (None if available else "Local Modbus data unavailable. Check the connector service; device connection states are unknown."),
                "connector": self._connector,
                "devices": devices,
            }
            self._cached_at = now
            return self._cached

    # ---- docker / config ----------------------------------------------------

    def _find_gateway_container(self):
        try:
            from .docker_service import docker_service
            for c in docker_service.client.containers.list(all=True):
                if c.name == 'tb-gateway' or 'thingsboard/tb-gateway' in c.attrs.get('Config', {}).get('Image', '').lower():
                    return c
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
        """Config files of the connectors the gateway ACTUALLY loads, from
        tb_gateway.json's `connectors` list -- so example/template connector files
        sitting in the config dir (and their placeholder devices) are ignored.
        Unreadable active config must not promote example JSON files to devices."""
        try:
            with open(config_dir / "tb_gateway.json") as f:
                conns = json.load(f).get("connectors", [])
            files = [config_dir / c["configuration"] for c in conns if c.get("configuration")]
            files = [p for p in files if p.exists()]
            return files
        except Exception:
            pass
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
