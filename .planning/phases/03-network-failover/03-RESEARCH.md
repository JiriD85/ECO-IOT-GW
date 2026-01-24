# Phase 3: Network Failover - Research

**Researched:** 2026-01-24
**Domain:** Linux network routing and failover on Raspberry Pi
**Confidence:** HIGH

## Summary

Network failover on Linux is achieved through routing table metrics, where lower metric values indicate higher priority routes. The standard approach uses the built-in `ip route` command with different metrics for primary (Ethernet) and backup (LTE) interfaces. When the primary interface fails, the kernel automatically switches to the backup route.

Modern implementations use NetworkManager for metric-based failover combined with active connectivity monitoring via ping health checks. This provides both rapid link-layer detection (interface down) and slower but more reliable application-layer detection (gateway unreachable). The combination ensures robust failover without additional software beyond standard Linux tools.

For Raspberry Pi deployments, the decision to use `ip route` with metric-based failover aligns with best practices. NetworkManager (default on Raspberry Pi OS 5) provides built-in failover support, while custom monitoring scripts offer fine-grained control for specific requirements like connectivity thresholds and failback behavior.

**Primary recommendation:** Use metric-based routing with NetworkManager for automatic failover, supplemented by a Python monitoring service using psutil for interface statistics and subprocess for ping health checks. This provides both fast link-layer detection and reliable application-layer verification.

## Standard Stack

The established tools for Linux network failover on Raspberry Pi:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| iproute2 | system | Route management via `ip route` command | Built into all Linux systems, kernel-supported |
| NetworkManager | 1.44+ | Network configuration and automatic failover | Default on Raspberry Pi OS 5, handles metric-based failover automatically |
| systemd | 255+ | Service management and network monitoring | Standard init system, manages network services |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| psutil | 7.2+ | Network interface statistics in Python | Monitoring interface status, bandwidth, connection state |
| pyroute2 | 0.9.3+ | Python netlink library for routing | Advanced route manipulation, real-time network monitoring |
| netifaces | 0.11+ | Portable network interface enumeration | Getting gateway IPs, interface addresses cross-platform |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| NetworkManager | systemd-networkd | Lower overhead but metric persistence issues, less reliable failover |
| Metric-based failover | Custom scripts only | More control but no link-layer detection, slower failover |
| psutil | Parsing /sys/class/net directly | No dependencies but fragile, platform-specific |

**Installation:**
```bash
# Core tools (already installed on Raspberry Pi OS)
sudo apt-get install network-manager iproute2

# Python libraries for monitoring
pip install psutil pyroute2 netifaces
```

## Architecture Patterns

### Recommended Project Structure
```
backend/
├── api/
│   └── network_routes.py       # FastAPI endpoints for failover config/status
├── services/
│   ├── network_service.py      # NetworkManager/ip route integration
│   ├── failover_monitor.py     # Health check monitoring daemon
│   └── audit_service.py        # Configuration change logging
└── models/
    └── network_config.py       # Pydantic models for network configuration

frontend/
├── views/
│   └── NetworkStatus.vue       # Network status dashboard
└── services/
    └── api.js                  # API client for network endpoints
```

### Pattern 1: Metric-Based Routing with NetworkManager
**What:** Configure different route metrics for interfaces, letting the kernel automatically use the lowest-metric route.
**When to use:** When NetworkManager is available (Raspberry Pi OS 5+) and you want automatic link-layer failover.
**Example:**
```bash
# Source: https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html
# Set Ethernet as primary (lower metric = higher priority)
nmcli connection modify ethernet ipv4.route-metric 100

# Set LTE as backup (higher metric = lower priority)
nmcli connection modify lte ipv4.route-metric 200

# Enable connectivity checking
nmcli connection modify ethernet ipv4.may-fail false
nmcli connection modify lte ipv4.may-fail true
```

### Pattern 2: Active Health Check Monitoring
**What:** Periodic ping checks to verify gateway connectivity, adjusting routes when checks fail.
**When to use:** When you need application-layer verification beyond link-layer detection.
**Example:**
```python
# Source: https://www.linuxized.com/2022/01/automatic-internet-failover-to-lte-or-another-interface/
import subprocess
import time

def check_connectivity(interface, gateway):
    """Ping gateway through specific interface"""
    try:
        result = subprocess.run(
            ['ping', '-c', '2', '-W', '3', '-I', interface, gateway],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False

def adjust_route_metric(interface, metric):
    """Adjust route metric for interface"""
    subprocess.run(
        ['nmcli', 'connection', 'modify', interface,
         'ipv4.route-metric', str(metric)],
        check=True
    )
    # Reactivate connection to apply changes
    subprocess.run(['nmcli', 'connection', 'up', interface])
```

