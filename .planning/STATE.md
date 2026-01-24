# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-24)

**Core value:** System-Level-Konfiguration des IoT Gateways uber eine einfache Web-UI, ohne die ThingsBoard Gateway Config zu beruhren (MQTT-Sync vom Server)

**Current focus:** Phase 5 - Menu Restructuring

## Current Position

Phase: 5 of 5 (Menu Restructuring)
Plan: 1 of 3
Status: In progress
Last activity: 2026-01-24 - Completed 05-01-PLAN.md

Progress: [█████████████████████████████████░] 97%

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
- Use asyncio.create_subprocess_exec for non-blocking subprocess calls (03-01)
- Multiple ping targets (1.1.1.1, 8.8.8.8) for redundancy (03-01)
- Configure both IPv4 and IPv6 route metrics (03-01)
- Validate all interface names to prevent command injection (03-01)
- Default metrics: Ethernet=100, LTE=200 (lower=higher priority) (03-01)
- GET /status unauthenticated for public network visibility (03-02)
- Field validators prevent command injection in interface names (03-02)
- Metric range validation enforces 0-1000 range (03-02)
- Admin role required for failover configuration changes (03-02)
- State machine with PRIMARY_ACTIVE and BACKUP_ACTIVE states (03-04)
- Hysteresis thresholds: 3 failures to failover, 10 successes to failback (03-04)
- 30-second health check interval balances responsiveness and overhead (03-04)
- Systemd service waits 10s after network-online for interface settling (03-04)
- Resource limits: 256M memory, 10% CPU quota for daemon (03-04)
- networkApi follows ntpApi/backupApi pattern for consistency (03-03)
- Admin-only save button with visual indicator for role-based access (03-03)
- Metric validation prevents misconfiguration (primary < backup) (03-03)
- Active interface highlighted with border and chip (03-03)
- phonenumbers library for E.164 validation (04-01)
- threading.Lock for thread-safe serial access to modem (04-01)
- GSM charset (AT+CSCS="GSM") for SMS compatibility (04-01)
- 160 char truncation for GSM-7 safe messages (04-01)
- 30s timeout for SMS delivery confirmation (04-01)
- Cooldown tracking in memory (resets on service restart) (04-01)
- SMS test accessible to all authenticated users (04-02)
- State machine for alerts: only OK→FAILED triggers SMS (04-04)
- 60s check interval for SMS daemon (less aggressive than failover) (04-04)
- Dynamic tab generation from router children instead of hard-coded arrays (05-01)
- Route watcher pattern to keep tab state in sync with navigation (05-01)
- Consistent parent container structure across all four views (05-01)

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
- _run_command_async: Async subprocess wrapper using asyncio.create_subprocess_exec (03-01)
- Interface validation: Regex pattern for alphanumeric, dash, underscore only (03-01)
- Multiple health check targets: Avoid single point of failure (03-01)
- Graceful degradation: Optional library imports with try/except (03-01)
- Audit logging: All configuration changes logged with username/IP (03-01)
- Asyncio daemon pattern: continuous monitoring loop with graceful shutdown (03-04)
- State machine with hysteresis prevents connection flapping (03-04)
- Systemd service dependencies: After=network-online.target NetworkManager.service (03-04)
- networkApi pattern: API grouping for network-related endpoints in api.js (03-03)
- Admin-only UI controls: Role-based button disabling with visual feedback (03-03)
- Multi-section card layout: Status display, configuration, testing sections (03-03)
- Phone validation: validate_phone_number() returns E.164 format (04-01)
- Encrypted config storage: encrypt phone numbers in sms_config.json (04-01)
- smsApi pattern: API grouping for SMS-related endpoints in api.js (04-03)
- Trigger state tracking: transition detection (OK→FAILED only alerts) (04-04)
- SMS daemon: asyncio monitoring loop with 60s interval (04-04)
- Parent container pattern: v-container > v-card > v-tabs + router-view (05-01)
- childRoutes computed: router.getRoutes().find(r => r.name === 'ParentName')?.children (05-01)
- Tab sync: watch(() => route.path, (newPath) => currentTab.value = newPath) (05-01)

### Pending TODOs

None

### Blockers

None

## Session Continuity

Last session: 2026-01-24T14:15:34Z
Stopped at: Completed 05-01-PLAN.md
Resume file: None
Next: Continue with 05-02 (Router restructure)

### Deployment Notes (Phase 3)
- Deployed to gateway 192.168.1.69
- Backend service running (eco-iot-gw-backend)
- Failover daemon running (eco-iot-gw-failover)
- Network Status UI verified working
- Connectivity Test verified working (wlan0 → 8.8.8.8, 0% packet loss)
- Frontend fix: changed operational_status to is_up for API compatibility
- Log file permission fix: /var/log/eco-iot-gw/failover.log

### Deployment Notes (Phase 4)
- Deployed to gateway 192.168.1.69 on 2026-01-24
- Backend service restarted with SMS API endpoints
- SMS alert daemon running (eco-iot-gw-sms-alerts)
- phonenumbers library installed for E.164 validation
- Log file created: /var/log/eco-iot-gw/sms-alerts.log
- SMS Alerts UI accessible at /sms-alerts

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

## Phase 3 Plans

| Plan | Wave | Status | Description |
|------|------|--------|-------------|
| 03-01 | 1 | Complete | Backend Network Service |
| 03-02 | 2 | Complete | Backend Network API + Models |
| 03-03 | 3 | Complete | Frontend Network Failover View |
| 03-04 | 2 | Complete | Failover Daemon |

## Phase 4 Plans

| Plan | Wave | Status | Description |
|------|------|--------|-------------|
| 04-01 | 1 | Complete | Backend SMS Foundation (models, service, modem SMS) |
| 04-02 | 2 | Complete | Backend SMS API (endpoints) |
| 04-03 | 3 | Complete | Frontend SMS Alerts View |
| 04-04 | 3 | Complete | SMS Alert Daemon |

## Phase 5 Plans

| Plan | Wave | Status | Description |
|------|------|--------|-------------|
| 05-01 | 1 | Complete | Create parent container views with v-tabs |
| 05-02 | 2 | Pending | Router restructure (parent/child hierarchy) |
| 05-03 | 3 | Pending | Child view cleanup (remove wrappers) |
