# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ECO-IOT-GW is an IoT Gateway management system for Raspberry Pi (Pi4, Pi5, CM4) designed to work with ThingsBoard IoT Gateway. It provides a web interface for configuring VPN connections, LTE modems, RS485/Modbus, Docker containers, and system settings.

## READ FIRST when working on gateway/Modbus/ThingsBoard configuration

**[docs/KNOWLEDGE_BASE.md](docs/KNOWLEDGE_BASE.md)** is the consolidated operational reference
(telemetry worlds, register map, LTE/modem, WAN model, migration, web console, known issues).
[docs/RESI_MIGRATION.md](docs/RESI_MIGRATION.md) has the RESI unit analysis + full register map.
Facts that are not derivable from this codebase and silently corrupt data / break connectivity
if guessed:

- The MQTT endpoint is `lb-mqtt.pke-iot.expert` (1883 plain / 8883 TLS), **not** the
  ThingsBoard REST host.
- The P-Flow D116 is **mixed-endian** — each meter needs two slave entries.
- Its totals are **mantissa + exponent**, so a constant divider is only conditionally right.
- The temperature sensors (`TS1`/`TS2`) are **PT1000 RTDs on the C4's onboard AIOX**, read as
  **Modbus unit 255, FC04 (input registers)** on the **same external meter bus** as the P-Flows
  (slot 0 = TS1, slot 1 = TS2; **degC = int16 / 10**). *(This supersedes an earlier
  unitId-1 / internal-port / regs 41064-41079 / ×100 guess — that was never how the firmware
  read temps.)*
- The LTE modem is a **Quectel EC25** (QMI/`cdc-wdm0`), driven via **ModemManager (`mmcli`) + a
  NetworkManager GSM connection** (APN `wsim`), **not** raw AT. *(An earlier "Cinterion" note
  was wrong.)*
- Child device names must match `ECO_<HWID>_PF1..PF4` / `_TS1..TS2` / `_gw` exactly, with
  the HWID **inherited** from the RESI unit being replaced.

Provisioning workflow for new gateways: [provisioning/README.md](provisioning/README.md).

## Build & Development Commands

### Backend (FastAPI/Python)
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Development server (with reload)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Run tests
pytest
pytest tests/test_auth.py -v              # Single test file
pytest -k "test_login" -v                 # Tests matching pattern
pytest --cov=app                          # With coverage
```

### Frontend (Vue.js 3 / Vuetify 3)
```bash
cd frontend
npm install

# Development server (port 3000, proxies /api to backend)
npm run dev

# Production build
npm run build

