import asyncio
import gzip
import importlib.util
import json
import sys
import types
from pathlib import Path
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.live_meters import read_snapshot
from app.services.meter_stream import difference, MeterStream
from app.services.meters_service import MetersService
from app.static_ui import CompressedStaticFiles, accepts_gzip
from app.security import tailscale_identity, auth
from app.api.meters import router


def slave(name='kit-PF1', **kw):
    return {'deviceName': name, 'deviceType': 'P-Flow', 'unitId': 1, 'pollPeriod': 5000,
            'timeseries': [{'tag': 'Vdot_m3h'}], **kw}


def group(name='kit-PF1', **kw):
    return {'name': name, 'address': 1, 'last_seen': 100, 'last_poll': 100, 'answered': True,
            'readings': {'Vdot_m3h': {'value': 0, 'ts': 100}}, **kw}


def write(tmp_path, groups):
    (tmp_path / 'test.json').write_text(json.dumps({'version': 1, 'groups': groups}))


def read(tmp_path, slaves=None, now=101):
    return read_snapshot(slaves or [slave()], lambda s: s, lambda s: '', tmp_path, now)[0]


def test_zero_reading_and_disconnect_reconnect(tmp_path):
    write(tmp_path, {'a': group()})
    assert read(tmp_path)[0]['readings'][0]['value'] == 0
    assert read(tmp_path)[0]['link'] == 'connected'
    write(tmp_path, {'a': group(last_poll=102, answered=False)})
    device = read(tmp_path, now=103)[0]
    assert device['link'] == 'disconnected'
    assert device['readings'][0]['value'] == 0
    write(tmp_path, {'a': group(last_poll=104, last_seen=104)})
    assert read(tmp_path, now=105)[0]['link'] == 'connected'


def test_stale_and_missing_observer_are_not_disconnection(tmp_path):
    assert read(tmp_path)[0]['link'] == 'pending'
    write(tmp_path, {'a': group()})
    device = read(tmp_path, now=200)[0]
    assert device['link'] == 'pending'
    assert device['status'] == 'stale'
    assert device['readings'][0]['stale']


def test_same_address_sensors_and_fault_register(tmp_path):
    sensors = [slave(f'kit-TS{i}', unitId=255, deviceType='Temperature Sensor', timeseries=[{'tag': f'auxT{i}_C'}, {'tag': f'auxT{i}_error'}]) for i in (1, 2)]
    write(tmp_path, {str(i): group(f'kit-TS{i}', address=255, readings={f'auxT{i}_C': {'value': i * 10, 'ts': 100}, f'auxT{i}_error': {'value': i - 1, 'ts': 100}}) for i in (1, 2)})
    devices = read(tmp_path, sensors)
    assert [d['sensor_state'] for d in devices] == ['ok', 'fault']
    assert devices[0]['readings'][0]['value'] == 10
    assert devices[1]['readings'][0]['value'] == 20


def test_full_kit_four_pflows_two_temperature_sensors(tmp_path):
    slaves, groups = [], {}
    for unit in range(1, 5):
        name = f'kit-PF{unit}'
        # Each physical P-Flow has separate float and integer word-order groups.
        for tag, order, value in [('Vdot_m3h', 'BIG', unit), ('V_m3', 'LITTLE', unit * 100)]:
            slaves.append(slave(name, unitId=unit, wordOrder=order, timeseries=[{'tag': tag}]))
            groups[f'{name}-{order}'] = group(name, address=unit, readings={tag: {'value': value, 'ts': 100}})
    for slot in (1, 2):
        name, tag = f'kit-TS{slot}', f'auxT{slot}_C'
        fault = f'auxT{slot}_error'
        slaves.append(slave(name, unitId=255, deviceType='Temperature Sensor', timeseries=[{'tag': tag}, {'tag': fault}]))
        groups[name] = group(name, address=255, readings={tag: {'value': 20 + slot, 'ts': 100}, fault: {'value': 0, 'ts': 100}})
    write(tmp_path, groups)
    devices = read(tmp_path, slaves)
    assert len(devices) == 6
    assert all(d['connected'] for d in devices)
    for unit in range(1, 5):
        meter = next(d for d in devices if d['name'] == f'kit-PF{unit}')
        assert {r['tag']: r['value'] for r in meter['readings']} == {'Vdot_m3h': unit, 'V_m3': unit * 100}
    assert [d['sensor_state'] for d in devices if d['role'] == 'temperature'] == ['ok', 'ok']


