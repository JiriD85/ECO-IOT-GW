"""
ECO-IOT-GW SMS Alert Daemon
Monitors system events and sends SMS alerts to configured recipients.

Trigger Events:
- vpn_down: VPN tunnel disconnected
- modem_down: LTE modem unreachable
- network_failover: Network failover occurred
- backup_failed: Backup operation failed

Features:
- Configurable cooldown per trigger
- Multiple recipients support
- State tracking (alerts only on transitions, not continuous)
- Graceful shutdown on SIGTERM/SIGINT
- Audit logging for all alerts
"""
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# Add app to path for standalone execution
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.sms_service import sms_service
from app.services.modem_service import modem_service
from app.services.audit_service import audit_service

logger = logging.getLogger(__name__)

# Configuration constants
CHECK_INTERVAL = 60  # seconds between checks
VPN_CONFIG_DIR = Path("/etc/eco-iot-gw/vpn")
FAILOVER_STATE_FILE = Path("/var/lib/eco-iot-gw/failover_state.json")


class SMSAlertDaemon:
    """Automated SMS alert monitoring daemon."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.running = False
        # Track previous states to detect transitions
        self._previous_states: Dict[str, bool] = {
            "vpn_down": False,
            "modem_down": False,
            "network_failover": False,
            "backup_failed": False,
        }

    def _check_vpn_status(self) -> bool:
        """
        Check if VPN is expected but down.

        Returns:
            True if VPN should be up but isn't (trigger condition met)
        """
        try:
            # Check if VPN is configured (config files exist)
            vpn_configs = list(VPN_CONFIG_DIR.glob("*.conf")) + list(
                VPN_CONFIG_DIR.glob("*.ovpn")
            )
            if not vpn_configs:
                # No VPN configured, not a failure
                return False

            # Check if any VPN interface is up
            # Look for common VPN interfaces: tun0, wg0, tailscale0
            vpn_interfaces = ["tun0", "wg0", "tailscale0"]
            for iface in vpn_interfaces:
                iface_path = Path(f"/sys/class/net/{iface}")
                if iface_path.exists():
                    operstate = (iface_path / "operstate").read_text().strip()
                    if operstate == "up" or operstate == "unknown":
                        # VPN is up
                        return False

            # VPN configured but no interface up
            self.logger.debug("VPN configured but no VPN interface up")
            return True

        except Exception as e:
            self.logger.error(f"Error checking VPN status: {e}")
            return False

    def _check_modem_status(self) -> bool:
        """
        Check if modem is unreachable.

        Returns:
            True if modem should respond but doesn't (trigger condition met)
        """
        try:
            # Check if modem responds to AT commands
            ready, message = modem_service.check_sms_ready()
            if not ready:
                self.logger.debug(f"Modem not ready: {message}")
                return True
            return False

        except Exception as e:
            self.logger.debug(f"Modem check failed: {e}")
            return True

    def _check_failover_state(self) -> bool:
        """
        Check if network failover has occurred.

        Returns:
            True if currently on backup connection (trigger condition met)
        """
        try:
            if not FAILOVER_STATE_FILE.exists():
                return False

            import json

            state_data = json.loads(FAILOVER_STATE_FILE.read_text())
            state = state_data.get("state", "PRIMARY_ACTIVE")

            if state == "BACKUP_ACTIVE":
                self.logger.debug("Network is on backup connection")
                return True

            return False

        except Exception as e:
            self.logger.error(f"Error checking failover state: {e}")
            return False

    def _check_backup_status(self) -> bool:
        """
        Check for recent backup failures.

        Returns:
            True if a backup failed recently (trigger condition met)
        """
        try:
            # Check audit log for recent backup failures
            # This is a simplified check - could be enhanced with proper state tracking
            from app.services.audit_service import audit_service

            # Get recent audit entries
            logs = audit_service.get_logs(
                limit=10, action="backup_restore", success=False
            )

            if logs:
                # Check if any failures in last hour
                for log in logs:
                    log_time = log.get("timestamp")
                    if log_time:
                        # Parse timestamp and check if recent
                        try:
                            log_dt = datetime.fromisoformat(
                                log_time.replace("Z", "+00:00")
                            )
                            age = (datetime.now(log_dt.tzinfo) - log_dt).total_seconds()
                            if age < 3600:  # Within last hour
                                self.logger.debug("Recent backup failure detected")
                                return True
                        except Exception:
                            pass

            return False

        except Exception as e:
            self.logger.error(f"Error checking backup status: {e}")
            return False

    async def _send_alert(self, event_type: str, message: str) -> None:
        """
        Send SMS alert to all enabled recipients.

        Args:
            event_type: The trigger event type
            message: Alert message to send
        """
        # Check if SMS is enabled
        config = sms_service.get_config()
        if not config.enabled:
            self.logger.debug("SMS alerts disabled, skipping alert")
            return

        # Check cooldown
        if not sms_service.check_trigger_cooldown(event_type):
            self.logger.debug(f"Trigger {event_type} in cooldown, skipping alert")
            return

        # Get enabled recipients
        recipients = sms_service.get_enabled_recipients()
        if not recipients:
            self.logger.warning("No enabled SMS recipients configured")
            return

        # Send to each recipient
        success_count = 0
        for recipient in recipients:
            try:
                success, result = modem_service.send_sms(recipient.phone, message)
                if success:
                    success_count += 1
                    self.logger.info(
                        f"Alert sent to {recipient.name} ({recipient.phone})"
                    )
                else:
                    self.logger.error(
                        f"Failed to send alert to {recipient.name}: {result}"
                    )
            except Exception as e:
                self.logger.error(f"Error sending alert to {recipient.name}: {e}")

        # Record trigger fired
        sms_service.record_trigger_fired(event_type)

        # Audit log
        audit_service.log(
            username="sms_daemon",
            action="sms_alert_sent",
            resource="sms",
            ip_address="127.0.0.1",
            success=success_count > 0,
            details={
                "event_type": event_type,
                "message": message[:50] + "..." if len(message) > 50 else message,
                "recipients_total": len(recipients),
                "recipients_success": success_count,
            },
        )

    async def _evaluate_triggers(self) -> None:
        """
        Evaluate all trigger conditions and send alerts on state transitions.

        Only sends alerts when state changes from OK to FAILED, not continuously.
        """
        # Check each trigger
        checks = {
            "vpn_down": self._check_vpn_status,
            "modem_down": self._check_modem_status,
            "network_failover": self._check_failover_state,
            "backup_failed": self._check_backup_status,
        }

        messages = {
            "vpn_down": "VPN connection lost on ECO-IOT-GW",
            "modem_down": "LTE modem unreachable on ECO-IOT-GW",
            "network_failover": "Network failover to backup on ECO-IOT-GW",
            "backup_failed": "Backup operation failed on ECO-IOT-GW",
        }

        for event_type, check_func in checks.items():
            try:
                current_state = check_func()
                previous_state = self._previous_states.get(event_type, False)

                # Only alert on transition from OK (False) to FAILED (True)
                if current_state and not previous_state:
                    self.logger.warning(
                        f"Trigger {event_type}: state changed to FAILED"
                    )
                    await self._send_alert(event_type, messages[event_type])
                elif not current_state and previous_state:
                    self.logger.info(f"Trigger {event_type}: state recovered to OK")

                # Update previous state
                self._previous_states[event_type] = current_state

            except Exception as e:
                self.logger.error(f"Error evaluating trigger {event_type}: {e}")

    async def monitor_loop(self) -> None:
        """Main monitoring loop - runs continuously."""
        self.logger.info("SMS alert daemon starting...")

        self.running = True

        while self.running:
            try:
                await self._evaluate_triggers()
            except Exception as e:
                self.logger.error(f"Monitor loop error: {e}", exc_info=True)

            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL)

    async def stop(self) -> None:
        """Stop the daemon gracefully."""
        self.logger.info("Stopping SMS alert daemon...")
        self.running = False


async def main():
    """Entry point for standalone daemon execution."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("/var/log/eco-iot-gw/sms-alerts.log"),
        ],
    )

    daemon = SMSAlertDaemon()

    try:
        await daemon.monitor_loop()
    except KeyboardInterrupt:
        await daemon.stop()


if __name__ == "__main__":
    asyncio.run(main())
