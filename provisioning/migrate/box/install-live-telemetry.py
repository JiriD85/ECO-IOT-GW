"""Install observer on an existing gateway, retaining its image/config/runtime settings.

Executed by tui.js on the kit during installation, never by preview or tests.
The previous container and configuration are retained for rollback.
"""
import copy
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time


LIVE = '/run/eco-telemetry'
EXT = '/thingsboard_gateway/extensions/eco_modbus'


def create_payload(old, extensions):
    if old['HostConfig']['NetworkMode'] != 'host':
        raise ValueError('Observer installer requires the provisioned host-network gateway')
    config = copy.deepcopy(old['Config'])
    allowed = ('Hostname', 'Domainname', 'User', 'AttachStdin', 'AttachStdout', 'AttachStderr',
               'ExposedPorts', 'Tty', 'OpenStdin', 'StdinOnce', 'Env', 'Cmd', 'Healthcheck',
               'ArgsEscaped', 'Volumes', 'WorkingDir', 'Entrypoint', 'NetworkDisabled',
               'MacAddress', 'OnBuild', 'Labels', 'StopSignal', 'StopTimeout', 'Shell')
    payload = {k: config[k] for k in allowed if k in config}
    payload['Image'] = old['Image']  # Exact installed image ID; never pull latest.
    host = copy.deepcopy(old['HostConfig'])
    if host.get('AutoRemove'):
        raise ValueError('Cannot retain rollback container with AutoRemove enabled')
    # Preserve devices, limits, privileges, restart policy and every unrelated bind.
    host['Binds'] = [b for b in host.get('Binds') or [] if b.split(':')[1] not in (LIVE, EXT)]
    host['Binds'] += [f'{LIVE}:{LIVE}', f'{extensions}:{EXT}:ro']
    bound = {b.split(':')[1] for b in host['Binds']}
    bound.update(m.get('Target') for m in host.get('Mounts') or [])
    for mount in old.get('Mounts', []):
        # Config.Volumes alone would allocate NEW anonymous volumes on recreation.
        if mount['Type'] == 'volume' and mount['Destination'] not in bound:
            host['Binds'].append(f"{mount['Name']}:{mount['Destination']}" + ('' if mount['RW'] else ':ro'))
    if any(m.get('Target') in (LIVE, EXT) for m in host.get('Mounts') or []):
        raise ValueError('Conflicting structured mount; manual migration required')
    payload['HostConfig'] = host
    return payload


class Engine(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


_API_VERSION = None


def request(method, path, body=None):
    global _API_VERSION
    if _API_VERSION is None:
        version = Engine('localhost', timeout=10)
        try:
            version.request('GET', '/version')
            _API_VERSION = json.loads(version.getresponse().read())['ApiVersion']
        finally:
            version.close()
    connection = Engine('localhost', timeout=90)
    try:
        connection.request(method, '/v' + _API_VERSION + path, json.dumps(body) if body is not None else None,
                           {'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = response.read()
        if response.status >= 300:
            raise RuntimeError(f'Docker {method} {path.split("?")[0]} failed ({response.status})')
        return json.loads(data) if data else None
    finally:
        connection.close()


def install(prepare_file, observer_file, root=Path('/')):
    old = request('GET', '/containers/tb-gateway/json')
    mount = next(m for m in old['Mounts'] if m['Destination'] == '/thingsboard_gateway/config')
    if mount['Type'] != 'bind':
        raise ValueError('Expected a host-bound configuration directory')
    config_dir = Path(mount['Source'])
    # Validate the pinned private hooks before changing configuration or stopping anything.
    subprocess.run(['docker', 'exec', 'tb-gateway', 'python3', '-c',
        'from thingsboard_gateway.connectors.modbus.modbus_connector import AsyncModbusConnector as C; '
        'assert hasattr(C,"_AsyncModbusConnector__poll_device"); '
        'assert hasattr(C,"_AsyncModbusConnector__read_slave_data")'], check=True)
    ids = subprocess.check_output(['docker', 'exec', 'tb-gateway', 'sh', '-c', 'id -u; id -g'], text=True).split()
    uid, gid = map(int, ids)
    # /run must be memory backed. Do not silently put live writes on the SD card.
    if subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '/run'], text=True).strip() != 'tmpfs':
        raise RuntimeError('/run must be tmpfs')
    runtime = root / LIVE.lstrip('/')
    runtime.mkdir(exist_ok=True, mode=0o750)
    os.chown(runtime, uid, gid)
    os.chmod(runtime, 0o750)
    (root / 'etc/tmpfiles.d/eco-telemetry.conf').write_text(f'd {LIVE} 0750 {uid} {gid} -\n')
    dropin = root / 'etc/systemd/system/docker.service.d'
    dropin.mkdir(parents=True, exist_ok=True)
    (dropin / 'eco-telemetry.conf').write_text('[Unit]\nAfter=systemd-tmpfiles-setup.service\n')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)

    spec = importlib.util.spec_from_file_location('prepare_live', prepare_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backup = config_dir.parent / ('pre-live-' + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    shutil.copytree(config_dir, backup / 'config')
    extensions = config_dir.parent / ('extensions-live-' + str(time.time_ns()))
    extensions.mkdir(mode=0o755)
    old_name = 'tb-gateway-pre-live-' + str(time.time_ns())
    renamed = False
    created = False
    try:
        with tempfile.TemporaryDirectory(dir=backup) as staging:
            staged = Path(staging) / 'config'
            shutil.copytree(config_dir, staged)
            module.prepare(staged, extensions, observer_file)
            payload = create_payload(old, str(extensions / 'eco_modbus'))
            (backup / 'container.json').write_text(json.dumps(old))
            request('POST', '/containers/tb-gateway/stop?t=30')
            request('POST', '/containers/tb-gateway/rename?name=' + old_name)
            renamed = True
            shutil.copytree(staged, config_dir, dirs_exist_ok=True)
            # The gateway writes accepted cloud updates and sidecar baselines.
            # copytree preserves modes but not ownership of newly staged files.
            os.chown(config_dir, uid, gid)
            for item in config_dir.rglob('*'):
                if not item.is_symlink():
                    os.chown(item, uid, gid)
            request('POST', '/containers/create?name=tb-gateway', payload)
            created = True
            request('POST', '/containers/tb-gateway/start')
            time.sleep(3)
            if not request('GET', '/containers/tb-gateway/json')['State']['Running']:
                raise RuntimeError('Updated gateway did not remain running')
        # A stopped rollback container must not restart after reboot.
        request('POST', '/containers/' + old_name + '/update', {'RestartPolicy': {'Name': 'no'}})
        print('Observer installed. Previous container:', old_name)
        print('Configuration and original container settings:', backup)
    except Exception:
        if created:
            request('DELETE', '/containers/tb-gateway?force=true')
        shutil.copytree(backup / 'config', config_dir, dirs_exist_ok=True)
        if renamed:
            request('POST', '/containers/' + old_name + '/rename?name=tb-gateway')
            request('POST', '/containers/tb-gateway/update', {'RestartPolicy': old['HostConfig']['RestartPolicy']})
        request('POST', '/containers/tb-gateway/start')
        raise


if __name__ == '__main__':
    install(*sys.argv[1:])