def test_partial_read_does_not_refresh_other_tags(tmp_path):
    write(tmp_path, {'a': group(readings={'Vdot_m3h': {'value': 1, 'ts': 50}, 'T_flow_C': {'value': 25, 'ts': 100}})})
    device = read(tmp_path, [slave(timeseries=[{'tag': 'Vdot_m3h'}, {'tag': 'T_flow_C'}])])[0]
    assert [r['stale'] for r in device['readings']] == [True, False]


def test_no_demo_devices_when_connectors_empty(tmp_path):
    (tmp_path / 'tb_gateway.json').write_text('{"connectors": []}')
    (tmp_path / 'demo.json').write_text(json.dumps({'master': {'slaves': [slave()]}}))
    assert MetersService()._load_slaves(tmp_path) == []


def test_transient_config_failure_retains_inventory(tmp_path, monkeypatch):
    config = tmp_path / 'tb_gateway.json'
    config.write_text(json.dumps({'connectors': [{'type': 'modbus', 'configuration': 'modbus.json'}]}))
    (tmp_path / 'modbus.json').write_text(json.dumps({'master': {'slaves': [slave()]}}))
    service = MetersService()
    service._fallback_config_dir = tmp_path
    monkeypatch.setattr(service, '_find_gateway_container', lambda: None)
    assert len(service.get_latest()['devices']) == 1
    config.unlink()
    service._config_at = service._cached_at = 0
    current = service.get_latest()
    assert len(current['devices']) == 1
    assert 'configuration unavailable' in current['notice']
    config.write_text('{"connectors": []}')
    service._config_at = service._cached_at = 0
    assert service.get_latest()['devices'] == []


def test_only_changed_devices_are_pushed():
    first = {'devices': [{'name': 'a', 'value': 1}, {'name': 'b', 'value': 2}], 'source': 'local', 'updated_at': 'x'}
    assert difference(first, {**first, 'updated_at': 'y'}) is None
    second = {**first, 'devices': [{'name': 'a', 'value': 3}]}
    delta = difference(first, second)
    assert delta['devices'] == [{'name': 'a', 'value': 3}]
    assert delta['removed'] == ['b']


def test_sample_timestamp_does_not_resend_unchanged_value():
    old = {'devices': [{'name': 'PF1', 'readings': [{'tag': 'flow', 'value': 0, 'unit': 'm3/h', 'last_seen': 'old'}]}], 'updated_at': 'old'}
    new = {'devices': [{'name': 'PF1', 'readings': [{'tag': 'flow', 'value': 0, 'unit': 'm3/h', 'last_seen': 'new'}]}], 'updated_at': 'new'}
    delta = difference(old, new)
    assert delta['devices'][0]['readings'] == [{'tag': 'flow', 'last_seen': 'new'}]