### Pattern 3: Policy-Based Routing Tables
**What:** Define separate routing tables for each interface, using IP rules to direct traffic.
**When to use:** When you need advanced routing policies or load balancing.
**Example:**
```bash
# Source: https://github.com/d03n3rfr1tz3/FailOver-Routing
# Define routing tables in /etc/iproute2/rt_tables
# 100 primary
# 101 secondary

# Add routes to each table
ip route add table primary default via 192.168.1.1 dev eth0
ip route add table secondary default via 10.0.0.1 dev wwan0

# Add rules to use tables (lower priority number = higher priority)
ip rule add from 192.168.1.0/24 table primary priority 100
ip rule add from all table secondary priority 200
```

### Pattern 4: Interface Status Monitoring with psutil
**What:** Use psutil to get real-time interface statistics and operational state.
**When to use:** When building a monitoring dashboard or collecting metrics.
**Example:**
```python
# Source: https://psutil.readthedocs.io/
import psutil

def get_interface_status(interface_name):
    """Get comprehensive interface status"""
    # Get interface statistics
    stats = psutil.net_if_stats().get(interface_name)
    if not stats:
        return None

    # Get IO counters
    io_counters = psutil.net_io_counters(pernic=True).get(interface_name)

    return {
        'is_up': stats.isup,
        'speed_mbps': stats.speed,
        'mtu': stats.mtu,
        'bytes_sent': io_counters.bytes_sent if io_counters else 0,
        'bytes_recv': io_counters.bytes_recv if io_counters else 0,
        'errors': io_counters.errin + io_counters.errout if io_counters else 0
    }
```

### Pattern 5: FastAPI WebSocket for Real-Time Status
**What:** Stream network status updates to frontend via WebSocket.
**When to use:** When users need real-time visibility into failover events.
**Example:**
```python
# Source: https://fastapi.tiangolo.com/advanced/websockets/
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio

app = FastAPI()

class NetworkStatusBroadcaster:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, status: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(status)
            except:
                pass

broadcaster = NetworkStatusBroadcaster()

@app.websocket("/ws/network-status")
async def network_status_websocket(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
```

### Anti-Patterns to Avoid
- **Relying solely on ping to 8.8.8.8:** Single point of failure; ping multiple targets (1.1.1.1, 8.8.8.8, ISP gateway)
- **Not persisting route configuration:** Routes vanish on reboot unless configured in NetworkManager or /etc/network/interfaces
- **Immediate failback:** Can cause flapping; introduce hysteresis (require multiple successful checks before failing back)
- **Blocking subprocess calls in async code:** Use `asyncio.create_subprocess_exec()` instead of `subprocess.run()`
- **Not handling both IPv4 and IPv6:** Configure metrics for both address families

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Network interface monitoring | Custom /proc/net parser | psutil library | Handles platform differences, parses binary formats correctly, maintained |
| Route table manipulation | String parsing of `ip route` output | pyroute2 library | Direct netlink access, type-safe, handles edge cases |
| Failover detection | Basic link check script | NetworkManager with connectivity checking | Handles DNS, captive portals, temporary outages with exponential backoff |
| Ping health checks | Custom ICMP implementation | subprocess with `ping` command or asyncio-based ping library | Handles timeouts, packet loss, requires no root privileges for ping command |
| Configuration persistence | Manual file editing | NetworkManager nmcli | Validates configuration, handles service restarts, prevents invalid states |

**Key insight:** Network failover has numerous edge cases that aren't obvious during initial testing. NetworkManager has years of battle-tested logic for handling captive portals, DNS failures, partial connectivity, and race conditions during interface state transitions. Custom scripts typically miss these cases until production failures occur.

## Common Pitfalls

### Pitfall 1: Route Metric Doesn't Persist After Reboot
**What goes wrong:** Routes configured with `ip route` command disappear after reboot, failover stops working.
**Why it happens:** The `ip route` command configures runtime state, not persistent configuration. Without NetworkManager or systemd-networkd configuration, changes are lost.
**How to avoid:**
- Use NetworkManager: `nmcli connection modify <name> ipv4.route-metric <value>`
- Or configure in systemd-networkd .network files with `[Route]` sections
- Verify persistence with `systemctl reboot` in testing
**Warning signs:** Failover works initially but stops working after system reboot.

