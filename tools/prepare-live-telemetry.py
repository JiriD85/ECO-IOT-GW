"""Prepare LOCAL deployment config; does not connect to or change any hardware.

Usage: python tools/prepare-live-telemetry.py <staged-config-dir> <staged-extension-dir>
Input is the existing generated tb_gateway.json / modbus connector files. Originals
are saved once as .pre-live backups. Install the tmpfs bind described in LIVE_UI.md.
"""
import json
import shutil
import sys
from pathlib import Path


def prepare(config_dir, extensions_dir, source=None):
    config_dir, extensions_dir = Path(config_dir), Path(extensions_dir)
    target = config_dir / 'tb_gateway.json'
    config = json.loads(target.read_text())
    connectors = [c for c in config.get('connectors', []) if c.get('type') in ('modbus', 'eco_modbus')]
    if not connectors:
        raise ValueError('No active Modbus connectors found')
    # Validate every source before changing any staged file.
    paths = []
    for connector in connectors:
        path = (config_dir / connector['configuration']).resolve()
        if not path.is_relative_to(config_dir.resolve()):
            raise ValueError('Connector path leaves the config directory')
        data = json.loads(path.read_text())
        if not isinstance(data.get('master', {}).get('slaves'), list):
            raise ValueError('Expected pinned 3.7.8 master.slaves configuration')
        paths.append((path, data))
    for path, data in paths:
        backup = path.with_suffix(path.suffix + '.pre-live')
        if not backup.exists():
            shutil.copyfile(path, backup)
        # Add fault status only for the firmware-verified AIOX map.
        for slave in data['master']['slaves']:
            if slave.get('unitId') != 255 or 'temperature' not in slave.get('deviceType', '').lower():
                continue
            for tag in list(slave.get('timeseries', [])):
                if tag.get('functionCode') == 4 and tag.get('address') in (0, 1):
                    address = tag['address'] + 6
                    if not any(t.get('address') == address and t.get('functionCode') == 4 for t in slave['timeseries']):
                        key = tag['tag'].removesuffix('_C') + '_error' if tag['tag'] != 'temperature' else 'sensor_error'
                        slave['timeseries'].append({'tag': key, 'type': '16uint', 'functionCode': 4, 'address': address, 'objectsCount': 1})
        path.write_text(json.dumps(data, indent=2) + '\n')
    backup = target.with_suffix('.json.pre-live')
    if not backup.exists():
        shutil.copyfile(target, backup)
    for connector in connectors:
        connector.update(type='eco_modbus', **{'class': 'EcoModbusConnector'})
    target.write_text(json.dumps(config, indent=2) + '\n')
    destination = extensions_dir / 'eco_modbus'
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source or Path(__file__).resolve().parents[1] / 'gateway/extensions/eco_modbus/live_modbus.py', destination / 'live_modbus.py')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    prepare(*sys.argv[1:])
