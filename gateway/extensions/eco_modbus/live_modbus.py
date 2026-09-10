"""Local read observer for the pinned AsyncModbusConnector (see docs/LIVE_UI.md).

Never opens a bus or changes polling/report strategy. Atomic snapshots belong on
tmpfs, shared read-only with the web backend. Observer failure cannot stop polling.
"""
import hashlib
import json
import logging
import math
import os
import time
from pathlib import Path

from thingsboard_gateway.connectors.modbus.modbus_connector import AsyncModbusConnector

log = logging.getLogger(__name__)


class EcoModbusConnector(AsyncModbusConnector):
    def __init__(self, gateway, config, connector_type):
        self._live_dir = Path(os.environ.get('ECO_LIVE_DIR', '/run/eco-telemetry'))
        self._live_groups = {}
        self._live_warning_at = 0
        self._live_observed = set()
        self._live_id = hashlib.sha256(str(config.get('id') or config.get('name')).encode()).hexdigest()[:16]
        super().__init__(gateway, config, connector_type)

    async def _AsyncModbusConnector__poll_device(self, slave):
        self._live_observed.discard(id(slave))
        try:
            return await super()._AsyncModbusConnector__poll_device(slave)
        finally:
            if id(slave) not in self._live_observed:
                self._observe(slave, {})
            self._live_observed.discard(id(slave))

    async def _AsyncModbusConnector__read_slave_data(self, slave):
        # Hook before conversion batching, report filtering, storage and MQTT.
        try:
            result = await super()._AsyncModbusConnector__read_slave_data(slave)
        except Exception:
            self._observe(slave, {})
            raise
        self._observe(slave, result)
        return result

    def _observe(self, slave, result):
        self._live_observed.add(id(slave))
        try:
            cfg = slave.uplink_converter_config
            tags = [t for section in ('attributes', 'telemetry') for t in getattr(cfg, section)]
            group_key = slave.device_name + ':' + hashlib.sha256(
                json.dumps(tags, sort_keys=True).encode()).hexdigest()[:12]
            previous = self._live_groups.get(group_key, {})
            readings = dict(previous.get('readings', {}))
            now = time.time()
            answered = False
            for section in ('attributes', 'telemetry'):
                for tag in getattr(cfg, section):
                    response = result.get(section, {}).get(tag['tag'])
                    if response is None or response.isError():
                        continue
                    answered = True
                    value = slave.uplink_converter.decode_data(response, tag, cfg.byte_order, cfg.word_order)
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                        readings[tag['tag']] = {'value': value, 'ts': now}
            self._live_groups[group_key] = {
                'name': slave.device_name, 'address': slave.unit_id,
                'model': cfg.device_type, 'poll_period': slave.poll_period,
                'last_poll': now, 'answered': answered,
                'last_seen': now if answered else previous.get('last_seen'),
                'readings': readings,
            }
            self._live_dir.mkdir(parents=True, exist_ok=True)
            target = self._live_dir / (self._live_id + '.json')
            temporary = target.with_suffix('.tmp')
            with temporary.open('w') as stream:
                json.dump({'version': 1, 'updated_at': now, 'groups': self._live_groups}, stream, allow_nan=False)
            os.replace(temporary, target)
        except Exception:
            if time.monotonic() - self._live_warning_at > 60:
                log.warning('Local telemetry observer unavailable', exc_info=True)
                self._live_warning_at = time.monotonic()
