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

**Plans:** (created by /gsd:plan-phase)

---

## Phase 4: SMS Alerts
**Goal**: Send SMS alerts via LTE modem for critical events

**Depends on**: Phase 3 (network status awareness)

**Requirements**: SMS-01, SMS-02

**Success Criteria** (what must be TRUE):
1. User can configure SMS recipients
2. System sends SMS on configured triggers
3. User can test SMS functionality

**Plans:** (created by /gsd:plan-phase)

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
- [ ] **FAILOVER-01**: System auto-switches between LTE and Ethernet
- [ ] **FAILOVER-02**: User can configure failover priority and thresholds

### SMS Alerts
- [ ] **SMS-01**: User can configure SMS alert recipients
- [ ] **SMS-02**: System sends SMS via AT commands on Quectel modem
