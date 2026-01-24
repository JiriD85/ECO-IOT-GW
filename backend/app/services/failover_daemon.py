"""
ECO-IOT-GW Network Failover Daemon
Automated network failover monitoring with state machine

Continuously monitors primary interface connectivity and automatically
switches to backup interface on failure, with hysteresis to prevent flapping.

State Machine:
- PRIMARY_ACTIVE: Primary interface is healthy, routing through primary
- BACKUP_ACTIVE: Primary failed, routing through backup
- Thresholds: 3 consecutive failures to failover, 10 consecutive successes to failback

Features:
- Periodic health checks every 30 seconds
- Multiple ping targets to avoid single point of failure
- Hysteresis prevents connection flapping
- Audit logging for all failover events
- Graceful shutdown on SIGTERM/SIGINT
"""
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, List
from datetime import datetime

# Add app to path for standalone execution
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.network_service import NetworkService
from app.services.audit_service import audit_service

logger = logging.getLogger(__name__)

# Configuration constants from RESEARCH.md
CHECK_INTERVAL = 30  # seconds between health checks
FAIL_THRESHOLD = 3   # consecutive failures before failover
SUCCESS_THRESHOLD = 10  # consecutive successes before failback
PRIMARY_METRIC = 100
BACKUP_METRIC = 200
PING_TARGETS = ['1.1.1.1', '8.8.8.8']  # Multiple targets per Anti-Pattern 1


class FailoverDaemon:
    """Automated network failover monitoring daemon"""

    def __init__(self):
        self.network_service = NetworkService()
        self.logger = logging.getLogger(__name__)
        self.state = "PRIMARY_ACTIVE"
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.primary_interface = "eth0"
        self.backup_interface = "wwan0"
        self.running = False

    async def load_config(self):
        """Load failover configuration from NetworkService"""
        try:
            config = await self.network_service.get_failover_config()
            self.primary_interface = config.get('primary_interface', 'eth0')
            self.backup_interface = config.get('backup_interface', 'wwan0')
            self.logger.info(f"Loaded config: primary={self.primary_interface}, backup={self.backup_interface}")
        except Exception as e:
            self.logger.warning(f"Failed to load config, using defaults: {e}")

    async def check_interface_connectivity(self, interface: str) -> bool:
        """Check if interface can reach any ping target"""
        for target in PING_TARGETS:
            try:
                result = await self.network_service.check_connectivity(interface, target)
                if result:
                    return True  # At least one target reachable
            except Exception as e:
                self.logger.debug(f"Ping {target} on {interface} failed: {e}")
        return False  # All targets unreachable

    async def handle_primary_failure(self):
        """Switch to backup interface"""
        self.logger.warning(f"Primary interface {self.primary_interface} failed {FAIL_THRESHOLD} consecutive checks, switching to backup")

        try:
            # Set backup to higher priority (lower metric)
            await self.network_service.set_interface_priority(self.backup_interface, PRIMARY_METRIC)
            # Set primary to lower priority (higher metric)
            await self.network_service.set_interface_priority(self.primary_interface, BACKUP_METRIC)

            self.state = "BACKUP_ACTIVE"
            self.consecutive_failures = 0
            self.consecutive_successes = 0

            await audit_service.log_event(
                category="network",
                action="failover_to_backup",
                details=f"Switched from {self.primary_interface} to {self.backup_interface} after {FAIL_THRESHOLD} failures",
                severity="warning"
            )
        except Exception as e:
            self.logger.error(f"Failed to switch to backup: {e}")

    async def handle_primary_recovery(self):
        """Switch back to primary interface"""
        self.logger.info(f"Primary interface {self.primary_interface} recovered after {SUCCESS_THRESHOLD} consecutive checks, failing back")

        try:
            # Restore primary to higher priority (lower metric)
            await self.network_service.set_interface_priority(self.primary_interface, PRIMARY_METRIC)
            # Restore backup to lower priority (higher metric)
            await self.network_service.set_interface_priority(self.backup_interface, BACKUP_METRIC)

            self.state = "PRIMARY_ACTIVE"
            self.consecutive_failures = 0
            self.consecutive_successes = 0

            await audit_service.log_event(
                category="network",
                action="failback_to_primary",
                details=f"Switched back from {self.backup_interface} to {self.primary_interface} after {SUCCESS_THRESHOLD} successes",
                severity="info"
            )
        except Exception as e:
            self.logger.error(f"Failed to switch back to primary: {e}")

    async def monitor_loop(self):
        """Main monitoring loop - runs continuously"""
        self.logger.info("Failover daemon starting...")

        await self.load_config()

        self.running = True

        while self.running:
            try:
                # Check primary interface connectivity
                primary_ok = await self.check_interface_connectivity(self.primary_interface)

                if self.state == "PRIMARY_ACTIVE":
                    if primary_ok:
                        # Primary is healthy
                        self.consecutive_failures = 0
                        self.logger.debug(f"Primary {self.primary_interface} healthy")
                    else:
                        # Primary failed
                        self.consecutive_failures += 1
                        self.logger.warning(f"Primary {self.primary_interface} check failed ({self.consecutive_failures}/{FAIL_THRESHOLD})")

                        if self.consecutive_failures >= FAIL_THRESHOLD:
                            await self.handle_primary_failure()

                elif self.state == "BACKUP_ACTIVE":
                    if primary_ok:
                        # Primary recovered
                        self.consecutive_successes += 1
                        self.logger.info(f"Primary {self.primary_interface} recovery check passed ({self.consecutive_successes}/{SUCCESS_THRESHOLD})")

                        if self.consecutive_successes >= SUCCESS_THRESHOLD:
                            await self.handle_primary_recovery()
                    else:
                        # Primary still down
                        self.consecutive_successes = 0
                        self.logger.debug(f"Primary {self.primary_interface} still down, staying on backup")

            except Exception as e:
                self.logger.error(f"Monitor loop error: {e}", exc_info=True)

            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL)

    async def stop(self):
        """Stop the daemon gracefully"""
        self.logger.info("Stopping failover daemon...")
        self.running = False


async def main():
    """Entry point for standalone daemon execution"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('/var/log/eco-iot-gw/failover.log')
        ]
    )

    daemon = FailoverDaemon()

    try:
        await daemon.monitor_loop()
    except KeyboardInterrupt:
        await daemon.stop()


if __name__ == "__main__":
    asyncio.run(main())
