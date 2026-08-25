# AGENTS.md

Konfiguration für den Multi-Agent Workflow mit Claude Code und OpenAI Codex CLI für ECO IoT Gateway.

## Workflow Übersicht

```
Claude Code (Planung) → Codex CLI (Umsetzung) → Claude Code (Review)
```

---

## Spezialisierte Agents

### 1. Backend Agent (`backend-agent`)

**Beschreibung:** Spezialist für FastAPI/Python Backend Development.

**Expertise:**
- FastAPI Routing und Dependency Injection
- Pydantic Models und Validation
- Async/Await Patterns
- JWT Authentication
- System Commands via subprocess
- Docker SDK Integration

**Projekt-Struktur:**
```
backend/
├── app/
│   ├── main.py              # FastAPI Entry Point
│   ├── config.py            # Pydantic Settings
│   ├── api/                 # FastAPI Routers
│   │   ├── auth.py
│   │   ├── docker.py
│   │   ├── vpn.py
│   │   ├── modem.py
│   │   ├── serial.py
│   │   └── system.py
│   ├── services/            # Business Logic
│   ├── security/            # Auth, Crypto, Rate Limiting
│   └── models/schemas.py    # Pydantic Models
```

**Codex Integration:**
```bash
source ~/.nvm/nvm.sh && nvm use 20
codex exec --approval-mode full-auto -q "Als backend-agent: [Aufgabe]"
```

---

### 2. Frontend Agent (`frontend-agent`)

**Beschreibung:** Spezialist für Vue.js 3 Frontend Development.

**Expertise:**
- Vue.js 3 Composition API
- Pinia State Management
- Vue Router mit Auth Guards
- Axios API Integration
- Responsive Design

**Projekt-Struktur:**
```
frontend/
├── src/
│   ├── views/              # Page Components
│   ├── components/         # Reusable Components
│   ├── services/
│   │   ├── api.js          # Axios Instance
│   │   └── auth.js         # Pinia Auth Store
│   ├── router/             # Vue Router Config
│   └── assets/
```

**Codex Integration:**
```bash
source ~/.nvm/nvm.sh && nvm use 20
codex exec --approval-mode full-auto -q "Als frontend-agent: [Aufgabe]"
```

---

### 3. DevOps Agent (`devops-agent`)

**Beschreibung:** Spezialist für Deployment und System-Administration.

**Expertise:**
- Docker und Docker Compose
- Systemd Service Management
- Nginx Konfiguration
- Raspberry Pi Specifics
- VPN (OpenVPN, WireGuard)
- LTE Modem Konfiguration

**Deployment Pfade:**
| Component | Path |
|-----------|------|
| Backend | `/opt/eco-iot-gw/backend/` |
| Frontend | `/var/www/eco-iot-gw/` |
| Config | `/etc/eco-iot-gw/secrets.env` |
| Logs | `/var/log/eco-iot-gw/` |

**Systemd Services:**
- `eco-iot-gw-backend.service` - Uvicorn Server
- `thingsboard-gateway` - ThingsBoard Gateway

**Codex Integration:**
```bash
source ~/.nvm/nvm.sh && nvm use 20
codex exec --approval-mode full-auto -q "Als devops-agent: [Aufgabe]"
```

---

## Remote Deployment

### SSH Verbindung
```bash
# Host: 192.168.1.69
# User: pi
# Credentials: export PI_USER / PI_HOST / PI_PASSWORD from .env.local

sshpass -p "$PI_PASSWORD" ssh -o StrictHostKeyChecking=no "$PI_USER@$PI_HOST" '[COMMAND]'
```

### Häufige Befehle
```bash
# Service Status
sudo systemctl status eco-iot-gw-backend

# Service Restart
sudo systemctl restart eco-iot-gw-backend

# Logs
sudo journalctl -u eco-iot-gw-backend -n 50 --no-pager

# Gateway Status
sudo systemctl status thingsboard-gateway
```

---

## Task-Spezifikation Format

```markdown
# Task: [Name]

## Beschreibung
[Was soll erreicht werden?]

## Agent
[backend-agent | frontend-agent | devops-agent]

## Betroffene Dateien
- `backend/app/api/...`
- `frontend/src/views/...`

## Akzeptanzkriterien
- [ ] Kriterium 1
- [ ] Kriterium 2

## Tests
- Unit Test: ...
- Integration Test: ...
```
