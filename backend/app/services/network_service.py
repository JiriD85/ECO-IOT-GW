"""
ECO-IOT-GW Network Service
Network interface monitoring and failover control for Raspberry Pi

Handles:
- Interface status monitoring via psutil
- Route metric configuration via NetworkManager (nmcli)
- Connectivity health checks via ping
- Failover configuration management
- Audit logging for all network configuration changes

Failover mechanism:
- Lower route metric = higher priority (Ethernet=100, LTE=200)
- NetworkManager automatically uses lowest-metric route
- Health checks verify connectivity beyond link-layer detection
"""
import asyncio
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:
    psutil = None

try:
    import netifaces
except ImportError:
    netifaces = None

try:
    from pyroute2 import IPRoute
except ImportError:
    IPRoute = None

from .audit_service import audit_service

logger = logging.getLogger(__name__)


class NetworkService:
    """Service for managing network interfaces and failover configuration."""

    def __init__(self):
        """Initialize Network service."""
        self.config_path = Path("/etc/eco-iot-gw/network-failover.conf")
        self._default_primary = "eth0"
        self._default_backup = "wwan0"

        # Default route metrics (lower = higher priority)
        self.METRIC_PRIMARY = 100
        self.METRIC_BACKUP = 200

        # Health check targets (multiple for redundancy)
        self.HEALTH_CHECK_TARGETS = [
            "1.1.1.1",  # Cloudflare DNS
            "8.8.8.8",  # Google DNS
        ]

    def _run_command(
        self, cmd: List[str], sudo: bool = False, timeout: int = 30
    ) -> Tuple[str, str, int]:
        """
        Execute a command with optional sudo.

        Args:
            cmd: Command and arguments as list
            sudo: Whether to run with sudo
            timeout: Command timeout in seconds

        Returns:
            Tuple of (stdout, stderr, returncode)
        """
        try:
            if sudo:
                cmd = ["sudo"] + cmd

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode

        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {' '.join(cmd)}")
            return "", "Command timed out", -1
        except Exception as e:
            logger.error(f"Command failed: {' '.join(cmd)} - {e}")
            return "", str(e), -1

    def _validate_interface_name(self, interface: str) -> bool:
        """
        Validate interface name to prevent command injection.

        Args:
            interface: Interface name to validate

        Returns:
            True if valid, False otherwise
        """
        # Allow only alphanumeric, dash, underscore
        if not re.match(r'^[a-zA-Z0-9_-]+$', interface):
            logger.warning(f"Invalid interface name: {interface}")
            return False
        return True

    def _validate_priority(self, priority: int) -> bool:
        """
        Validate route metric priority value.

        Args:
            priority: Priority value to validate (lower = higher priority)

        Returns:
            True if valid, False otherwise
        """
        # Route metrics typically range 0-1000
        if not isinstance(priority, int) or priority < 0 or priority > 1000:
            logger.warning(f"Invalid priority value: {priority}")
            return False
        return True

    def _validate_ip_address(self, ip: str) -> bool:
        """
        Validate IP address format.

        Args:
            ip: IP address to validate

        Returns:
            True if valid, False otherwise
        """
        # Simple IPv4 validation
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
            return False

        parts = ip.split('.')
        return all(0 <= int(part) <= 255 for part in parts)

    async def get_interfaces(self) -> List[Dict[str, Any]]:
        """
        Get list of all network interfaces with status.

        Returns:
            List of interface dictionaries with name, is_up, speed, bytes sent/recv
        """
        interfaces = []

        if psutil is None:
            logger.error("psutil not available, cannot get interfaces")
            return interfaces

        try:
            # Run in thread to avoid blocking
            stats = await asyncio.to_thread(psutil.net_if_stats)
            io_counters = await asyncio.to_thread(psutil.net_io_counters, pernic=True)

            for interface_name, stat in stats.items():
                # Skip loopback
                if interface_name == "lo":
                    continue

                io = io_counters.get(interface_name)

                interface_info = {
                    "name": interface_name,
                    "is_up": stat.isup,
                    "speed_mbps": stat.speed if stat.speed > 0 else None,
                    "mtu": stat.mtu,
                    "bytes_sent": io.bytes_sent if io else 0,
                    "bytes_recv": io.bytes_recv if io else 0,
                    "errors_in": io.errin if io else 0,
                    "errors_out": io.errout if io else 0,
                    "drops_in": io.dropin if io else 0,
                    "drops_out": io.dropout if io else 0,
                }

                interfaces.append(interface_info)

            logger.debug(f"Found {len(interfaces)} network interfaces")
            return interfaces

        except Exception as e:
            logger.error(f"Failed to get interfaces: {e}")
            return []

    async def get_interface_status(self, interface_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed status for a specific interface.

        Args:
            interface_name: Name of the interface (e.g., eth0, wwan0)

        Returns:
            Dictionary with interface status or None if not found
        """
        if not self._validate_interface_name(interface_name):
            return None

        if psutil is None:
            logger.error("psutil not available, cannot get interface status")
            return None

        try:
            stats = await asyncio.to_thread(psutil.net_if_stats)
            io_counters = await asyncio.to_thread(psutil.net_io_counters, pernic=True)

            if interface_name not in stats:
                logger.warning(f"Interface not found: {interface_name}")
                return None

            stat = stats[interface_name]
            io = io_counters.get(interface_name)

            # Get IP addresses if netifaces is available
            addresses = []
            if netifaces:
                try:
                    addrs = await asyncio.to_thread(netifaces.ifaddresses, interface_name)
                    if netifaces.AF_INET in addrs:
                        for addr_info in addrs[netifaces.AF_INET]:
                            addresses.append({
                                "family": "IPv4",
                                "address": addr_info.get("addr"),
                                "netmask": addr_info.get("netmask"),
                            })
                    if netifaces.AF_INET6 in addrs:
                        for addr_info in addrs[netifaces.AF_INET6]:
                            addresses.append({
                                "family": "IPv6",
                                "address": addr_info.get("addr"),
                                "netmask": addr_info.get("netmask"),
                            })
                except Exception as e:
                    logger.debug(f"Could not get addresses for {interface_name}: {e}")

            return {
                "name": interface_name,
                "is_up": stat.isup,
                "speed_mbps": stat.speed if stat.speed > 0 else None,
                "mtu": stat.mtu,
                "bytes_sent": io.bytes_sent if io else 0,
                "bytes_recv": io.bytes_recv if io else 0,
                "errors_in": io.errin if io else 0,
                "errors_out": io.errout if io else 0,
                "drops_in": io.dropin if io else 0,
                "drops_out": io.dropout if io else 0,
                "addresses": addresses,
            }

        except Exception as e:
            logger.error(f"Failed to get interface status: {e}")
            return None

    async def get_active_route(self) -> Optional[Dict[str, Any]]:
        """
        Get currently active default route.

        Returns:
            Dictionary with interface, gateway, metric or None
        """
        try:
            # Use ip route command for compatibility
            stdout, stderr, rc = self._run_command(["ip", "route", "show", "default"])

            if rc != 0:
                logger.error(f"Failed to get default route: {stderr}")
                return None

            # Parse output: default via 192.168.1.1 dev eth0 proto dhcp src 192.168.1.10 metric 100
            if not stdout.strip():
                logger.warning("No default route found")
                return None

            # Get first default route (lowest metric is active)
            first_line = stdout.strip().split('\n')[0]

            route_info = {
                "interface": None,
                "gateway": None,
                "metric": None,
            }

            # Parse with regex
            if match := re.search(r'via\s+([\d.]+)', first_line):
                route_info["gateway"] = match.group(1)

            if match := re.search(r'dev\s+(\S+)', first_line):
                route_info["interface"] = match.group(1)

            if match := re.search(r'metric\s+(\d+)', first_line):
                route_info["metric"] = int(match.group(1))

            logger.debug(f"Active route: {route_info}")
            return route_info

        except Exception as e:
            logger.error(f"Failed to get active route: {e}")
            return None

    async def set_interface_priority(
        self,
        interface_name: str,
        priority: int,
        username: str = "system",
        ip_address: str = "127.0.0.1"
    ) -> Dict[str, Any]:
        """
        Set route metric (priority) for an interface.

        Lower metric = higher priority (e.g., Ethernet=100, LTE=200)

        Args:
            interface_name: Interface to configure
            priority: Route metric value (0-1000, lower is higher priority)
            username: User making the change (for audit)
            ip_address: Client IP (for audit)

        Returns:
            Dictionary with success status and message
        """
        if not self._validate_interface_name(interface_name):
            error_msg = f"Invalid interface name: {interface_name}"
            audit_service.log(
                username=username,
                action="network_priority_update",
                resource="network",
                ip_address=ip_address,
                success=False,
                details={"interface": interface_name, "error": error_msg}
            )
            return {"success": False, "message": error_msg}

        if not self._validate_priority(priority):
            error_msg = f"Invalid priority value: {priority} (must be 0-1000)"
            audit_service.log(
                username=username,
                action="network_priority_update",
                resource="network",
                ip_address=ip_address,
                success=False,
                details={"interface": interface_name, "priority": priority, "error": error_msg}
            )
            return {"success": False, "message": error_msg}

        try:
            # Get connection name for interface (may differ from interface name)
            stdout, stderr, rc = self._run_command(
                ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"]
            )

            connection_name = None
            if rc == 0:
                for line in stdout.strip().split('\n'):
                    parts = line.split(':')
                    if len(parts) >= 2 and parts[1] == interface_name:
                        connection_name = parts[0]
                        break

            if not connection_name:
                error_msg = f"No active NetworkManager connection for interface {interface_name}"
                logger.warning(error_msg)
                audit_service.log(
                    username=username,
                    action="network_priority_update",
                    resource="network",
                    ip_address=ip_address,
                    success=False,
                    details={"interface": interface_name, "error": error_msg}
                )
                return {"success": False, "message": error_msg}

            # Set IPv4 route metric
            stdout, stderr, rc = self._run_command(
                ["nmcli", "connection", "modify", connection_name,
                 "ipv4.route-metric", str(priority)],
                sudo=True
            )

            if rc != 0:
                error_msg = f"Failed to set IPv4 metric: {stderr}"
                logger.error(error_msg)
                audit_service.log(
                    username=username,
                    action="network_priority_update",
                    resource="network",
                    ip_address=ip_address,
                    success=False,
                    details={"interface": interface_name, "priority": priority, "error": error_msg}
                )
                return {"success": False, "message": error_msg}

            # Set IPv6 route metric (avoid pitfall 7)
            stdout, stderr, rc = self._run_command(
                ["nmcli", "connection", "modify", connection_name,
                 "ipv6.route-metric", str(priority)],
                sudo=True
            )

            if rc != 0:
                logger.warning(f"Failed to set IPv6 metric: {stderr}")

            # Reactivate connection to apply changes
            stdout, stderr, rc = self._run_command(
                ["nmcli", "connection", "up", connection_name],
                sudo=True
            )

            if rc != 0:
                error_msg = f"Failed to reactivate connection: {stderr}"
                logger.error(error_msg)
                audit_service.log(
                    username=username,
                    action="network_priority_update",
                    resource="network",
                    ip_address=ip_address,
                    success=False,
                    details={"interface": interface_name, "priority": priority, "error": error_msg}
                )
                return {"success": False, "message": error_msg}

            # Log success
            audit_service.log(
                username=username,
                action="network_priority_update",
                resource="network",
                ip_address=ip_address,
                success=True,
                details={
                    "interface": interface_name,
                    "connection": connection_name,
                    "priority": priority
                }
            )

            logger.info(f"Set route metric for {interface_name} to {priority}")

            return {
                "success": True,
                "message": f"Priority set for {interface_name}",
                "interface": interface_name,
                "priority": priority
            }

        except Exception as e:
            error_msg = f"Failed to set interface priority: {e}"
            logger.error(error_msg)
            audit_service.log(
                username=username,
                action="network_priority_update",
                resource="network",
                ip_address=ip_address,
                success=False,
                details={"interface": interface_name, "priority": priority, "error": error_msg}
            )
            return {"success": False, "message": error_msg}

    async def check_connectivity(
        self,
        interface_name: str,
        target: Optional[str] = None
    ) -> bool:
        """
        Check connectivity via ping health check bound to specific interface.

        Args:
            interface_name: Interface to test (e.g., eth0, wwan0)
            target: Target IP to ping (defaults to multiple redundant targets)

        Returns:
            True if connectivity verified, False otherwise
        """
        if not self._validate_interface_name(interface_name):
            return False

        # Use multiple targets for redundancy if no specific target given
        targets = [target] if target else self.HEALTH_CHECK_TARGETS

        for test_target in targets:
            if target and not self._validate_ip_address(test_target):
                logger.warning(f"Invalid target IP: {test_target}")
                continue

            try:
                # Use asyncio subprocess to avoid blocking
                process = await asyncio.create_subprocess_exec(
                    'ping', '-c', '2', '-W', '3', '-I', interface_name, test_target,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)

                    if process.returncode == 0:
                        logger.debug(f"Connectivity check passed: {interface_name} -> {test_target}")
                        return True

                except asyncio.TimeoutError:
                    logger.debug(f"Connectivity check timeout: {interface_name} -> {test_target}")
                    try:
                        process.kill()
                    except:
                        pass

            except Exception as e:
                logger.debug(f"Connectivity check error: {interface_name} -> {test_target}: {e}")
                continue

        # All targets failed
        logger.warning(f"Connectivity check failed for {interface_name}")
        return False

    async def get_failover_config(self) -> Dict[str, Any]:
        """
        Get current failover configuration.

        Returns:
            Dictionary with primary and backup interface names
        """
        try:
            if self.config_path.exists():
                content = await asyncio.to_thread(self.config_path.read_text)
                lines = content.strip().split('\n')

                config = {}
                for line in lines:
                    if '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()

                return {
                    "primary": config.get("PRIMARY", self._default_primary),
                    "backup": config.get("BACKUP", self._default_backup),
                }
            else:
                # Return defaults
                return {
                    "primary": self._default_primary,
                    "backup": self._default_backup,
                }

        except Exception as e:
            logger.error(f"Failed to get failover config: {e}")
            return {
                "primary": self._default_primary,
                "backup": self._default_backup,
            }

    async def set_failover_config(
        self,
        primary: str,
        backup: str,
        username: str = "system",
        ip_address: str = "127.0.0.1"
    ) -> Dict[str, Any]:
        """
        Configure primary and backup interfaces for failover.

        Args:
            primary: Primary interface name (e.g., eth0)
            backup: Backup interface name (e.g., wwan0)
            username: User making the change (for audit)
            ip_address: Client IP (for audit)

        Returns:
            Dictionary with success status and message
        """
        if not self._validate_interface_name(primary):
            error_msg = f"Invalid primary interface name: {primary}"
            audit_service.log(
                username=username,
                action="network_failover_config",
                resource="network",
                ip_address=ip_address,
                success=False,
                details={"primary": primary, "backup": backup, "error": error_msg}
            )
            return {"success": False, "message": error_msg}

        if not self._validate_interface_name(backup):
            error_msg = f"Invalid backup interface name: {backup}"
            audit_service.log(
                username=username,
                action="network_failover_config",
                resource="network",
                ip_address=ip_address,
                success=False,
                details={"primary": primary, "backup": backup, "error": error_msg}
            )
            return {"success": False, "message": error_msg}

        try:
            # Get old config for audit
            old_config = await self.get_failover_config()

            # Write new config
            config_content = f"PRIMARY={primary}\nBACKUP={backup}\n"

            # Ensure directory exists
            await asyncio.to_thread(self.config_path.parent.mkdir, parents=True, exist_ok=True)

            # Write to temp file first
            temp_path = Path(f"/tmp/network-failover.conf.new")
            await asyncio.to_thread(temp_path.write_text, config_content)

            # Move to final location with sudo
            stdout, stderr, rc = self._run_command(
                ["cp", str(temp_path), str(self.config_path)],
                sudo=True
            )

            if rc != 0:
                error_msg = f"Failed to write config: {stderr}"
                logger.error(error_msg)
                audit_service.log(
                    username=username,
                    action="network_failover_config",
                    resource="network",
                    ip_address=ip_address,
                    success=False,
                    details={"primary": primary, "backup": backup, "error": error_msg}
                )
                return {"success": False, "message": error_msg}

            # Clean up temp file
            await asyncio.to_thread(temp_path.unlink, missing_ok=True)

            # Apply route metrics
            await self.set_interface_priority(primary, self.METRIC_PRIMARY, username, ip_address)
            await self.set_interface_priority(backup, self.METRIC_BACKUP, username, ip_address)

            # Log success
            audit_service.log(
                username=username,
                action="network_failover_config",
                resource="network",
                ip_address=ip_address,
                success=True,
                details={
                    "old_primary": old_config.get("primary"),
                    "old_backup": old_config.get("backup"),
                    "new_primary": primary,
                    "new_backup": backup,
                }
            )

            logger.info(f"Failover configured: primary={primary}, backup={backup}")

            return {
                "success": True,
                "message": "Failover configuration updated",
                "primary": primary,
                "backup": backup,
            }

        except Exception as e:
            error_msg = f"Failed to set failover config: {e}"
            logger.error(error_msg)
            audit_service.log(
                username=username,
                action="network_failover_config",
                resource="network",
                ip_address=ip_address,
                success=False,
                details={"primary": primary, "backup": backup, "error": error_msg}
            )
            return {"success": False, "message": error_msg}


# Global network service instance
network_service = NetworkService()
