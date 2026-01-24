# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-24)

**Core value:** System-Level-Konfiguration des IoT Gateways uber eine einfache Web-UI, ohne die ThingsBoard Gateway Config zu beruhren (MQTT-Sync vom Server)

**Current focus:** Phase 2 - Backup & Restore

## Current Position

Phase: 1 of 4 (NTP Configuration) - COMPLETE
Plan: 3 of 3
Status: Phase 1 complete, ready for Phase 2
Last activity: 2026-01-24 - Phase 1 deployed and verified on gateway

Progress: [██████████] 100%

## Accumulated Context

### Decisions

- chrony statt systemd-timesyncd fur NTP - Besser fur instabile LTE-Verbindungen
- Backup als tar.gz - Einfach, portabel, kein spezieller Client notig
- Failover via ip route - Keine zusatzliche Software notig, Standard-Linux
- SMS via AT-Commands - Quectel Modem bereits vorhanden
- _run_command wrapper for subprocess with sudo support (01-01)
- Cached timezone list for performance (01-01)
- Auto-include IoT-critical chrony settings: makestep 1 3, iburst, maxpoll 10 (01-01)
- PUT /timezone accessible to all authenticated users (not admin-only) for user preference (01-02)
- Added POST /restart endpoint for explicit chrony service restart (01-02)
- TimezoneRequest model for body-based timezone updates (01-02)

### Patterns Established

- Backend: FastAPI router in api/, service in services/
- Frontend: Vue component in views/, API in services/api.js
- Audit: All config changes logged via audit_service
- NTP: _run_command wrapper for subprocess with timeout and sudo support (01-01)
- NTP API routes at /api/ntp/* following existing router patterns (01-02)
- Config changes require admin role, status/read operations require any authenticated user (01-02)
- Frontend: ntpApi object pattern in api.js for API grouping (01-03)
- Frontend: v-autocomplete for searchable dropdowns like timezone (01-03)
- Deploy: Single SSH session with tar pipe to avoid fail2ban lockout

### Pending TODOs

None

### Blockers

None

## Session Continuity

Last session: 2026-01-24T12:05:00Z
Stopped at: Phase 1 complete - deployed and verified on gateway
Resume file: None
Next: /gsd:plan-phase 2 for Backup & Restore

## Phase 1 Plans

| Plan | Wave | Status | Description |
|------|------|--------|-------------|
| 01-01 | 1 | Complete | Backend NTP Service |
| 01-02 | 2 | Complete | Backend NTP API + Models |
| 01-03 | 3 | Complete | Frontend NTP View |