# Lint with auto-fix
npm run lint
```

### Full Installation on Raspberry Pi
```bash
sudo ./install/install.sh
sudo ./install/uninstall.sh              # Uninstall
```

## Architecture

### Backend (`backend/app/`)

- **`main.py`**: FastAPI entry point with lifespan management, middleware (CORS, security headers, request logging), router registration
- **`config.py`**: Pydantic settings loaded from `/etc/eco-iot-gw/secrets.env` (production) or environment vars (dev)
- **`api/`**: FastAPI routers - each file is a feature module (auth, docker, vpn, modem, serial, wifi, system, terminal, diagnostics, watchdog, audit, thingsboard)
- **`services/`**: Business logic layer - services handle system interactions (subprocess, Docker SDK, pyserial, AT commands)
- **`security/`**: Authentication (JWT with bcrypt), crypto (AES-256), rate limiting, input validators
- **`models/schemas.py`**: Pydantic models for request/response validation

### Frontend (`frontend/src/`)

- **`views/`**: Page components (Login, Dashboard, VpnConfig, DockerManager, ThingsboardConfig, Terminal, etc.)
- **`services/api.js`**: Axios instance with automatic token refresh interceptors
- **`services/auth.js`**: Pinia store for authentication state
- **`composables/`**: Reusable composition functions (useGatewayStatus, useSnackbar, etc.)
- **`router/`**: Vue Router with auth guards (redirects unauthenticated users to /login)

### Key Integration Patterns

1. **Service Layer**: API routes in `api/*.py` call corresponding services in `services/*.py`. Services handle system interactions.

2. **Sudo Commands**: The `eco-iot-gw` user has limited sudo permissions via `/etc/sudoers.d/eco-iot-gw`. Services use `_run_command(cmd, sudo=True)` for privileged operations.

3. **WebSocket Terminal**: `terminal.py` creates a PTY shell session, streams I/O over WebSocket to xterm.js frontend.

4. **Audit Logging**: All configuration changes logged to SQLite at `/var/lib/eco-iot-gw/audit/audit.db` via `audit_service.py`.

5. **Gateway Status State Machine**: ThingsBoard gateway status uses states: UNKNOWN → STARTING → CONNECTED ↔ DISCONNECTED → STOPPED/ERROR. Includes caching (30s TTL) and circuit breaker.

### Deployment Paths

| Component | Development | Production |
|-----------|-------------|------------|
| Backend | `localhost:8000` | `/opt/eco-iot-gw/backend/` via systemd |
| Frontend | `localhost:3000` | `/var/www/eco-iot-gw/` served by Nginx |
| Config | Environment vars / `.env.local` | `/etc/eco-iot-gw/secrets.env` |
| Logs | Console | `/var/log/eco-iot-gw/` |
| Data | Local | `/var/lib/eco-iot-gw/` |

## Remote Deployment (Raspberry Pi)

```bash
# SSH connection. Credentials live in .env.local (gitignored) - export them first:
#   export PI_USER=pi PI_HOST=<ip> PI_PASSWORD=<password>
sshpass -p "$PI_PASSWORD" ssh -o StrictHostKeyChecking=no "$PI_USER@$PI_HOST" '[COMMAND]'

# Deploy frontend
cd frontend && npm run build
sshpass -p "$PI_PASSWORD" scp -r dist/* "$PI_USER@$PI_HOST":/tmp/frontend-dist/
sshpass -p "$PI_PASSWORD" ssh "$PI_USER@$PI_HOST" 'sudo cp -r /tmp/frontend-dist/* /var/www/eco-iot-gw/'

# Deploy backend
sshpass -p "$PI_PASSWORD" scp backend/app/*.py "$PI_USER@$PI_HOST":/tmp/backend/
sshpass -p "$PI_PASSWORD" ssh "$PI_USER@$PI_HOST" 'sudo cp -r /tmp/backend/* /opt/eco-iot-gw/backend/app/'
sshpass -p "$PI_PASSWORD" ssh "$PI_USER@$PI_HOST" 'sudo systemctl restart eco-iot-gw-backend'

# Check service status
sshpass -p "$PI_PASSWORD" ssh "$PI_USER@$PI_HOST" 'sudo systemctl status eco-iot-gw-backend'
sshpass -p "$PI_PASSWORD" ssh "$PI_USER@$PI_HOST" 'sudo journalctl -u eco-iot-gw-backend -n 50 --no-pager'
```

## Configuration Notes

- **JWT tokens**: Access expires in 15 minutes, refresh in 7 days
- **Rate limiting**: 100 requests/60 seconds, login lockout after 5 failed attempts (15 min)
- **VPN configs**: OpenVPN (644 permissions), WireGuard (600 permissions), owned by root
- **ThingsBoard Gateway**: Docker container, config at `/etc/thingsboard-gateway/config/`

## Tech Stack

- **Backend**: FastAPI 0.109+, Python 3.11, Uvicorn, pydantic, python-jose, bcrypt, docker-py, pyserial
- **Frontend**: Vue.js 3.4 (Composition API), Pinia, Vue Router, Vuetify 3.5, Vite 5, Axios, xterm.js
- **Deployment**: Docker, systemd, Nginx, SQLite (audit), Raspberry Pi OS

## Custom Skills (Claude Code)

The project uses custom skills defined in `~/.claude/skills/`:
- `/commit` - Git commit with auto-generated conventional message
- `/ssh` - SSH to IoT Gateway for status checks and debugging
- `/tbsync` - Sync ThingsBoard dashboards/widgets/i18n to server
- `/tbpull` - Pull ThingsBoard assets from server
- `/deploy` - Full deployment workflow (tbsync + commit + push)
- `/validate` - Validate JSON/JS/i18n files
- `/uitest` - Browser UI testing with screenshots/GIFs
