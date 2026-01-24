# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-24)

**Core value:** System-Level-Konfiguration des IoT Gateways uber eine einfache Web-UI, ohne die ThingsBoard Gateway Config zu beruhren (MQTT-Sync vom Server)

**Current focus:** Phase 1 - NTP Configuration

## Current Position

Phase: 1 of 4 (NTP Configuration)
Plan: 1 of 3
Status: In progress
Last activity: 2026-01-24 - Completed 01-01-PLAN.md

Progress: [███░░░░░░░] 33%

## Accumulated Context

### Decisions

- chrony statt systemd-timesyncd fur NTP - Besser fur instabile LTE-Verbindungen
- Backup als tar.gz - Einfach, portabel, kein spezieller Client notig
- Failover via ip route - Keine zusatzliche Software notig, Standard-Linux
- SMS via AT-Commands - Quectel Modem bereits vorhanden
- _run_command wrapper for subprocess with sudo support (01-01)
- Cached timezone list for performance (01-01)
- Auto-include IoT-critical chrony settings: makestep 1 3, iburst, maxpoll 10 (01-01)

### Patterns Established

- Backend: FastAPI router in api/, service in services/
- Frontend: Vue component in views/, API in services/api.js
- Audit: All config changes logged via audit_service
- NTP: _run_command wrapper for subprocess with timeout and sudo support (01-01)

### Pending TODOs

None

### Blockers

None

## Session Continuity

Last session: 2026-01-24T10:45:28Z
Stopped at: Completed 01-01-PLAN.md
Resume file: None

## Phase 1 Plans

| Plan | Wave | Status | Description |
|------|------|--------|-------------|
| 01-01 | 1 | Complete | Backend NTP Service |
| 01-02 | 2 | Ready | Backend NTP API + Models |
| 01-03 | 3 | Ready | Frontend NTP View |
