import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.modbus_config import ModbusConfig, PROFILES, validate_slaves


def device(name='kit-PF1', unit=88):
    return [dict(type='serial', method='rtu', port='/dev/meterbus', baudrate=9600,
                 bytesize=8, stopbits=1, parity='N', timeout=2, deviceName=name,
                 deviceType='P-Flow D116 GW', unitId=unit, pollPeriod=60000, **deepcopy(g)) for g in PROFILES['pflow']]


def setup(tmp_path):
    (tmp_path / 'tb_gateway.json').write_text(json.dumps({'connectors':[{'name':'RS485','type':'eco_modbus','configuration':'modbus.json'}]}))
    data = {'master':{'slaves':device()},'unrelated':{'keep':True}}
    (tmp_path / 'modbus.json').write_text(json.dumps(data))
    key = hashlib.sha256(b'modbus.json').hexdigest()[:16]
    (tmp_path / ('.eco-cloud-'+key+'.json')).write_text(json.dumps(data))
    return ModbusConfig(tmp_path,tmp_path), data


def test_temporary_edit_restore_and_concurrent_cloud_change(tmp_path):
    service, original = setup(tmp_path)
    state = service.state('RS485')
    changed = device(unit=80)
    updated = service.save('RS485',state['revision'],changed)
    assert updated['temporary'] and updated['configuration']['unrelated'] == {'keep':True}
    with pytest.raises(FileExistsError):
        service.save('RS485',state['revision'],changed)
    restored = service.save('RS485',updated['revision'],[],restore=True)
    assert not restored['temporary'] and restored['configuration'] == original
    changed = service.save('RS485',restored['revision'],changed)
    # A cloud replacement automatically invalidates the old override indicator.
    (tmp_path/'modbus.json').write_text(json.dumps(original))
    assert not service.state('RS485')['temporary']


def test_profiles_full_kit_and_registers():
    slaves = sum([device('PF'+str(i),80+i) for i in range(1,5)],[])
    for slot in range(2):
        slaves.append({**device()[0],**deepcopy(PROFILES['pt1000'][slot][0]),'deviceName':'TS'+str(slot+1),'unitId':255})
    validate_slaves(slaves,[])
    assert len(slaves)==10
    assert {g['wordOrder'] for g in slaves[:2]} == {'BIG','LITTLE'}
    assert slaves[-1]['timeseries'][1]['address']==7


@pytest.mark.parametrize('change',[{'unitId':0},{'pollPeriod':0},{'port':'../../etc/passwd'}, {'converter':'Evil'}, {'timeseries':[{'tag':'write','type':'16int','address':0,'objectsCount':1,'functionCode':6}]}])
def test_invalid_or_executable_config_rejected(change):
    bad=device();bad[0].update(change)
    with pytest.raises(ValueError):validate_slaves(bad,device())


def test_existing_manual_extension_preserved():
    old=device();old[0]['rpc']=[{'tag':'existing'}]
    validate_slaves(deepcopy(old),old)


def test_path_escape_rejected(tmp_path):
    service,_=setup(tmp_path)
    (tmp_path/'tb_gateway.json').write_text(json.dumps({'connectors':[{'type':'eco_modbus','name':'RS485','configuration':'../outside.json'}]}))
    with pytest.raises(ValueError):service.state('RS485')


def test_cloud_guard_preserves_observer_and_caches_only_applied_config(tmp_path, monkeypatch):
    import importlib.util
    import types
    base = types.ModuleType('thingsboard_gateway.connectors.modbus.modbus_connector')
    base.AsyncModbusConnector = type('Base', (), {})
    remote = types.ModuleType('thingsboard_gateway.tb_utility.tb_gateway_remote_configurator')
    class Remote:
        def _handle_connector_configuration_update(self, cfg):
            self.received = cfg
            if not self.fail:
                (tmp_path / cfg['configuration']).write_text(json.dumps(cfg['configurationJson']))
    remote.RemoteConfigurator = Remote
    monkeypatch.setitem(sys.modules,base.__name__,base)
    monkeypatch.setitem(sys.modules,remote.__name__,remote)
    monkeypatch.setitem(sys.modules,'fcntl',types.SimpleNamespace(flock=lambda *a:None,LOCK_EX=2))
    spec = importlib.util.spec_from_file_location('eco_guard_test',ROOT/'gateway/extensions/eco_modbus/live_modbus.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.install_configuration_guard(); module.install_configuration_guard()
    handler=Remote();handler._gateway=types.SimpleNamespace(get_config_path=lambda:str(tmp_path));handler.fail=False
    incoming={'type':'modbus','name':'RS485','configuration':'modbus.json','configurationJson':{'master':{'slaves':device()}}}
    handler._handle_connector_configuration_update(incoming)
    assert incoming['type']=='modbus'
    assert handler.received['type']=='eco_modbus' and handler.received['class']=='EcoModbusConnector'
    baseline=next(tmp_path.glob('.eco-cloud-*.json'))
    assert json.loads(baseline.read_text())==incoming['configurationJson']
    handler.fail=True
    incoming['configurationJson']['master']['slaves']=device(unit=80)
    handler._handle_connector_configuration_update(incoming)
    assert json.loads(baseline.read_text())['master']['slaves'][0]['unitId']==88


def test_duplicate_new_address_cannot_collide_with_unchanged_device():
    original=device()
    with pytest.raises(ValueError,match='share'):
        validate_slaves(original+device('PF2',88),original)


def test_config_api_requires_authentication_and_returns_conflict(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import modbus
    from app.security.auth import get_current_user
    from app.models.schemas import UserInfo
    service,_=setup(tmp_path)
    monkeypatch.setattr(modbus,'ModbusConfig',lambda _:service)
    monkeypatch.setattr(modbus,'log_audit',lambda *a,**kw:None)
    app=FastAPI();app.include_router(modbus.router,prefix='/api/modbus')
    with TestClient(app) as client:
        assert client.get('/api/modbus/config').status_code==401
        app.dependency_overrides[get_current_user]=lambda:UserInfo(username='test',role='admin')
        response=client.get('/api/modbus/config')
        assert response.status_code==200
        state=response.json()['connectors'][0]
        response=client.put('/api/modbus/config/RS485',json={'revision':state['revision'],'slaves':device(unit=80)})
        assert response.status_code==200 and response.json()['temporary']
        assert client.put('/api/modbus/config/RS485',json={'revision':state['revision'],'slaves':device()}).status_code==409
