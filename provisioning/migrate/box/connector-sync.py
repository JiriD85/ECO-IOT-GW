"""Installer-only bridge. JSON export is captured privately by tui.js, never logged."""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path('/opt/eco/tb-gateway/config')


def write(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.eco-sync-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=2)
            out.flush()
            os.fsync(out.fileno())
        owner = path.stat() if path.exists() else path.parent.stat()
        os.chmod(tmp, 0o660)
        os.chown(tmp, owner.st_uid, owner.st_gid)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def export(root=ROOT):
    root = root.resolve()
    config = json.loads((root / 'tb_gateway.json').read_text())
    files = {}
    for c in config['connectors']:
        p = (root / c['configuration']).resolve()
        if not p.is_relative_to(root) or p.name.startswith('.'):
            raise ValueError('Unsafe connector path')
        files[c['configuration']] = json.loads(p.read_text())
    logs = root / 'logs.json'
    return {'gateway': config, 'files': files, 'logs': json.loads(logs.read_text()) if logs.exists() else None}


def main():
    action = sys.argv[1]
    if action == 'export':
        print(json.dumps(export()))
    elif action in ('enable', 'disable'):
        p = ROOT / 'tb_gateway.json'
        cfg = json.loads(p.read_text())
        cfg['thingsboard']['remoteConfiguration'] = action == 'enable'
        write(p, cfg)
    elif action == 'complete':
        device_id = sys.argv[2]
        if len(device_id) != 36 or any(c not in '0123456789abcdef-' for c in device_id):
            raise ValueError('Invalid gateway id')
        data = export()
        for filename, config in data['files'].items():
            key = hashlib.sha256(filename.encode()).hexdigest()[:16]
            baseline = ROOT / ('.eco-cloud-' + key + '.json')
            # The remote guard has already cached accepted updates. Initial config
            # can be timestamp-skipped when byte-for-byte identical to local files.
            if not baseline.exists():
                write(baseline, config)
        write(ROOT / '.eco-sync.json', {'deviceId': device_id, 'version': 1})
    else:
        raise ValueError('Unknown action')


if __name__ == '__main__':
    main()
