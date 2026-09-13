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


def _atomic_config(path, data):
    """Sidecar state only; connector files remain owned by the TB configurator."""
    import tempfile
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.eco-state-')
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(data, output)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install_configuration_guard():
    """Keep the observer on cloud-created/edited Modbus connectors (pinned 3.7.8).

    Registered before RemoteConfigurator builds its bound handler table. Cloud
    remains authoritative; this only fixes the locally installed implementation
    and records the last successfully applied cloud configuration for offline undo.
    """
    from thingsboard_gateway.tb_utility.tb_gateway_remote_configurator import RemoteConfigurator
    if getattr(RemoteConfigurator, '_eco_guard_installed', False):
        return
    original = RemoteConfigurator._handle_connector_configuration_update

    def guarded(self, incoming):
        if not isinstance(incoming, dict) or incoming.get('type') not in ('modbus', 'eco_modbus'):
            return original(self, incoming)
        from copy import deepcopy
        config = deepcopy(incoming)
        config.update(type='eco_modbus', **{'class': 'EcoModbusConnector'})
        # An omitted filename is resolved the same way as upstream.
        filename = config.get('configuration') or config['name'].replace(' ', '_').lower() + '.json'
        root = Path(self._gateway.get_config_path()).resolve()
        target = (root / filename).resolve()
        if not target.is_relative_to(root) or target.name.startswith('.'):
            log.error('Rejected Modbus configuration path outside active configuration')
            return
        import fcntl
        with (root / '.eco-config.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = original(self, config)
            try:
                actual = json.loads(target.read_text())
                if actual.get('master') == config.get('configurationJson', {}).get('master'):
                    key = hashlib.sha256(filename.encode()).hexdigest()[:16]
                    _atomic_config(root / ('.eco-cloud-' + key + '.json'), actual)
                    (root / ('.eco-override-' + key + '.json')).unlink(missing_ok=True)
            except (OSError, ValueError):
                log.exception('Could not record applied cloud configuration')
            return result

    RemoteConfigurator._handle_connector_configuration_update = guarded
    RemoteConfigurator._eco_guard_installed = True


class EcoModbusConnector(AsyncModbusConnector):
    def __init__(self, gateway, config, connector_type):
        install_configuration_guard()
        self._live_dir = Path(os.environ.get('ECO_LIVE_DIR', '/run/eco-telemetry'))
        self._live_groups = {}
        self._live_warning_at = 0
        self._live_observed = set()
        self._live_id = hashlib.sha256(str(config.get('id') or config.get('name')).encode()).hexdigest()[:16]
        super().__init__(gateway, config, connector_type)
        try:
            root = Path(gateway.get_config_path())
            main = json.loads((root / 'tb_gateway.json').read_text())
            for entry in main.get('connectors', []):
                if entry.get('name') == config.get('name') or (config.get('id') and entry.get('id') == config['id']):
                    key = hashlib.sha256(entry['configuration'].encode()).hexdigest()[:16]
                    self._live_dir.mkdir(parents=True, exist_ok=True)
                    _atomic_config(self._live_dir / ('config-' + key + '.state'), config)
                    break
        except (OSError, ValueError):
            log.exception('Could not record loaded Modbus configuration')

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
