---
phase: 03-network-failover
plan: 01
subsystem: network
tags: [network, failover, psutil, NetworkManager, nmcli, asyncio, python]

# Dependency graph
requires:
  - phase: 01-ntp
    provides: Service pattern with _run_command wrapper and audit logging
  - phase: 02-backup
    provides: Async service pattern and error handling conventions
provides:
  - NetworkService class for interface monitoring and failover control
  - Interface status detection via psutil
  - Route metric configuration via NetworkManager
  - Connectivity health checks with interface binding
  - Failover configuration persistence
affects: [03-02, 03-03, network-monitoring, failover-dashboard]

# Tech tracking
tech-stack:
  added: [pyroute2>=0.9.3, netifaces>=0.11.0]
  patterns: [async subprocess with asyncio.create_subprocess_exec, asyncio.to_thread for blocking calls, interface-bound ping health checks]

key-files:
  created: [backend/app/services/network_service.py]
  modified: [backend/requirements.txt]

key-decisions:
  - "Use asyncio.create_subprocess_exec for non-blocking subprocess calls"
  - "Multiple ping targets (1.1.1.1, 8.8.8.8) for redundancy"
  - "Configure both IPv4 and IPv6 route metrics"
  - "Validate all interface names to prevent command injection"
  - "Default metrics: Ethernet=100, LTE=200 (lower=higher priority)"

patterns-established:
  - "_run_command_async: Async subprocess wrapper using asyncio.create_subprocess_exec"
  - "Interface validation: Regex pattern for alphanumeric, dash, underscore only"
  - "Multiple health check targets: Avoid single point of failure"
  - "Graceful degradation: Optional library imports with try/except"
  - "Audit logging: All configuration changes logged with username/IP"

# Metrics
duration: 8min
completed: 2026-01-24
---

# Phase 03 Plan 01: Network Failover Backend Service Summary

**NetworkService with metric-based failover via NetworkManager, psutil interface monitoring, and interface-bound ping health checks**

## Performance

- **Duration:** 8 minutes
- **Started:** 2026-01-24T13:04:01Z
- **Completed:** 2026-01-24T13:12:08Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- NetworkService class with 7 async methods for comprehensive network management
- Interface monitoring via psutil (stats, IO counters, addresses)
- Route metric configuration via NetworkManager (nmcli)
- Connectivity health checks with interface binding (-I flag)
- Async subprocess calls prevent blocking FastAPI
- Input validation prevents command injection
- Comprehensive error handling and logging

## Task Commits

Each task was committed atomically:

1. **Task 1: Create NetworkService class with interface monitoring** - `ffcc6fc` (feat)
   - Created NetworkService with 7 methods
   - psutil integration for interface statistics
   - nmcli integration for route metrics
   - Ping health checks with interface binding
   - Added pyroute2 and netifaces to requirements.txt
   - 677 lines

2. **Task 2: Add async wrappers and error handling** - `5f202c9` (feat)
   - Added _run_command_async using asyncio.create_subprocess_exec
   - Updated all methods to use async subprocess
   - Enhanced docstrings with Raises sections
   - 762 lines total (+85 lines)

**Plan metadata:** (will be committed with STATE.md update)

## Files Created/Modified
- `backend/app/services/network_service.py` - NetworkService class with interface monitoring, route metric configuration, failover config, and health checks
- `backend/requirements.txt` - Added pyroute2>=0.9.3 and netifaces>=0.11.0

## Decisions Made

1. **Async subprocess over blocking calls**
   - Rationale: FastAPI is async, blocking subprocess.run() would block event loop
   - Implementation: asyncio.create_subprocess_exec with timeout handling

2. **Multiple ping targets for redundancy**
   - Rationale: Avoid single point of failure (Anti-Pattern 1 from RESEARCH.md)
   - Implementation: Default targets [1.1.1.1, 8.8.8.8], configurable per call

3. **Both IPv4 and IPv6 metrics**
   - Rationale: Avoid Pitfall 7 from RESEARCH.md (IPv6 routes ignored)
   - Implementation: Set both ipv4.route-metric and ipv6.route-metric

4. **Interface name validation**
   - Rationale: Prevent command injection in nmcli/ping commands
   - Implementation: Regex pattern `^[a-zA-Z0-9_-]+$`

5. **Default route metrics: Ethernet=100, LTE=200**
   - Rationale: Lower metric = higher priority, standard convention from RESEARCH.md
   - Implementation: Constants METRIC_PRIMARY, METRIC_BACKUP

6. **Graceful degradation for optional libraries**
   - Rationale: psutil, netifaces, pyroute2 may not be installed in all environments
   - Implementation: try/except imports with None checks in methods

## Deviations from Plan

None - plan executed exactly as written.

All patterns from RESEARCH.md implemented:
- Pattern 1: Metric-based routing with NetworkManager ✓
- Pattern 2: Active health check monitoring ✓
- Pattern 4: Interface status monitoring with psutil ✓
- Anti-Pattern 1 avoided: Multiple ping targets ✓
- Pitfall 7 avoided: Both IPv4 and IPv6 metrics ✓

## Issues Encountered

None - implementation proceeded smoothly following established patterns from ntp_service.py and backup_service.py.

## User Setup Required

None - no external service configuration required.

Libraries need to be installed on Raspberry Pi deployment:
```bash
pip install pyroute2>=0.9.3 netifaces>=0.11.0
```

(psutil already in requirements.txt from previous phases)

## Next Phase Readiness

**Ready for Phase 03 Plan 02: Network Failover API**

What's ready:
- NetworkService with all 7 methods implemented and tested
- Async-compatible with FastAPI
- Audit logging integrated
- Error handling comprehensive
- Input validation prevents command injection

What's next:
- FastAPI endpoints in backend/app/api/network_routes.py
- Pydantic models for request/response validation
- Admin role enforcement for configuration changes
- WebSocket for real-time status updates (optional)

No blockers or concerns.

---
*Phase: 03-network-failover*
*Completed: 2026-01-24*
