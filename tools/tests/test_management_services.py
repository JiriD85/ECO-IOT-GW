import asyncio
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.backup_service import BackupService
from app.services.modem_service import ModemService
from app.services.watchdog_service import WatchdogService
from app.models.schemas import ModemConfig, WatchdogConfig


def test_watchdog_disabled_survives_reload(tmp_path, monkeypatch):
    from app.services import watchdog_service as module
    monkeypatch.setattr(module.settings, 'DATA_DIR', tmp_path)
    watchdog = WatchdogService()
    watchdog.set_enabled(False)
    reloaded = WatchdogService()
    reloaded.start()
    assert not reloaded._running
    assert not reloaded.get_config().enabled


def test_watchdog_uses_selected_vpn(tmp_path, monkeypatch):
    from app.config import settings
    for key in ['VPN_CONFIG_DIR', 'OPENVPN_CONFIG_DIR', 'WIREGUARD_CONFIG_DIR']:
        monkeypatch.setattr(settings, key, tmp_path / key)
    from app.services.vpn_service import vpn_service
    monkeypatch.setattr(vpn_service, 'get_status', lambda: SimpleNamespace(connected=True))
    monkeypatch.setattr(vpn_service, 'get_autostart', lambda: SimpleNamespace(enabled=True))
    watchdog = WatchdogService()
    monkeypatch.setattr(watchdog, '_check_gateway_container', lambda: True)
    monkeypatch.setattr(watchdog, '_check_modem', lambda: True)
    assert watchdog.get_status().services[0].running is True


def test_watchdog_stop_wakes_sleep_and_restarts_once(monkeypatch):
    import threading
    watchdog = WatchdogService()
    watchdog._config = WatchdogConfig(enabled=True, check_interval=600)
    checked = threading.Event()
    monkeypatch.setattr(watchdog, '_check_all', checked.set)
    watchdog.start()
    thread = watchdog._thread
    assert checked.wait(1)
    watchdog.stop()
    assert not thread.is_alive()
    watchdog.start()
    assert watchdog._thread is not thread
    watchdog.stop()


def test_modem_preserves_active_profile_and_masked_credentials(monkeypatch):
    modem = ModemService()
    calls = []
    def nm(args, timeout=15):
        calls.append(args)
        if args[:2] == ['-f', 'UUID,TYPE']:
            return 'existing-uuid:gsm'
        if '--show-secrets' in args:
            return 'metered.apn\nuser\nsecret\n1234\nyes'
        return ''
    monkeypatch.setattr(modem, '_nm', nm)
    monkeypatch.setattr(modem, '_save_config', lambda: None)
    modem.set_config(ModemConfig(apn='new.apn', username='user', password='********', pin='****'))
    writes = [c for c in calls if c[:2] == ['connection', 'modify']]
    assert len(writes) == 1
    assert writes[0][:4] == ['connection', 'modify', 'uuid', 'existing-uuid']
    assert writes[0][writes[0].index('gsm.password') + 1] == 'secret'
    assert writes[0][writes[0].index('gsm.pin') + 1] == '1234'
    assert not any('delete' in c or 'add' in c for c in calls)


def test_modem_ambiguous_profiles_fail_without_changes(monkeypatch):
    modem = ModemService()
    monkeypatch.setattr(modem, '_nm', lambda args: '' if '--active' in args else 'one:gsm\ntwo:gsm')
    with pytest.raises(RuntimeError, match='Multiple cellular'):
        modem._profile()


def test_modem_apply_failure_does_not_save(monkeypatch):
    modem = ModemService()
    monkeypatch.setattr(modem, 'get_config', lambda: ModemConfig(apn='old'))
    monkeypatch.setattr(modem, '_profile', lambda: 'uuid')
    monkeypatch.setattr(modem, '_nm', lambda args: (_ for _ in ()).throw(RuntimeError('failed')))
    monkeypatch.setattr(modem, '_save_config', lambda: pytest.fail('must not save failed configuration'))
    with pytest.raises(RuntimeError):
        modem.set_config(ModemConfig(apn='new'))


