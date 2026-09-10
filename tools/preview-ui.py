"""UI preview (loopback by default, optional network binding) with simulated meters. Never connects to hardware.

Build frontend first; run with backend/.venv/Scripts/python tools/preview-ui.py.
"""
import math
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.api.meters import router
from app.security.auth import get_current_user
from app.models.schemas import UserInfo
from app.services.meters_service import meters_service
from app.security import tailscale_identity
from app.static_ui import CompressedStaticFiles


PREVIEW_START = int(time.time() / 60) * 60

def sample():
    now = int(time.time() / 60) * 60
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
    devices = []
    for i, name in enumerate(['PF1', 'PF2', 'TS1', 'TS2']):
        temp = name.startswith('TS')
        readings = ([('auxT1_C', round(23.4 + 0.2 * math.sin(now / 600 + i), 2), '°C')] if temp else [('Vdot_m3h', round(1.3 + math.sin(now / 600) / 10, 3), 'm³/h'), ('T_flow_C', round(48.6 + 0.3 * math.sin(now / 600), 2), '°C'), ('T_return_C', round(36.2 + 0.2 * math.sin(now / 600 - 0.5), 2), '°C'), ('V_m3', round(1458.9 + max(0, now - PREVIEW_START) * 1.3 / 3600, 3), 'm³')])
        devices.append({'name': f'DEMO-{name}', 'label': ('Temperature ' if temp else 'P-Flow ') + name[-1], 'key': name,
                        'model': 'AIOX RTD' if temp else 'P-Flow D116', 'address': 255 if temp else i + 1,
                        'role': 'temperature' if temp else 'meter', 'configured': True,
                        'link': 'disconnected' if i == 1 else 'connected', 'connected': i != 1,
                        'status': 'error' if i == 1 else 'ok', 'last_poll': stamp, 'last_seen': stamp,
                        'sensor_state': 'ok' if temp else None, 'stale_after': 160,
                        'readings': [] if i == 1 else [{'tag': k, 'value': v, 'unit': u, 'last_seen': stamp, 'stale': False} for k, v, u in readings]})
    return {'devices': devices, 'source': 'local_modbus', 'updated_at': stamp,
            'notice': 'LOCAL PREVIEW · Simulated readings every 60s. This page does not connect to your hardware.',
            'connector': {'name': 'RS485 Modbus', 'serial_port': '/dev/meterbus', 'baudrate': 9600, 'running': True}}


app = FastAPI()
app.dependency_overrides[get_current_user] = lambda: UserInfo(username='Local preview', role='admin')
meters_service.get_latest = sample
tailscale_identity.identity_for_request = lambda request: 'preview@example.invalid'
app.include_router(router, prefix='/api/meters')


@app.get('/api/auth/whoami')
def whoami():
    return {'authenticated': True, 'identity': 'Local preview', 'method': 'tailscale'}


@app.get('/api/branding/config')
def branding():
    return {'kit_name': 'ECO Gateway', 'theme': 'light'}


@app.get('/api/auth/me')
def me():
    return {'username': 'Local preview', 'role': 'admin'}


@app.get('/api/system/status')
def system():
    return {'hostname': 'preview-kit', 'uptime': 3600, 'cpu_percent': 18.2, 'memory_percent': 34.6, 'memory_total': 1000000000, 'memory_used': 346000000, 'disk_percent': 22.8, 'temperature': 46.1}


@app.get('/api/{path:path}')
def api_placeholder(path: str):
    fixtures = {
        'serial/ports': [{'device': '/dev/meterbus', 'description': 'Simulated RS485'}],
        'serial/config': {'port': '/dev/meterbus', 'baudrate': 9600, 'bytesize': 8, 'parity': 'N', 'stopbits': 1, 'timeout': 1},
        'docker/status': {'containers': [], 'compose_running': False},
        'docker/compose': {'content': '# Local preview: no containers are controlled.'},
        'ntp/sources': [], 'ntp/status': {'synchronized': False},
        'ntp/config': {'servers': [], 'pools': []},
        'ntp/timezones': {'available': ['Europe/Vienna', 'UTC'], 'current': 'Europe/Vienna'},
        'ntp/timezone': {'timezone': 'Europe/Vienna'},
        'audit/logs': [], 'audit/stats': {'total': 0, 'by_action': {}},
        'diagnostics/modbus': [], 'diagnostics/gateway/logs': [],
        'diagnostics/gateway/status': {'running': False, 'container_name': 'Preview only'},
        'diagnostics/connectivity': {'internet': False, 'dns': False, 'thingsboard': False},
        'thingsboard/devices': [], 'thingsboard/config': {'configured': False},
        'thingsboard/status': {'connected': False},
        'thingsboard/gateway/status': {'running': False},
        'thingsboard/gateway-status': {'state': 'stopped', 'container': {'running': False, 'status': 'Preview'}, 'mqtt_connected': False},
        'thingsboard/gateway/logs': {'success': True, 'logs': 'Local preview: no gateway logs.'},
        'vpn/status': {'connected': False}, 'vpn/type': {'vpn_type': 'wireguard'},
        'vpn/autostart': {'enabled': False}, 'vpn/config': {'configured': False},
        'modem/status': {'connected': False, 'detected': False}, 'modem/config': {'apn': '', 'enabled': False},
        'network/status': {'interfaces': [], 'active_interface': None},
        'network/failover/config': {'enabled': False, 'priority': []},
        'watchdog/status': {'enabled': False}, 'watchdog/config': {'enabled': False},
        'system/update/status': {'current_version': 'Local preview', 'update_available': False},
        'sms/config': {'enabled': False, 'recipients': [], 'triggers': {}}, 'sms/triggers': [],
    }
    if path in fixtures:
        return fixtures[path]
    raise HTTPException(501, 'This endpoint is not simulated in the local preview.')


@app.api_route('/api/{path:path}', methods=['POST', 'PUT', 'DELETE', 'PATCH'])
def preview_action(path: str):
    raise HTTPException(501, 'Local preview only: changes and hardware actions are unavailable.')


@app.websocket('/api/terminal/ws')
async def preview_terminal(ws: WebSocket):
    await ws.accept()
    await ws.send_text('LOCAL PREVIEW — no hardware shell connected. Commands are not executed.\r\n')
    try:
        while True:
            message = await ws.receive_text()
            if 'resize' not in message:
                await ws.send_text('\r\nPreview only: commands are disabled.\r\n')
    except WebSocketDisconnect:
        pass


dist = ROOT / 'frontend/dist'
app.mount('/assets', CompressedStaticFiles(directory=dist / 'assets'))


@app.middleware('http')
async def caching(request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if request.url.path.startswith('/assets/') else 'no-cache'
    return response


@app.get('/{path:path}')
def index(path: str):
    return HTMLResponse((dist / 'index.html').read_text(encoding='utf-8').replace('<body>', '<body><div style="padding:8px 18px;background:#302611;color:#ffe0a0;font:12px system-ui">LOCAL PREVIEW · Administrator session · Hardware actions are disabled.</div>'))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=4173)
