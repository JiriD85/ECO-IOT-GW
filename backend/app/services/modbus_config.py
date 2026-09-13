"""Local connector editor. No bus access or cloud administrator credentials."""
import hashlib
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from threading import RLock
from contextlib import contextmanager

LOCK = RLock()
PROFILES = json.loads(Path(__file__).with_name('modbus_profiles.json').read_text())


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def atomic(path, value):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.eco-write-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
            if hasattr(os, 'chown'):
                os.chown(tmp, path.stat().st_uid, path.stat().st_gid)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class ModbusConfig:
    def __init__(self, directory, live_dir='/run/eco-telemetry'):
        self.directory = Path(directory).resolve()
        self.live_dir = Path(live_dir)

    def entries(self):
        return [c for c in json.loads((self.directory / 'tb_gateway.json').read_text())['connectors']
                if c.get('type') in ('modbus', 'eco_modbus')]

    @contextmanager
    def writing(self):
        lock_path = self.directory / '.eco-config.lock'
        with LOCK, lock_path.open('a') as lock:
            if os.name != 'nt':
                import fcntl
                owner = self.directory.stat()
                os.chown(lock_path, owner.st_uid, owner.st_gid)
                os.chmod(lock_path, 0o660)
                fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def target(self, name):
        entry = next((c for c in self.entries() if c['name'] == name), None)
        if not entry:
            raise ValueError('Active Modbus connector not found')
        path = (self.directory / entry['configuration']).resolve()
        if not path.is_relative_to(self.directory) or path.name.startswith('.'):
            raise ValueError('Invalid connector path')
        return entry, path

    def state(self, name):
        entry, path = self.target(name)
        data = json.loads(path.read_text())
        key = hashlib.sha256(entry['configuration'].encode()).hexdigest()[:16]
        baseline = self.directory / ('.eco-cloud-' + key + '.json')
        override = self.directory / ('.eco-override-' + key + '.json')
        def read(p):
            try:
                return json.loads(p.read_text())
            except (OSError, ValueError):
                return None
        saved = read(override)
        runtime = read(self.live_dir / ('config-' + key + '.state'))
        # Compare the device configuration; the gateway adds its own root metadata.
        loaded = bool(runtime and runtime.get('master') == data.get('master'))
        return {'name': name, 'type': entry['type'], 'revision': revision(data),
                'configuration': data, 'loaded_configuration': runtime,
                'application': 'loaded' if loaded else 'pending_or_stopped',
                'temporary': bool(saved and saved.get('master') == data.get('master')),
                'can_restore': baseline.exists()}

    def list(self):
        with LOCK:
            return {'connectors': [self.state(e['name']) for e in self.entries()], 'profiles': PROFILES}

    def save(self, name, expected, slaves, restore=False):
        with self.writing():
            entry, path = self.target(name)
            old = json.loads(path.read_text())
            if revision(old) != expected:
                raise FileExistsError('Configuration changed. Reload before saving.')
            if entry['type'] != 'eco_modbus':
                raise ValueError('Install the live connector upgrade before editing locally')
            key = hashlib.sha256(entry['configuration'].encode()).hexdigest()[:16]
            if restore:
                baseline = self.directory / ('.eco-cloud-' + key + '.json')
                if not baseline.exists():
                    raise ValueError('No received ThingsBoard configuration is cached')
                new = json.loads(baseline.read_text())
            else:
                validate_slaves(slaves, old['master']['slaves'])
                new = deepcopy(old)
                new['master']['slaves'] = slaves
            atomic(self.directory / ('.eco-before-' + key + '.json'), old)
            atomic(path, new)
            marker = self.directory / ('.eco-override-' + key + '.json')
            if restore:
                marker.unlink(missing_ok=True)
            else:
                atomic(marker, new)
            return self.state(name)