def test_local_staging_is_idempotent_and_preserves_poll_settings(tmp_path):
    spec = importlib.util.spec_from_file_location('prepare_live', ROOT / 'tools/prepare-live-telemetry.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    config = tmp_path / 'config'; config.mkdir()
    original = {'connectors': [{'name': 'RS485', 'type': 'modbus', 'configuration': 'modbus.json'}]}
    (config / 'tb_gateway.json').write_text(json.dumps(original))
    sensor = slave('kit-TS1', unitId=255, deviceType='Temperature Sensor', timeseries=[{'tag': 'auxT1_C', 'functionCode': 4, 'address': 0, 'divider': 10}])
    (config / 'modbus.json').write_text(json.dumps({'master': {'slaves': [sensor]}}))
    module.prepare(config, tmp_path / 'extensions')
    module.prepare(config, tmp_path / 'extensions')
    staged = json.loads((config / 'modbus.json').read_text())['master']['slaves'][0]
    assert staged['pollPeriod'] == 5000
    assert len(staged['timeseries']) == 2
    assert staged['timeseries'][1]['address'] == 6
    assert staged['timeseries'][1]['tag'] == 'auxT1_error'
    assert json.loads((config / 'tb_gateway.json.pre-live').read_text()) == original


def test_gzip_and_conditional_get(tmp_path):
    raw = b'const data = 42;' * 40
    (tmp_path / 'app-hash.js').write_bytes(raw)
    (tmp_path / 'app-hash.js.gz').write_bytes(gzip.compress(raw))
    app = FastAPI()
    app.mount('/assets', CompressedStaticFiles(directory=tmp_path))
    with TestClient(app) as client:
        response = client.get('/assets/app-hash.js', headers={'Accept-Encoding': 'gzip'})
        assert response.content == raw
        assert response.headers['content-encoding'] == 'gzip'
        assert 'javascript' in response.headers['content-type']
        assert client.get('/assets/app-hash.js', headers={'Accept-Encoding': 'gzip', 'If-None-Match': response.headers['etag']}).status_code == 304
        assert 'content-encoding' not in client.get('/assets/app-hash.js', headers={'Accept-Encoding': 'gzip;q=0'}).headers
    assert not accepts_gzip('br, gzip;q=0')


def test_peer_headers_cannot_spoof_tailnet(monkeypatch):
    request = types.SimpleNamespace(headers={'X-Real-IP': '100.127.1.1'}, client=types.SimpleNamespace(host='10.10.10.2'))
    assert tailscale_identity.identity_for_request(request) is None
    request.client.host = '100.127.1.1'
    monkeypatch.setattr(tailscale_identity, 'whois', lambda ip: None)
    assert tailscale_identity.identity_for_request(request) is None


@pytest.mark.parametrize('token', [None, 'garbage', auth.create_access_token({'sub': 'admin'}, timedelta(seconds=-5))])
def test_websocket_rejects_unauthenticated(token):
    app = FastAPI(); app.include_router(router, prefix='/api/meters')
    with TestClient(app) as client, client.websocket_connect('/api/meters/stream', headers={'Origin': 'http://testserver'}) as ws:
        ws.send_json({'token': token})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_websocket_rejects_cross_origin():
    app = FastAPI(); app.include_router(router, prefix='/api/meters')
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/meters/stream', headers={'Origin': 'http://evil.example'}):
            pass


def test_websocket_snapshot_and_authenticated_rest(monkeypatch):
    from app.services.meters_service import meters_service
    payload = {'devices': [], 'source': 'local_modbus', 'updated_at': 'x'}
    monkeypatch.setattr(meters_service, 'get_latest', lambda: payload)
    token = auth.create_access_token({'sub': 'admin'})
    app = FastAPI(); app.include_router(router, prefix='/api/meters')
    with TestClient(app) as client:
        assert client.get('/api/meters/latest').status_code == 401
        response = client.get('/api/meters/latest', headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 200
        assert client.get('/api/meters/latest', headers={'Authorization': f'Bearer {token}', 'If-None-Match': response.headers['etag']}).status_code == 304
        with client.websocket_connect('/api/meters/stream', headers={'Origin': 'http://testserver'}) as ws:
            ws.send_json({'token': token})
            assert ws.receive_json()['type'] == 'snapshot'


@pytest.mark.asyncio
async def test_one_watcher_bounded_queues(monkeypatch):
    from app.services.meters_service import meters_service
    monkeypatch.setattr(meters_service, 'get_latest', lambda: {'devices': [], 'updated_at': 'x'})
    hub = MeterStream()
    a = hub.subscribe(); task = hub.task; b = hub.subscribe()
    assert task is hub.task
    await asyncio.wait_for(a.get(), 2)
    assert b.qsize() == 1
    await hub.unsubscribe(a)
    assert hub.task is task
    await hub.unsubscribe(b)
    assert hub.task is None


def observer(monkeypatch):
    module = types.ModuleType('thingsboard_gateway.connectors.modbus.modbus_connector')
    class Base:
        def __init__(self, *args): pass
        async def _AsyncModbusConnector__read_slave_data(self, slave): return slave.result
        async def _AsyncModbusConnector__poll_device(self, slave):
            if not getattr(slave, 'unreachable', False):
                await self._AsyncModbusConnector__read_slave_data(slave)
    module.AsyncModbusConnector = Base
    monkeypatch.setitem(sys.modules, module.__name__, module)
    spec = importlib.util.spec_from_file_location('live_observer_test', ROOT / 'gateway/extensions/eco_modbus/live_modbus.py')
    loaded = importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)
    # This fixture isolates the read-boundary observer; cloud guard has separate tests.
    monkeypatch.setattr(loaded, 'install_configuration_guard', lambda: None)
    return loaded.EcoModbusConnector


@pytest.mark.asyncio
async def test_runtime_fixes_close_stale_serial_and_use_modern_decoder(monkeypatch):
    cls = observer(monkeypatch)
    loaded = sys.modules.get(cls.__module__)
    if loaded is None:
        spec = importlib.util.spec_from_file_location('live_runtime_test', ROOT / 'gateway/extensions/eco_modbus/live_modbus.py')
        loaded = importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)

    master_module = types.ModuleType('thingsboard_gateway.connectors.modbus.entities.master')
    converter_module = types.ModuleType('thingsboard_gateway.connectors.modbus.bytes_modbus_uplink_converter')
    mixin_module = types.ModuleType('pymodbus.client.mixin')

    class Master:
        async def connect(self):
            self.original_called = True

    class Converter:
        def decode_data(self, *_):
            return 'legacy'

    class DataTypes:
        INT16 = object(); UINT16 = object(); INT32 = object(); UINT32 = object()
        FLOAT32 = object(); INT64 = object(); UINT64 = object(); FLOAT64 = object()

    class Mixin:
        DATATYPE = DataTypes
        calls = []

        @classmethod
        def convert_from_registers(cls, registers, data_type, word_order='big'):
            cls.calls.append((registers, data_type, word_order))
            return 12.345678

    master_module.Master = Master
    converter_module.BytesModbusUplinkConverter = Converter
    mixin_module.ModbusClientMixin = Mixin
    monkeypatch.setitem(sys.modules, master_module.__name__, master_module)
    monkeypatch.setitem(sys.modules, converter_module.__name__, converter_module)
    monkeypatch.setitem(sys.modules, mixin_module.__name__, mixin_module)

    loaded.install_runtime_fixes()
    events = []

    class Client:
        connected = False
        def close(self): events.append('close')
        async def connect(self): events.append('connect'); self.connected = True

    master = Master(); master.client_type = 'serial'; master.lock = asyncio.Lock()
    master._Master__client = Client()
    await master.connect()
    assert events == ['close', 'connect']

    encoded = types.SimpleNamespace(registers=[0x1234, 0x5678])
    decoded = Converter().decode_data(encoded, {'functionCode': 3, 'type': '32float', 'objectsCount': 2,
                                                'round': 3, 'divider': 2}, 'LITTLE', 'LITTLE')
    assert decoded == 6.173
    assert Mixin.calls == [([0x3412, 0x7856], DataTypes.FLOAT32, 'little')]
    assert Converter().decode_data(encoded, {'functionCode': 3, 'type': 'string'}, 'BIG', 'BIG') == 'legacy'