def archive(path, members):
    with tarfile.open(path, 'w:gz') as tar:
        for name, content in members.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            tar.addfile(entry, io.BytesIO(content))


def test_backup_roundtrip_in_temporary_root(tmp_path):
    service = BackupService(root=tmp_path / 'host', temp_dir=tmp_path)
    names = ['etc/eco-iot-gw/secrets.env', 'opt/eco/tb-gateway/config/tb_gateway.json',
             'var/lib/eco-iot-gw/branding/logo.svg', 'etc/NetworkManager/system-connections/lte.nmconnection']
    for name in names:
        path = service._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    result = service._create()
    assert set(result['manifest']['paths']) == set(names)
    for name in names:
        service._path(name).write_text('changed')
    restored = service._restore(result['backup_file'])
    assert restored['success']
    for name in names:
        assert service._path(name).read_text() == name


@pytest.mark.parametrize('name', ['../escape', '/etc/shadow', 'etc/shadow', 'etc/eco-iot-gw/../../shadow'])
def test_backup_rejects_outside_roots(tmp_path, name):
    service = BackupService(root=tmp_path / 'host', temp_dir=tmp_path)
    file = tmp_path / 'bad.tgz'
    archive(file, {'backup-manifest.json': b'{"version":"1.0"}', name: b'bad'})
    with pytest.raises(ValueError):
        service._restore(file)
    assert not service.root.exists()


def test_backup_checksum_failure_precedes_all_writes(tmp_path):
    service = BackupService(root=tmp_path / 'host', temp_dir=tmp_path)
    file = tmp_path / 'bad.tgz'
    archive(file, {'backup-manifest.json': b'{"version":"1.1","sha256":{}}',
                   'etc/eco-iot-gw/settings.json': b'changed'})
    with pytest.raises(ValueError, match='checksum'):
        service._restore(file)
    assert not service.root.exists()


def test_installer_preserves_container_runtime():
    spec = importlib.util.spec_from_file_location('live_install', ROOT / 'provisioning/migrate/box/install-live-telemetry.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = {'Image': 'sha256:pinned', 'Config': {'Image': 'mutable-tag', 'Env': ['KEEP=1'], 'User': '1000',
           'Cmd': ['run'], 'Labels': {'owner': 'kit'}}, 'HostConfig': {'NetworkMode': 'host',
           'Binds': ['/config:/thingsboard_gateway/config', '/logs:/thingsboard_gateway/logs'],
           'Devices': [{'PathOnHost': '/dev/serial/by-id/stable', 'PathInContainer': '/dev/meterbus'}],
           'RestartPolicy': {'Name': 'unless-stopped'}, 'Memory': 128000000},
           'Mounts': [{'Type': 'volume', 'Name': 'original-anonymous-volume',
                       'Destination': '/thingsboard_gateway/extensions', 'RW': True}]}
    result = module.create_payload(old, '/extensions/eco_modbus')
    assert result['Image'] == old['Image']
    for key in ['Env', 'User', 'Cmd', 'Labels']:
        assert result[key] == old['Config'][key]
    for key in ['Devices', 'RestartPolicy', 'Memory']:
        assert result['HostConfig'][key] == old['HostConfig'][key]
    assert set(old['HostConfig']['Binds']).issubset(result['HostConfig']['Binds'])
    assert '/run/eco-telemetry:/run/eco-telemetry' in result['HostConfig']['Binds']
    assert '/extensions/eco_modbus:/thingsboard_gateway/extensions/modbus:ro' in result['HostConfig']['Binds']
    assert 'original-anonymous-volume:/thingsboard_gateway/extensions' in result['HostConfig']['Binds']
    assert len(old['HostConfig']['Binds']) == 2


