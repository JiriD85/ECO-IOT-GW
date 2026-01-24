# ECO-IOT-GW System Configuration Roadmap

## Overview
System-level configuration of IoT Gateway via web UI, without touching ThingsBoard Gateway config (MQTT sync from server).

---

## Phase 1: NTP Configuration
**Goal**: Users can configure NTP time synchronization and view sync status for accurate audit logs and coordinated sensor data

**Depends on**: Nothing (first phase)

**Requirements**: NTP-01, NTP-02, NTP-03

**Success Criteria** (what must be TRUE):
1. User can configure chrony NTP servers and pools via web UI and changes persist across reboots
2. User can set system time zone from dropdown list and verify change takes effect
3. User can view real-time NTP sync status showing offset, jitter, stratum, and last sync time
4. System maintains accurate time even after offline boot (chrony makestep configured)
5. All configuration changes are logged to audit trail with timestamp and user

**Plans:** 3 plans

Plans:
- [x] 01-01-PLAN.md - Backend NTP Service (chrony config, status) ✓
- [x] 01-02-PLAN.md - Backend NTP API + Models (endpoints, schemas) ✓
- [x] 01-03-PLAN.md - Frontend NTP View (Vue component, UI) ✓

---

## Phase 2: Backup & Restore
**Goal**: Users can create system backups and restore from them

**Depends on**: Phase 1 (audit logging foundation)

**Requirements**: BACKUP-01, BACKUP-02, BACKUP-03

**Success Criteria** (what must be TRUE):
1. User can create full system backup as tar.gz
2. User can download backup file
3. User can restore from uploaded backup
4. Backup includes all critical configs (VPN, modem, serial, etc.)

**Plans:** 3 plans

Plans:
- [x] 02-01-PLAN.md - Backend Backup Service (tar.gz creation, manifest, validation) ✓
- [x] 02-02-PLAN.md - Backend Backup API + Models (endpoints, schemas) ✓
- [x] 02-03-PLAN.md - Frontend Backup View (Vue component, UI) ✓

---

## Phase 3: Network Failover
**Goal**: Automatic failover between LTE and Ethernet connections

**Depends on**: Phase 1 (NTP for accurate logging)

**Requirements**: FAILOVER-01, FAILOVER-02

**Success Criteria** (what must be TRUE):
1. System detects primary connection failure
2. System automatically switches to backup connection
3. User can configure failover priority
4. User can view current connection status

**Plans:** 4 plans

Plans:
- [x] 03-01-PLAN.md - Backend Network Service (NetworkManager integration, interface monitoring) ✓
- [x] 03-02-PLAN.md - Backend Network API + Models (endpoints, schemas) ✓
- [x] 03-03-PLAN.md - Frontend Network Status View (Vue component, UI) ✓
- [x] 03-04-PLAN.md - Failover Monitoring Daemon (automated health checks, systemd service) ✓

---

## Phase 4: SMS Alerts
**Goal**: Send SMS alerts via LTE modem for critical events

**Depends on**: Phase 3 (network status awareness)

**Requirements**: SMS-01, SMS-02

**Success Criteria** (what must be TRUE):
1. User can configure SMS recipients
2. System sends SMS on configured triggers
3. User can test SMS functionality

**Plans:** 4 plans

Plans:
- [x] 04-01-PLAN.md - Backend SMS Foundation (models, sms_service, modem SMS methods) ✓
- [x] 04-02-PLAN.md - Backend SMS API (endpoints for config and testing) ✓
- [x] 04-03-PLAN.md - Frontend SMS Alerts View (Vue component, UI) ✓
- [x] 04-04-PLAN.md - SMS Alert Daemon (automated trigger monitoring, systemd service) ✓

---

## Phase 5: Menu Restructuring
**Goal**: Navigation is simplified from 15 to 8 menu items with logical tab-based grouping

**Depends on**: Nothing (UI reorganization, independent of v1.0)

**Requirements**: MENU-01, MENU-02, MENU-03, MENU-04, MENU-05

**Success Criteria** (what must be TRUE):
1. User sees 8 menu items in navigation instead of 15 separate items
2. User can access Modem and Serial configurations as tabs within Interfaces view
3. User can access Failover, VPN, and WiFi configurations as tabs within Network view
4. User can access Settings, NTP, Backup, and Admin as tabs within System view
5. User can access Diagnostics, Audit, and SMS Alerts as tabs within Monitoring view

**Plans:** 4 plans

Plans:
- [ ] 05-01-PLAN.md — Create parent container views (Interfaces, Network, System, Monitoring)
- [ ] 05-02-PLAN.md — Restructure router with nested routes and redirects
- [ ] 05-03-PLAN.md — Adapt child components (remove containers, keep logic)
- [ ] 05-04-PLAN.md — Update App.vue menu and verify navigation

---

## Requirements Reference

### NTP Configuration
- [x] **NTP-01**: User can configure chrony NTP servers and pools via web UI ✓
- [x] **NTP-02**: User can set system time zone from dropdown list ✓
- [x] **NTP-03**: User can view NTP sync status including offset, jitter, and stratum ✓

### Backup & Restore
- [x] **BACKUP-01**: User can create full system backup ✓
- [x] **BACKUP-02**: User can download backup as tar.gz ✓
- [x] **BACKUP-03**: User can restore from backup file ✓

### Network Failover
- [x] **FAILOVER-01**: System auto-switches between LTE and Ethernet ✓
- [x] **FAILOVER-02**: User can configure failover priority and thresholds ✓

### SMS Alerts
- [x] **SMS-01**: User can configure SMS alert recipients ✓
- [x] **SMS-02**: System sends SMS via AT commands on Quectel modem ✓

### Menu Restructuring
- [ ] **MENU-01**: Interfaces view combines Modem and Serial as tabs
- [ ] **MENU-02**: Network view combines Failover, VPN, and WiFi as tabs
- [ ] **MENU-03**: System view combines Settings, NTP, Backup, and Admin as tabs
- [ ] **MENU-04**: Monitoring view combines Diagnostics, Audit, and SMS Alerts as tabs
- [ ] **MENU-05**: Navigation reduced from 15 to 8 menu items