### Pitfall 2: Quectel Modem Interface Detection Race Condition
**What goes wrong:** LTE modem interface (wwan0 or usb0) appears with different names or takes 30+ seconds to appear after boot, causing failover configuration to fail.
**Why it happens:** Quectel modems can operate in QMI mode (wwan0) or ECM mode (usb0) depending on AT command configuration. Driver loading and modem initialization are asynchronous.
**How to avoid:**
- Configure modem mode explicitly with `AT+QCFG="usbnet",0` (QMI) or `AT+QCFG="usbnet",1` (ECM)
- Use udev rules to create consistent interface names
- Add NetworkManager wait-online service dependency
- Use `ip link show` polling in startup script before configuring routes
**Warning signs:** Failover configuration fails intermittently on boot, interface sometimes appears as wwan0, sometimes as usb0.

### Pitfall 3: Failover Flapping During Intermittent Connectivity
**What goes wrong:** System rapidly switches between interfaces when primary connection is unstable, causing connection drops and poor user experience.
**Why it happens:** No hysteresis in failover logic - single ping failure triggers immediate switch, single success triggers immediate failback.
**How to avoid:**
- Require multiple consecutive failures before failover (e.g., 2-3 failed pings)
- Require sustained success before failback (e.g., 10+ successful pings)
- Use different thresholds for failover (fast) vs failback (slow)
- Add minimum time in failover state (e.g., 60 seconds before attempting failback)
**Warning signs:** Logs show frequent interface switches, users report connection instability, high metric change frequency.

### Pitfall 4: Ping Health Check Continues Using Failed Interface
**What goes wrong:** Ping health check fails to detect outage because it doesn't bind to specific interface, uses whatever route is active.
**Why it happens:** Default ping behavior uses kernel routing table, not source interface binding.
**How to avoid:**
- Use `-I <interface>` flag: `ping -I eth0 8.8.8.8`
- Or use source IP binding: `ping -I 192.168.1.10 8.8.8.8`
- Verify with `tcpdump -i eth0 icmp` during testing
**Warning signs:** Ping succeeds even when primary interface cable is unplugged, failover never triggers.

### Pitfall 5: NetworkManager Overwrites Manual Route Changes
**What goes wrong:** Manual `ip route` commands get overridden by NetworkManager, failover state resets unexpectedly.
**Why it happens:** NetworkManager actively manages interfaces and rewrites routing table when connection state changes or DHCP renews.
**How to avoid:**
- Use NetworkManager's own configuration: `nmcli connection modify`
- Or set `NM_CONTROLLED=no` in interface config (not recommended)
- Or use NetworkManager dispatcher scripts in `/etc/NetworkManager/dispatcher.d/`
**Warning signs:** Route metrics revert to defaults after DHCP renewal or connection restart.

### Pitfall 6: Root Privileges Required for Route Modification
**What goes wrong:** Monitoring service fails to adjust routes because it lacks root privileges.
**Why it happens:** Route table modification requires CAP_NET_ADMIN capability, typically root-only.
**How to avoid:**
- Run monitoring service as systemd service with appropriate capabilities
- Use PolicyKit/pkexec for specific commands
- Or use sudo with NOPASSWD for specific commands in sudoers
- Backend should use existing `_run_command` wrapper with sudo support
**Warning signs:** Route modification commands fail with "Operation not permitted" error.

### Pitfall 7: IPv6 Routes Ignored in Failover Configuration
**What goes wrong:** IPv4 failover works, but IPv6 traffic still uses failed interface or doesn't fail over.
**Why it happens:** Metrics configured only for ipv4.route-metric, IPv6 routes use different defaults.
**How to avoid:**
- Configure both: `ipv4.route-metric` and `ipv6.route-metric`
- Verify with `ip -6 route show`
- Test failover with IPv6 ping: `ping6 2606:4700:4700::1111`
**Warning signs:** Some applications work after failover (IPv4) while others fail (IPv6).

