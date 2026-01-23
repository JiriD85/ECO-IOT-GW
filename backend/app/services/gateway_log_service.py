"""
ECO-IOT-GW Gateway Log Service
ThingsBoard Gateway log parsing for Modbus values
"""
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import settings
from ..models.schemas import GatewayLogEntry, ModbusValue

logger = logging.getLogger(__name__)


class GatewayLogService:
    """Service for parsing ThingsBoard Gateway logs."""

    def __init__(self):
        self._log_dir = settings.TB_GATEWAY_LOG_DIR
        self._config_dir = settings.TB_GATEWAY_CONFIG_DIR
        self._modbus_value_cache: Dict[str, ModbusValue] = {}

    def get_logs(
        self,
        level: Optional[str] = None,
        connector: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[GatewayLogEntry]:
        """
        Parse Gateway logs and return entries.

        Args:
            level: Filter by log level
            connector: Filter by connector name
            limit: Max entries to return
            offset: Skip first N entries

        Returns:
            List of GatewayLogEntry objects
        """
        entries = []
        log_file = self._log_dir / "connector.log"

        if not log_file.exists():
            # Try alternative log location
            log_file = self._log_dir / "tb_gateway.log"

        if not log_file.exists():
            return entries

        try:
            # Read log file in reverse (newest first)
            with open(log_file, 'r') as f:
                lines = f.readlines()

            # Parse log lines
            log_pattern = re.compile(
                r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d{3})\s+-\s+(\w+)\s+-\s+\[([^\]]*)\]\s+-\s+(.*)'
            )

            for line in reversed(lines):
                match = log_pattern.match(line.strip())
                if not match:
                    continue

                timestamp_str, log_level, connector_name, message = match.groups()

                # Apply filters
                if level and log_level.upper() != level.upper():
                    continue
                if connector and connector.lower() not in connector_name.lower():
                    continue

                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                except ValueError:
                    timestamp = datetime.now()

                entries.append(GatewayLogEntry(
                    timestamp=timestamp,
                    level=log_level,
                    message=message,
                    connector=connector_name if connector_name else None
                ))

                if len(entries) >= offset + limit:
                    break

            # Apply offset
            return entries[offset:offset + limit]

        except Exception as e:
            logger.error(f"Failed to parse gateway logs: {e}")
            return entries

    def get_modbus_values(
        self,
        device: Optional[str] = None,
        limit: int = 100
    ) -> List[ModbusValue]:
        """
        Extract Modbus values from Gateway logs.

        The Gateway logs Modbus read results, which we parse here.
        """
        values = []

        # Pattern for Modbus values in logs
        # Example: "Converted data: {'temperature': 23.5, 'humidity': 45.0}"
        value_pattern = re.compile(
            r'Converted data.*?device.*?["\'](\w+)["\'].*?:\s*(\{[^}]+\})'
        )

        # Alternative pattern
        alt_pattern = re.compile(
            r'Reading from device\s+(\w+).*?register\s+(\d+).*?value[:\s]+(\d+\.?\d*)'
        )

        log_file = self._log_dir / "connector.log"
        if not log_file.exists():
            log_file = self._log_dir / "tb_gateway.log"

        if not log_file.exists():
            # Return cached values if no log file
            return list(self._modbus_value_cache.values())[:limit]

        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()

            seen = set()
            for line in reversed(lines):
                # Try to extract Modbus data
                match = value_pattern.search(line)
                if match:
                    device_name = match.group(1)
                    if device and device_name != device:
                        continue

                    try:
                        data = json.loads(match.group(2).replace("'", '"'))
                        timestamp = self._extract_timestamp(line)

                        for key, value in data.items():
                            cache_key = f"{device_name}:{key}"
                            if cache_key not in seen:
                                seen.add(cache_key)
                                mv = ModbusValue(
                                    device=device_name,
                                    register=key,
                                    value=value,
                                    timestamp=timestamp
                                )
                                values.append(mv)
                                self._modbus_value_cache[cache_key] = mv

                    except json.JSONDecodeError:
                        pass

                # Try alternative pattern
                alt_match = alt_pattern.search(line)
                if alt_match:
                    device_name = alt_match.group(1)
                    if device and device_name != device:
                        continue

                    register = alt_match.group(2)
                    value = float(alt_match.group(3))
                    timestamp = self._extract_timestamp(line)

                    cache_key = f"{device_name}:{register}"
                    if cache_key not in seen:
                        seen.add(cache_key)
                        mv = ModbusValue(
                            device=device_name,
                            register=register,
                            value=value,
                            timestamp=timestamp
                        )
                        values.append(mv)
                        self._modbus_value_cache[cache_key] = mv

                if len(values) >= limit:
                    break

            return values

        except Exception as e:
            logger.error(f"Failed to extract Modbus values: {e}")
            return list(self._modbus_value_cache.values())[:limit]

    def _extract_timestamp(self, line: str) -> datetime:
        """Extract timestamp from log line."""
        match = re.match(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        return datetime.now()

    def get_configured_devices(self) -> List[Dict[str, Any]]:
        """Get devices from Gateway Modbus configuration."""
        devices = []

        modbus_config = self._config_dir / "modbus.json"
        if not modbus_config.exists():
            return devices

        try:
            with open(modbus_config) as f:
                config = json.load(f)

            # Parse devices from config
            for slave in config.get("slaves", []):
                device = {
                    "name": slave.get("name", "Unknown"),
                    "host": slave.get("host"),
                    "port": slave.get("port"),
                    "unit_id": slave.get("unitId", 1),
                    "attributes": [],
                    "timeseries": []
                }

                # Get attributes
                for attr in slave.get("attributes", []):
                    device["attributes"].append({
                        "name": attr.get("name"),
                        "type": attr.get("type"),
                        "address": attr.get("address")
                    })

                # Get timeseries
                for ts in slave.get("timeseries", []):
                    device["timeseries"].append({
                        "name": ts.get("name"),
                        "type": ts.get("type"),
                        "address": ts.get("address")
                    })

                devices.append(device)

        except Exception as e:
            logger.error(f"Failed to parse Modbus config: {e}")

        return devices

    def get_connectors(self) -> List[Dict[str, Any]]:
        """Get list of configured connectors."""
        connectors = []

        tb_gateway_config = self._config_dir / "tb_gateway.yaml"
        if not tb_gateway_config.exists():
            tb_gateway_config = self._config_dir / "tb_gateway.json"

        if not tb_gateway_config.exists():
            return connectors

        try:
            with open(tb_gateway_config) as f:
                if tb_gateway_config.suffix == '.yaml':
                    import yaml
                    config = yaml.safe_load(f)
                else:
                    config = json.load(f)

            for connector in config.get("connectors", []):
                connectors.append({
                    "name": connector.get("name"),
                    "type": connector.get("type"),
                    "configuration": connector.get("configuration")
                })

        except Exception as e:
            logger.error(f"Failed to parse gateway config: {e}")

        return connectors

    def check_thingsboard_connection(self) -> bool:
        """Check if Gateway is connected to ThingsBoard."""
        # Check by looking for recent successful connection log
        log_file = self._log_dir / "connector.log"
        if not log_file.exists():
            log_file = self._log_dir / "tb_gateway.log"

        if not log_file.exists():
            return False

        try:
            # Check last 100 lines for connection status
            with open(log_file, 'r') as f:
                lines = f.readlines()[-100:]

            for line in reversed(lines):
                if 'Connected to ThingsBoard' in line or 'connection established' in line.lower():
                    return True
                if 'disconnected' in line.lower() or 'connection lost' in line.lower():
                    return False

        except Exception as e:
            logger.warning(f"Failed to check TB connection: {e}")

        return False

    def check_internet(self) -> bool:
        """Check internet connectivity."""
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2", "8.8.8.8"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False


# Global gateway log service instance
gateway_log_service = GatewayLogService()