def validate_slaves(slaves, existing):
    if not isinstance(slaves, list) or len(slaves) > 64:
        raise ValueError('Expected at most 64 register groups')
    editable = {'deviceName', 'deviceType', 'type', 'method', 'port', 'host', 'unitId', 'pollPeriod',
                'baudrate', 'bytesize', 'stopbits', 'parity', 'timeout', 'byteOrder', 'wordOrder',
                'timeseries', 'attributes', 'retries', 'retryOnEmpty', 'retryOnInvalid', 'strict',
                'connectAttemptTimeMs', 'connectAttemptCount', 'waitAfterFailedAttemptsMs', 'reportStrategy',
                'sendDataOnlyOnChange'}
    addresses = {}
    for s in slaves:
        if not isinstance(s, dict):
            raise ValueError('Invalid device')
        bus = json.dumps([s.get('type'), s.get('host'), s.get('port'), s.get('unitId')])
        name = s.get('deviceName')
        if bus in addresses and addresses[bus] != name and s.get('unitId') != 255:
            raise ValueError('Different devices cannot share the same bus address')
        addresses[bus] = name
    for s in slaves:
        if not isinstance(s, dict):
            raise ValueError('Invalid device')
        if s in existing:
            # Unknown cloud-created devices are retained verbatim.
            continue
        # Preserve existing custom converter/RPC fields, but never accept injected code via this editor.
        extra = {k: v for k, v in s.items() if k not in editable}
        if extra and not any(extra == {k: v for k, v in e.items() if k not in editable} for e in existing):
            raise ValueError('Custom converter/RPC settings must be managed in ThingsBoard')
        name = s.get('deviceName')
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or '${' in name:
            raise ValueError('Use a fixed device name (1–128 characters)')
        def number(key, low, high):
            value = s.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError(f'{name}: invalid {key}')
        number('unitId', 1, 255)
        if not isinstance(s['unitId'], int):
            raise ValueError('Address must be an integer')
        number('pollPeriod', 1000, 86400000)
        number('timeout', 0.1, 60)
        if s.get('byteOrder') not in ('BIG', 'LITTLE') or s.get('wordOrder') not in ('BIG', 'LITTLE'):
            raise ValueError('Invalid byte/word order')
        if s.get('type') == 'serial':
            if not isinstance(s.get('port'), str) or not s['port'].startswith('/dev/') or '..' in s['port']:
                raise ValueError('Select a serial device under /dev')
            number('baudrate', 300, 1000000)
            if s.get('parity') not in ('N', 'E', 'O') or s.get('bytesize') not in (7, 8) or s.get('stopbits') not in (1, 2):
                raise ValueError('Invalid serial framing')
        elif s.get('type') in ('tcp', 'udp'):
            number('port', 1, 65535)
            if not isinstance(s.get('host'), str) or not s['host'].strip():
                raise ValueError('Host is required')
        else:
            raise ValueError('Supported transports: serial, tcp, udp')
        for section in ('timeseries', 'attributes'):
            tags = s.get(section, [])
            if not isinstance(tags, list) or len(tags) > 128:
                raise ValueError('Too many telemetry fields')
            for tag in tags:
                if any(tag in e.get(section, []) for e in existing):
                    continue  # Preserve unfamiliar, unchanged cloud mappings.
                if not isinstance(tag, dict) or set(tag) - {'tag', 'type', 'functionCode', 'objectsCount', 'address', 'divider', 'multiplier', 'reportStrategy'}:
                    raise ValueError('Unsupported telemetry mapping field')
                if not isinstance(tag.get('tag'), str) or not tag['tag'] or len(tag['tag']) > 128:
                    raise ValueError('Telemetry name is required')
                if tag.get('functionCode') not in (1, 2, 3, 4):
                    raise ValueError('Only read function codes 1–4 are allowed')
                if tag.get('type') not in ('8int', '8uint', '16int', '16uint', '32int', '32uint', '64int', '64uint', '16float', '32float', '64float', 'bits', 'string'):
                    raise ValueError('Unsupported Modbus data type')
                if not isinstance(tag.get('address'), int) or not 0 <= tag['address'] <= 65535:
                    raise ValueError('Register address must be 0–65535')
                if not isinstance(tag.get('objectsCount'), int) or not 1 <= tag['objectsCount'] <= 125:
                    raise ValueError('Register count must be 1–125')
                for field in ('divider', 'multiplier'):
                    if field in tag and (not isinstance(tag[field], (int, float)) or not abs(tag[field]) < 1e20 or tag[field] == 0):
                        raise ValueError('Invalid scaling')