def test_connector_sync_records_requested_schema_version(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('connector_sync', ROOT / 'provisioning/migrate/box/connector-sync.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    monkeypatch.setattr(module.os, 'chown', lambda *_: None, raising=False)
    (tmp_path / 'tb_gateway.json').write_text(json.dumps({
        'connectors': [{'name': 'RS485', 'configuration': 'modbus.json'}]
    }))
    (tmp_path / 'modbus.json').write_text(json.dumps({'master': {'slaves': []}}))
    monkeypatch.setattr(sys, 'argv', ['connector-sync.py', 'complete', 'a0195300-90c4-11f1-8f56-1bdafa1b1051', '2'])
    module.main()
    assert json.loads((tmp_path / '.eco-sync.json').read_text())['version'] == 2


def test_thingsboard_save_preserves_observer_and_hidden_credentials(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, 'DATA_DIR', tmp_path)
    from app.services.thingsboard_service import ThingsBoardService
    from app.models.schemas import ThingsBoardConfig, ThingsBoardSecurityType
    service = ThingsBoardService()
    service._gateway_config_file = tmp_path / 'tb_gateway.json'
    active = {'thingsboard': {'host': 'old', 'port': 1883, 'security': {
        'type': 'usernamePassword', 'username': 'user', 'password': 'secret', 'clientId': 'kit'},
        'statistics': {'enableCustom': True}}, 'connectors': [{'type': 'eco_modbus'}],
        'storage': {'type': 'memory'}}
    service._gateway_config_file.write_text(json.dumps(active))
    service.save_config(ThingsBoardConfig(host='new', security_type=ThingsBoardSecurityType.USERNAME_PASSWORD))
    updated = json.loads(service._gateway_config_file.read_text())
    assert updated['thingsboard']['host'] == 'new'
    assert updated['thingsboard']['security'] == active['thingsboard']['security']
    assert updated['thingsboard']['statistics'] == active['thingsboard']['statistics']
    assert updated['connectors'] == active['connectors']
    assert updated['storage'] == active['storage']
    assert service.get_config().has_credentials


def test_gateway_start_never_regenerates_container(tmp_path, monkeypatch):
    from app.services import thingsboard_service as module
    commands = []
    monkeypatch.setattr(module.subprocess, 'run', lambda cmd, **kw: commands.append(cmd))
    assert module.thingsboard_service.deploy_gateway()['success']
    assert commands == [['docker', 'start', 'tb-gateway']]


def test_observer_install_rolls_back_config_when_create_fails(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('install_rollback', ROOT / 'provisioning/migrate/box/install-live-telemetry.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / 'gateway/config'
    config.mkdir(parents=True)
    gateway = {'thingsboard': {'security': {'type': 'accessToken', 'accessToken': 'unchanged'}},
               'connectors': [{'name': 'bus', 'type': 'modbus', 'configuration': 'modbus.json'}]}
    (config / 'tb_gateway.json').write_text(json.dumps(gateway))
    (config / 'modbus.json').write_text('{"master":{"slaves":[]}}')
    old = {'Image': 'sha256:installed', 'Config': {'Env': ['KEEP=1']},
           'HostConfig': {'NetworkMode': 'host', 'RestartPolicy': {'Name': 'unless-stopped'}},
           'Mounts': [{'Type': 'bind', 'Destination': '/thingsboard_gateway/config', 'Source': str(config)}]}
    calls = []
    def engine(method, path, body=None):
        calls.append((method, path))
        if method == 'GET':
            return old
        if path.startswith('/containers/create'):
            raise RuntimeError('simulated create failure')
    monkeypatch.setattr(module, 'request', engine)
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(module.subprocess, 'check_output', lambda args, **kwargs:
                        '0\n0' if args[0] == 'docker' else 'tmpfs')
    monkeypatch.setattr(module.os, 'chown', lambda *args: None, raising=False)
    (tmp_path / 'run').mkdir()
    (tmp_path / 'etc/tmpfiles.d').mkdir(parents=True)
    with pytest.raises(RuntimeError, match='simulated create failure'):
        module.install(ROOT / 'tools/prepare-live-telemetry.py',
                       ROOT / 'gateway/extensions/eco_modbus/live_modbus.py', root=tmp_path)
    assert json.loads((config / 'tb_gateway.json').read_text()) == gateway
    assert calls[-1] == ('POST', '/containers/tb-gateway/start')
    assert any('/rename?name=tb-gateway' in path for _, path in calls)
