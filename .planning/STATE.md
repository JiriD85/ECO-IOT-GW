# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-24)

**Core value:** System-Level-Konfiguration des IoT Gateways uber eine einfache Web-UI, ohne die ThingsBoard Gateway Config zu beruhren (MQTT-Sync vom Server)

**Current focus:** Phase 2 - Backup & Restore

## Current Position

Phase: 2 of 4 (Backup & Restore)
Plan: 3 of 3
Status: Phase complete
Last activity: 2026-01-24 - Completed 02-03-PLAN.md (Frontend Backup View)

Progress: [██████████████████] 50%

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
- tar.gz with PAX_FORMAT for broad compatibility and large file support (02-01)
- Manifest version 1.0 as first member for fast validation (02-01)
- Two-pass extraction: validate all members before extracting any (02-01)
- WireGuard configs get 600, OpenVPN configs get 644 permissions (02-01)
- 8KB chunk size for memory-efficient streaming upload (02-02)
- NamedTemporaryFile with delete=False for manual cleanup control (02-02)
- require_admin helper function for consistent admin checks (02-02)
- Require validation before enabling restore button (02-03)
- Show manifest info (created_at, hostname, app_version) after validation (02-03)
- Confirmation dialog for restore to prevent accidental overwrites (02-03)

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
- Backup: Security validation before extraction - absolute paths, path traversal, symlinks (02-01)
- Backup: Audit logging for both create and restore with success/failure tracking (02-01)
- FileResponse for binary file downloads with Content-Disposition header (02-02)
- Streaming UploadFile with chunk-based reading for large files (02-02)
- Temp file cleanup in finally block ensures cleanup on exception (02-02)
- Blob download with Content-Disposition filename extraction (02-03)
- File upload with v-file-input and FormData (02-03)
- Validation-before-restore workflow pattern (02-03)
- Confirmation dialog for destructive operations (02-03)
- backupApi pattern: blob responseType for downloads, FormData for uploads (02-03)

### Pending TODOs

None

### Blockers

None

## Session Continuity

Last session: 2026-01-24T12:42:00Z
Stopped at: Phase 2 complete - deployed and verified on gateway
Resume file: None
Next: /gsd:plan-phase 3 for Network Failover

## Phase 1 Plans

| Plan | Wave | Status | Description |
|------|------|--------|-------------|
| 01-01 | 1 | Complete | Backend NTP Service |
| 01-02 | 2 | Complete | Backend NTP API + Models |
| 01-03 | 3 | Complete | Frontend NTP View |

## Phase 2 Plans

| Plan | Wave | Status | Description |
|------|------|--------|-------------|
| 02-01 | 1 | Complete | Backend Backup Service |
| 02-02 | 2 | Complete | Backend Backup API + Models |
| 02-03 | 3 | Complete | Frontend Backup View |