@pytest.mark.asyncio
async def test_observer_decodes_before_cloud_and_retains_failures(tmp_path, monkeypatch):
    cls = observer(monkeypatch)
    monkeypatch.setenv('ECO_LIVE_DIR', str(tmp_path))
    (tmp_path / 'tb_gateway.json').write_text('{"connectors":[]}')
    obj = cls(types.SimpleNamespace(get_config_path=lambda: str(tmp_path)), {'name': 'test'}, 'eco_modbus')
    (tmp_path / 'tb_gateway.json').unlink()
    cfg = types.SimpleNamespace(device_type='P-Flow', telemetry=[{'tag': 'flow'}], attributes=[], byte_order='BIG', word_order='LITTLE')
    response = types.SimpleNamespace(isError=lambda: False)
    device = types.SimpleNamespace(device_name='PF1', unit_id=1, poll_period=5, uplink_converter_config=cfg, uplink_converter=types.SimpleNamespace(decode_data=lambda *args: 0), result={'telemetry': {'flow': response}})
    # No gateway/MQTT object exists: observation must still succeed.
    result = await obj._AsyncModbusConnector__read_slave_data(device)
    assert result is device.result
    data = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert next(iter(data['groups'].values()))['readings']['flow']['value'] == 0
    device.unreachable = True
    await obj._AsyncModbusConnector__poll_device(device)
    data = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert not next(iter(data['groups'].values()))['answered']
    # Bad observer destination must not interrupt upstream reads.
    obj._live_dir = tmp_path / 'file'; obj._live_dir.write_text('not a directory')
    assert await obj._AsyncModbusConnector__read_slave_data(device) is device.result
