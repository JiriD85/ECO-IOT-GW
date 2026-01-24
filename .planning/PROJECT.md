# Project: ECO-IOT-GW System Configuration

## Core Value
System-Level-Konfiguration des IoT Gateways uber eine einfache Web-UI, ohne die ThingsBoard Gateway Config zu beruhren (MQTT-Sync vom Server)

## Tech Stack

### Backend
- FastAPI 0.109+
- Python 3.11
- Pydantic for validation
- python-jose, bcrypt for auth
- pystemd, systemd-python for service management
- structlog for logging
- SQLite for audit logs

### Frontend
- Vue.js 3.4 (Composition API)
- Vuetify 3.5
- Pinia for state
- Axios for API calls
- Vite 5 for build

### Deployment
- Raspberry Pi (Pi4, Pi5, CM4)
- systemd services
- Nginx for frontend
- Docker for ThingsBoard Gateway

## Codebase Patterns

### Backend API Pattern
```
/api/{feature}/{action}
```
- Router in `backend/app/api/{feature}.py`
- Service in `backend/app/services/{feature}_service.py`
- Models in `backend/app/models/schemas.py`

### Service Pattern
```python
class FeatureService:
    def _run_command(self, cmd, sudo=False):
        # subprocess wrapper with audit logging
```

### Frontend Pattern
- Views in `frontend/src/views/{Feature}.vue`
- API helpers in `frontend/src/services/api.js`
- Routes in `frontend/src/router/index.js`

## Codebase Location
`./development/ECO-IOT-GW/`

## Key Decisions
- chrony statt systemd-timesyncd fur NTP (besser fur instabile LTE-Verbindungen)
- Backup als tar.gz (einfach, portabel)
- Failover via ip route (Standard-Linux)
- SMS via AT-Commands (Quectel Modem vorhanden)

## Critical Pitfalls to Address
1. Raspberry Pi Has No Battery-Backed RTC - After power loss, clock resets to 1970. Configure chrony with `makestep 1 3`
5. Chrony Fails to Sync on Intermittent LTE - Configure with `iburst`, `maxpoll 10`
10. NIS2 Compliance - Log all config changes with who/what/when, structured JSON logs
