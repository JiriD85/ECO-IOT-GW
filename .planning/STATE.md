# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-24)

**Core value:** System-Level-Konfiguration des IoT Gateways uber eine einfache Web-UI, ohne die ThingsBoard Gateway Config zu beruhren (MQTT-Sync vom Server)

**Current focus:** Phase 1 - NTP Configuration

## Current Position

Phase: 1 of 4 (NTP Configuration)
Plan: 0 of 3
Status: Planning complete, ready to execute
Last activity: 2026-01-24 - Phase 1 plans created

Progress: [░░░░░░░░░░] 0%

## Accumulated Context

### Decisions

- chrony statt systemd-timesyncd fur NTP - Besser fur instabile LTE-Verbindungen
- Backup als tar.gz - Einfach, portabel, kein spezieller Client notig
- Failover via ip route - Keine zusatzliche Software notig, Standard-Linux
- SMS via AT-Commands - Quectel Modem bereits vorhanden

### Patterns Established

- Backend: FastAPI router in api/, service in services/
- Frontend: Vue component in views/, API in services/api.js
- Audit: All config changes logged via audit_service

### Pending TODOs

None

### Blockers

None

## Phase 1 Plans

| Plan | Wave | Status | Description |
|------|------|--------|-------------|
| 01-01 | 1 | Ready | Backend NTP Service |
| 01-02 | 2 | Ready | Backend NTP API + Models |
| 01-03 | 3 | Ready | Frontend NTP View |
