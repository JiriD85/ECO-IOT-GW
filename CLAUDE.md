# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ECO-IOT-GW is an IoT Gateway management system for Raspberry Pi (Pi4, Pi5, CM4) designed to work with ThingsBoard IoT Gateway. It provides a web interface for configuring VPN connections, LTE modems, RS485/Modbus, Docker containers, and system settings.

## Build & Development Commands

### Backend (FastAPI/Python)
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Run tests
pytest
pytest tests/test_auth.py -v              # Single test file
pytest -k "test_login" -v                 # Tests matching pattern
```

### Frontend (Vue.js 3)
```bash
cd frontend
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Lint
npm run lint
```

### Full Installation on Raspberry Pi
```bash
sudo ./install/install.sh
```

## Architecture

### Backend Structure (`backend/app/`)

- **`main.py`**: FastAPI application entry point with lifespan management, middleware (CORS, security headers, request logging), and router registration
- **`config.py`**: Pydantic settings loaded from `/etc/eco-iot-gw/secrets.env`
- **`api/`**: FastAPI routers - each file corresponds to a feature (auth, docker, vpn, modem, serial, wifi, system, diagnostics, watchdog, audit, terminal)
- **`services/`**: Business logic layer - services interact with system commands, Docker SDK, serial ports, etc.
- **`security/`**: Authentication (JWT with bcrypt), crypto (AES-256), rate limiting, input validators
- **`models/schemas.py`**: Pydantic models for request/response validation

### Frontend Structure (`frontend/src/`)

- **`views/`**: Page components (Login, Dashboard, VpnConfig, DockerManager, Terminal, etc.)
- **`services/api.js`**: Axios instance with automatic token refresh and API helper functions
- **`services/auth.js`**: Pinia store for authentication state
- **`router/`**: Vue Router configuration with auth guards

### Key Integration Patterns

1. **Service Layer**: API routes in `api/*.py` call corresponding services in `services/*.py`. Services handle system interactions (subprocess calls, Docker SDK, pyserial).

2. **Sudo Commands**: The `eco-iot-gw` user runs with limited sudo permissions defined in `/etc/sudoers.d/eco-iot-gw`. Service code uses `sudo=True` parameter in `_run_command()` for privileged operations.

3. **VPN Config Flow**: Files uploaded via API → saved to `/etc/openvpn/client/` or `/etc/wireguard/` → ownership changed to root via sudo → systemd service started.

4. **WebSocket Terminal**: `terminal.py` creates a PTY shell session, streams I/O over WebSocket to xterm.js frontend.

5. **Audit Logging**: All configuration changes are logged to SQLite at `/var/lib/eco-iot-gw/audit/audit.db` via `audit_service.py`.

### Deployment Paths

| Component | Development | Production |
|-----------|-------------|------------|
| Backend | `localhost:8000` | `/opt/eco-iot-gw/backend/` via systemd |
| Frontend | `localhost:5173` | `/var/www/eco-iot-gw/` served by Nginx |
| Config | Environment vars | `/etc/eco-iot-gw/secrets.env` |
| Logs | Console | `/var/log/eco-iot-gw/` |

### Systemd Services

- `eco-iot-gw-backend.service`: Uvicorn server (runs as `eco-iot-gw` user)
- Nginx reverse proxy handles HTTPS termination and serves static frontend

## Important Configuration Notes

- JWT tokens expire in 15 minutes; refresh tokens last 7 days
- VPN config files must be owned by root with correct permissions (644 for OpenVPN, 600 for WireGuard)
- The systemd watchdog is disabled in the service file - the app has its own internal watchdog
- `ReadWritePaths` in systemd unit must include all config directories the app writes to