### Pitfall 8: No Feedback on Configuration Changes
**What goes wrong:** User changes failover priority but sees no confirmation, unclear if change took effect.
**Why it happens:** Route changes are silent operations, no visual feedback mechanism.
**How to avoid:**
- Return current routing table state after configuration changes
- Use audit logging for all configuration changes
- Broadcast WebSocket updates when routes change
- Show visual indicator during transition period
**Warning signs:** Users repeatedly apply same configuration, uncertainty about system state.

## Code Examples

Verified patterns from official sources:

### Getting Active Default Route
```python
# Source: https://docs.pyroute2.org/general.html
from pyroute2 import IPRoute

def get_active_default_route():
    """Get currently active default route"""
    with IPRoute() as ipr:
        # Get default routes (dst='0.0.0.0/0')
        routes = ipr.route('show', dst='0.0.0.0/0')

        if not routes:
            return None

        # Sort by metric (lower is better)
        routes.sort(key=lambda r: r.get_attr('RTA_PRIORITY') or 0)

        best_route = routes[0]
        return {
            'interface': best_route.get_attr('RTA_OIF'),
            'gateway': best_route.get_attr('RTA_GATEWAY'),
            'metric': best_route.get_attr('RTA_PRIORITY')
        }
```

### Checking Interface Operational State
```python
# Source: https://psutil.readthedocs.io/
import psutil

def is_interface_operational(interface_name: str) -> bool:
    """Check if interface is up and operational"""
    try:
        stats = psutil.net_if_stats()
        if interface_name not in stats:
            return False

        return stats[interface_name].isup
    except Exception:
        return False
```

### Getting Gateway for Interface
```python
# Source: https://pypi.org/project/netifaces/
import netifaces

def get_interface_gateway(interface_name: str) -> str | None:
    """Get default gateway for specific interface"""
    gateways = netifaces.gateways()

    # Try IPv4 gateway
    if 'default' in gateways:
        default_gw = gateways['default'].get(netifaces.AF_INET)
        if default_gw and default_gw[1] == interface_name:
            return default_gw[0]

    # Check interface-specific gateways
    if netifaces.AF_INET in gateways:
        for gw, iface, is_default in gateways[netifaces.AF_INET]:
            if iface == interface_name:
                return gw

    return None
```

### Vue 3 Network Status Component
```vue
<!-- Source: https://vueuse.org/core/usenetwork/ -->
<template>
  <div class="network-status">
    <div class="status-indicator" :class="{ online: isOnline, offline: !isOnline }">
      <span>{{ isOnline ? 'Connected' : 'Disconnected' }}</span>
    </div>
    <div v-if="isOnline" class="connection-info">
      <p>Type: {{ type || 'unknown' }}</p>
      <p>Speed: {{ effectiveType || 'unknown' }}</p>
      <p v-if="downlink">Downlink: {{ downlink }} Mbps</p>
    </div>
  </div>
</template>

<script setup>
import { useNetwork } from '@vueuse/core'

const { isOnline, downlink, effectiveType, type } = useNetwork()
</script>
```

