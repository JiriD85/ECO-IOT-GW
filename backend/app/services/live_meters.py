"""Read bounded atomic snapshots, independently of Docker logs and cloud state."""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

_files = {}  # Bounded decoded snapshots keyed by path + inode/mtime/size.


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def read_snapshot(slaves, label, unit, directory=None, now=None):
    now = time.time() if now is None else now
    directory = Path(directory or os.environ.get('ECO_LIVE_DIR', '/run/eco-telemetry'))
    groups = []
    paths = list(directory.glob('*.json'))[:32]
    for cached in list(_files):
        if cached not in paths:
            del _files[cached]
    for path in paths:
        try:
            stat = path.stat()
            if stat.st_size > 2_000_000:
                continue
            signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            cached = _files.get(path)
            if cached and cached[0] == signature:
                data = cached[1]
            else:
                data = json.loads(path.read_text())
                _files[path] = (signature, data)
            if data.get('version') == 1:
                groups.extend(data['groups'].values())
        except (OSError, ValueError, KeyError, TypeError):
            continue
    configured = {}
    for slave in slaves:
        name = slave.get('deviceName')
        if name:
            dev = configured.setdefault(name, {'slave': slave, 'tags': set(), 'period': 0})
            dev['tags'].update(t.get('tag') or t.get('key') for section in ('timeseries', 'attributes') for t in slave.get(section, []))
            dev['period'] = max(dev['period'], float(slave.get('pollPeriod', 60000)) / 1000)
    devices = []
    for name, config in configured.items():
        slave = config['slave']
        matching = [g for g in groups if g.get('name') == name and g.get('address') == slave.get('unitId')]
        seen = max((g.get('last_seen') or 0 for g in matching), default=0)
        polled = max((g.get('last_poll') or 0 for g in matching), default=0)
        # Allow two poll periods plus bus timeout/retry overhead; never infer a
        # physical unplug from a missing observer alone.
        stale_after = max(15, config['period'] * 2.5 + 10)
        recent = [g for g in matching if 0 <= now - g.get('last_poll', 0) <= stale_after]
        link = ('connected' if any(g.get('answered') for g in recent) else 'disconnected') if recent else 'pending'
        readings = {}
        for group in matching:
            for tag, reading in group.get('readings', {}).items():
                if tag in config['tags'] and reading.get('ts', 0) > readings.get(tag, {}).get('ts', 0):
                    readings[tag] = reading
        suffix = name.split('-')[-1].lower()
        model = slave.get('deviceType', '')
        role = 'temperature' if suffix.startswith('ts') or 'temperature' in model.lower() else 'meter'
        faults = [r for tag, r in readings.items() if tag == 'sensor_error' or tag.endswith('_error')]
        fresh_faults = [r for r in faults if now - r['ts'] <= stale_after]
        sensor_state = ('fault' if any(r['value'] != 0 for r in fresh_faults) else 'ok') if fresh_faults else 'unknown'
        devices.append({
            'key': name, 'name': name, 'label': label(suffix), 'model': model,
            'role': role, 'sensor_state': sensor_state if role == 'temperature' else None,
            'address': slave.get('unitId'), 'configured': True,
            'link': link, 'connected': link == 'connected',
            'status': 'ok' if link == 'connected' else 'error' if link == 'disconnected' else 'stale' if seen else 'no_report',
            'last_seen': iso(seen), 'last_poll': iso(polled), 'stale_after': stale_after,
            'readings': [{'tag': tag, 'value': r['value'], 'unit': unit(tag),
                          'last_seen': iso(r['ts']), 'stale': now - r['ts'] > stale_after}
                         for tag, r in readings.items()],
        })
    return devices, bool(groups)
