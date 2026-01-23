# ECO-IOT-GW

IoT Gateway für Raspberry Pi (Pi4, Pi5, CM4) basierend auf ThingsBoard IoT Gateway.

## Features

- **Web-basiertes Konfigurationsinterface** (Vue.js 3 + Vuetify 3)
- **Docker-Compose Management** mit Drag&Drop Upload
- **VPN-Verbindung** (OpenVPN, WireGuard, Tailscale)
- **Modem-Konfiguration** (Quectel LTE/4G)
- **RS485-Konfiguration** für Modbus
- **WLAN Access Point** für Setup
- **Web-Terminal** (xterm.js)
- **Live-Diagnose** (Modbus-Werte aus Gateway-Logs)
- **Watchdog & Auto-Recovery**
- **NIS2-konforme Sicherheit**

## Systemanforderungen

- Raspberry Pi 4, Pi 5, oder Compute Module 4
- Raspberry Pi OS (Bookworm/Bullseye)
- Mindestens 2GB RAM
- 16GB SD-Karte oder größer
- Optionale Hardware:
  - Quectel LTE Modem (USB)
  - RS485 HAT oder USB-RS485 Adapter
  - WLAN-Adapter für Access Point

## Installation

```bash
# Repository klonen
git clone https://github.com/your-org/ECO-IOT-GW.git
cd ECO-IOT-GW

# Installation starten (als root)
sudo ./install/install.sh
```

Nach der Installation:
- Web-Interface: `https://<ip-adresse>`
- Standard-Benutzer: `admin`
- Passwort: Siehe `/etc/eco-iot-gw/secrets.env`

## Projektstruktur

```
ECO-IOT-GW/
├── install/                 # Installationsskripte
│   ├── install.sh          # Hauptinstallation
│   └── uninstall.sh        # Deinstallation
├── backend/                 # FastAPI Backend
│   ├── app/
│   │   ├── api/            # API Endpunkte
│   │   ├── services/       # Business Logic
│   │   ├── security/       # Auth, Crypto, Validators
│   │   └── models/         # Pydantic Models
│   └── requirements.txt
├── frontend/               # Vue.js Frontend
│   ├── src/
│   │   ├── views/          # Seiten-Komponenten
│   │   ├── services/       # API Services
│   │   └── router/         # Vue Router
│   └── package.json
├── config/                 # Konfigurationsdateien
│   ├── nginx/              # Nginx Reverse Proxy
│   ├── hostapd/            # WLAN AP
│   └── dnsmasq/            # DHCP
├── systemd/                # Systemd Services
├── updates/                # OTA Update Scripts
└── docker-compose.yml      # ThingsBoard Gateway
```

## API Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/api/auth/login` | POST | Login |
| `/api/auth/logout` | POST | Logout |
| `/api/docker/compose` | POST/GET | Docker-Compose hochladen/abrufen |
| `/api/docker/up` | POST | Container starten |
| `/api/docker/down` | POST | Container stoppen |
| `/api/terminal/ws` | WebSocket | Interaktive Shell |
| `/api/vpn/config` | POST/GET | VPN-Konfiguration |
| `/api/vpn/connect` | POST | VPN verbinden |
| `/api/vpn/disconnect` | POST | VPN trennen |
| `/api/modem/status` | GET | Modem-Status |
| `/api/modem/config` | GET/PUT | APN-Konfiguration |
| `/api/serial/config` | GET/PUT | RS485-Einstellungen |
| `/api/wifi/ap/status` | GET | AP-Status |
| `/api/diagnostics/modbus` | GET | Live-Modbus-Werte |
| `/api/watchdog/status` | GET | Watchdog-Status |
| `/api/system/status` | GET | System-Informationen |
| `/api/audit/logs` | GET | Audit-Protokoll |

## Sicherheit (NIS2-konform)

- JWT-Authentifizierung mit kurzlebigen Tokens
- Passwort-Hashing mit bcrypt (Kostenfaktor 12)
- AES-256 Verschlüsselung für sensible Daten
- Rate-Limiting und Brute-Force-Schutz
- Audit-Logging aller Konfigurationsänderungen
- HTTPS mit TLS 1.2/1.3
- Security Headers (CSP, X-Frame-Options, etc.)
- Fail2ban Integration
- Firewall (ufw) mit Whitelist

## WLAN Access Point

Der Access Point startet automatisch für die Erstkonfiguration:
- SSID: `ECO-IOT-GW-XXXX` (MAC-basiert)
- IP: `192.168.4.1`
- DHCP: `192.168.4.2 - 192.168.4.254`

## Entwicklung

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Deinstallation

```bash
sudo ./install/uninstall.sh
```

## Lizenz

MIT License

## Support

- GitHub Issues: [Link]
- Dokumentation: [Link]