### Async Subprocess for Non-Blocking Ping
```python
# Source: https://docs.python.org/3/library/subprocess.html
import asyncio

async def async_ping_check(host: str, interface: str) -> bool:
    """Non-blocking ping health check"""
    try:
        process = await asyncio.create_subprocess_exec(
            'ping', '-c', '2', '-W', '3', '-I', interface, host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        await asyncio.wait_for(process.wait(), timeout=5.0)
        return process.returncode == 0

    except asyncio.TimeoutError:
        process.kill()
        return False
    except Exception:
        return False
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ifupdown scripts | NetworkManager / systemd-networkd | ~2015-2020 | Declarative config, automatic failover support, better desktop/server integration |
| Manual /etc/network/interfaces | nmcli / netplan YAML | 2018+ | Version control friendly, validation, API access |
| Custom bash scripts for monitoring | Python services with asyncio | 2020+ | Better error handling, testability, integration with system services |
| Polling /proc/net files | psutil library | 2015+ | Cross-platform, maintained, handles binary formats |
| String parsing ip command output | pyroute2 netlink library | 2016+ | Type-safe, faster, handles all edge cases |
| Separate WiFi/LTE management | Unified NetworkManager | 2014+ | Consistent interface, single source of truth |

**Deprecated/outdated:**
- **ifupdown (ifup/ifdown commands):** Still works but deprecated in favor of NetworkManager/systemd-networkd on modern systems
- **net-tools (ifconfig, route):** Replaced by iproute2 (ip command), lacks features like policy routing
- **dhcpcd for route metrics:** NetworkManager provides better integration with modern desktop environments
- **Ping monitoring with threads:** asyncio-based implementations are more efficient and easier to manage

## Open Questions

Things that couldn't be fully resolved:

1. **Quectel modem specific AT commands for optimal failover**
   - What we know: AT+QCFG="usbnet" controls interface mode (QMI vs ECM)
   - What's unclear: Best mode for failover scenarios, reconnection behavior differences
   - Recommendation: Start with QMI mode (wwan0) as it's better documented, test reconnection timing, have fallback detection for both interface names

2. **NetworkManager vs systemd-networkd on Raspberry Pi OS**
   - What we know: Raspberry Pi OS 5 uses NetworkManager by default, systemd-networkd has metric persistence issues
   - What's unclear: Whether future Raspberry Pi OS versions will switch to systemd-networkd
   - Recommendation: Use NetworkManager (current default), code defensively to detect which is active at runtime

3. **Optimal ping interval and failure threshold**
   - What we know: Too frequent causes overhead, too infrequent delays failover
   - What's unclear: Best values for cellular networks with variable latency
   - Recommendation: Start with 10-second intervals, 3 consecutive failures for failover, 10 consecutive successes for failback. Make configurable for tuning.

4. **LTE data usage during health checks**
   - What we know: Ping generates minimal data (64 bytes per request)
   - What's unclear: Impact on metered LTE connections over time
   - Recommendation: Allow user to disable active LTE health checks (rely on passive metric failover only), or reduce check frequency when on backup

5. **FastAPI async compatibility with subprocess route changes**
   - What we know: FastAPI endpoints should be async, subprocess.run() is blocking
   - What's unclear: Best pattern for route changes from API endpoints
   - Recommendation: Use asyncio.create_subprocess_exec() for all subprocess calls, or use background tasks with blocking calls

## Sources

### Primary (HIGH confidence)
- NetworkManager Documentation - https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html - route metrics, connection priority, failover configuration
- FastAPI WebSockets Documentation - https://fastapi.tiangolo.com/advanced/websockets/ - WebSocket implementation patterns
- psutil Documentation - https://psutil.readthedocs.io/ - network interface monitoring, statistics
- pyroute2 Documentation - https://docs.pyroute2.org/general.html - IPRoute usage, routing table management
- VueUse Network Composable - https://vueuse.org/core/usenetwork/ - Vue 3 network status monitoring
- Python subprocess Documentation - https://docs.python.org/3/library/subprocess.html - subprocess best practices

### Secondary (MEDIUM confidence)
- Linux.com Failover Router Guide - https://www.linux.com/news/using-linux-failover-router/ - failover fundamentals
- Linuxized LTE Failover Tutorial - https://www.linuxized.com/2022/01/automatic-internet-failover-to-lte-or-another-interface/ - practical implementation with dhcpcd and monitoring script
- GitHub FailOver-Routing - https://github.com/d03n3rfr1tz3/FailOver-Routing - Raspberry Pi multi-WAN failover example
- Baeldung Multiple Default Gateways - https://www.baeldung.com/linux/multiple-default-gateways-outbound-connections - policy-based routing concepts
- Cytron Raspberry Pi Failover Tutorial - https://www.cytron.io/tutorial/RPI-ETH-4G-AUTO-SWITCHING - Raspberry Pi specific setup
- Digi Network Failover Docs - https://docs.digi.com/resources/documentation/digidocs/90001548/reference/yocto/r_network_failover.htm - NetworkManager failover behavior
- Quectel Linux USB Driver Guide - https://sixfab.com/wp-content/uploads/2020/12/Quectel_LTE5G_Linux_USB_Driver_User_Guide_V2.0.pdf - interface modes and configuration

### Tertiary (LOW confidence)
- WebSearch: "Linux network failover common mistakes pitfalls 2026" - general pitfall awareness, not verified against official docs
- WebSearch: "Python subprocess network interface monitoring best practices 2026" - general best practices, should be verified during implementation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All tools verified via official documentation, widely used in production
- Architecture: HIGH - Patterns verified via NetworkManager docs, psutil docs, FastAPI docs, real-world examples
- Pitfalls: MEDIUM-HIGH - Common issues verified across multiple sources, some based on community reports not official docs
- Code examples: HIGH - All examples sourced from official documentation or verified open-source implementations

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - stable domain, core Linux networking APIs change slowly)
