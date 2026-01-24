"""
ECO-IOT-GW NTP Service
Chrony NTP configuration and time management for Raspberry Pi

Handles:
- Chrony configuration (servers, pools, critical settings)
- NTP sync status via chronyc
- Timezone management via timedatectl
- Audit logging for all config changes

Critical settings for IoT Gateway:
- makestep 1 3: For offline boot (RPi has no battery-backed RTC)
- iburst: Fast initial sync on LTE connections
- maxpoll 10: More frequent checks for unstable connections
"""
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .audit_service import audit_service

logger = logging.getLogger(__name__)


class NTPService:
    """Service for managing chrony NTP configuration and time settings."""

    def __init__(self):
        """Initialize NTP service with default chrony paths."""
        self.config_path = Path("/etc/chrony/chrony.conf")
        self.backup_path = Path("/etc/chrony/chrony.conf.bak")
        self._timezone_cache: Optional[List[str]] = None

    def _run_command(
        self, cmd: List[str], sudo: bool = False
    ) -> Tuple[str, str, int]:
        """
        Execute a command with optional sudo.

        Args:
            cmd: Command and arguments as list
            sudo: Whether to run with sudo

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
                timeout=30
            )
            return result.stdout, result.stderr, result.returncode

        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {' '.join(cmd)}")
            return "", "Command timed out", -1
        except Exception as e:
            logger.error(f"Command failed: {' '.join(cmd)} - {e}")
            return "", str(e), -1

    async def get_config(self) -> Dict[str, Any]:
        """
        Parse chrony configuration file.

        Returns:
            Dictionary with:
            - servers: List of NTP servers
            - pools: List of NTP pools
            - settings: Dictionary of key settings (makestep, driftfile, etc.)
        """
        result = {
            "servers": [],
            "pools": [],
            "settings": {}
        }

        try:
            if not self.config_path.exists():
                logger.warning(f"Chrony config not found at {self.config_path}")
                return result

            content = self.config_path.read_text()

            for line in content.splitlines():
                line = line.strip()

                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                parts = line.split()
                if not parts:
                    continue

                directive = parts[0].lower()

                if directive == "server" and len(parts) >= 2:
                    # server <address> [options...]
                    server_entry = {
                        "address": parts[1],
                        "options": parts[2:] if len(parts) > 2 else []
                    }
                    result["servers"].append(server_entry)

                elif directive == "pool" and len(parts) >= 2:
                    # pool <address> [options...]
                    pool_entry = {
                        "address": parts[1],
                        "options": parts[2:] if len(parts) > 2 else []
                    }
                    result["pools"].append(pool_entry)

                elif directive == "makestep" and len(parts) >= 3:
                    # makestep <threshold> <limit>
                    result["settings"]["makestep"] = {
                        "threshold": parts[1],
                        "limit": parts[2]
                    }

                elif directive == "driftfile" and len(parts) >= 2:
                    result["settings"]["driftfile"] = parts[1]

                elif directive == "rtcsync":
                    result["settings"]["rtcsync"] = True

                elif directive in ["maxpoll", "minpoll"] and len(parts) >= 2:
                    result["settings"][directive] = parts[1]

            logger.debug(f"Parsed chrony config: {len(result['servers'])} servers, {len(result['pools'])} pools")
            return result

        except Exception as e:
            logger.error(f"Failed to parse chrony config: {e}")
            return result

    async def set_config(
        self,
        servers: List[str],
        pools: List[str],
        username: str = "system",
        ip_address: str = "127.0.0.1"
    ) -> Dict[str, Any]:
        """
        Write new chrony configuration with specified servers and pools.

        Preserves critical settings for IoT Gateway operation:
        - makestep 1 3: For offline boot
        - iburst: Fast initial sync
        - maxpoll 10: Frequent checks for LTE

        Args:
            servers: List of NTP server addresses
            pools: List of NTP pool addresses
            username: User making the change (for audit)
            ip_address: Client IP (for audit)

        Returns:
            Dictionary with success status and message
        """
        try:
            # Get current config for audit
            old_config = await self.get_config()

            # Create backup
            if self.config_path.exists():
                stdout, stderr, rc = self._run_command(
                    ["cp", str(self.config_path), str(self.backup_path)],
                    sudo=True
                )
                if rc != 0:
                    logger.warning(f"Failed to create backup: {stderr}")

            # Build new configuration
            config_lines = [
                "# Chrony configuration for ECO-IOT-GW",
                "# Managed by ECO-IOT-GW - manual changes may be overwritten",
                "",
                "# NTP Pools (preferred for reliability)",
            ]

            for pool in pools:
                # Add iburst for fast initial sync on LTE connections
                config_lines.append(f"pool {pool} iburst maxpoll 10")

            config_lines.append("")
            config_lines.append("# NTP Servers")

            for server in servers:
                config_lines.append(f"server {server} iburst maxpoll 10")

            # Add critical settings for IoT Gateway
            config_lines.extend([
                "",
                "# Critical settings for Raspberry Pi IoT Gateway",
                "# makestep: Allow large time jumps on startup (RPi has no battery-backed RTC)",
                "makestep 1 3",
                "",
                "# Drift file to track system clock drift",
                "driftfile /var/lib/chrony/drift",
                "",
                "# Sync hardware RTC if present",
                "rtcsync",
                "",
                "# Allow NTP client access from local network",
                "allow 192.168.0.0/16",
                "allow 10.0.0.0/8",
                "",
                "# Log tracking and measurements",
                "logdir /var/log/chrony",
                ""
            ])

            config_content = "\n".join(config_lines)

            # Write to temporary file first
            temp_path = Path("/tmp/chrony.conf.new")
            temp_path.write_text(config_content)

            # Move to final location with sudo
            stdout, stderr, rc = self._run_command(
                ["cp", str(temp_path), str(self.config_path)],
                sudo=True
            )

            if rc != 0:
                # Restore backup
                self._run_command(
                    ["cp", str(self.backup_path), str(self.config_path)],
                    sudo=True
                )
                error_msg = f"Failed to write chrony config: {stderr}"
                logger.error(error_msg)

                audit_service.log(
                    username=username,
                    action="ntp_config_update",
                    resource="ntp",
                    ip_address=ip_address,
                    success=False,
                    details={"error": error_msg}
                )

                return {"success": False, "message": error_msg}

            # Clean up temp file
            temp_path.unlink(missing_ok=True)

            # Restart chrony service
            restart_result = await self.restart_service()

            # Log audit
            audit_service.log(
                username=username,
                action="ntp_config_update",
                resource="ntp",
                ip_address=ip_address,
                success=True,
                details={
                    "old_servers": [s["address"] for s in old_config.get("servers", [])],
                    "old_pools": [p["address"] for p in old_config.get("pools", [])],
                    "new_servers": servers,
                    "new_pools": pools,
                    "service_restarted": restart_result.get("success", False)
                }
            )

            logger.info(f"NTP config updated: {len(servers)} servers, {len(pools)} pools")

            return {
                "success": True,
                "message": "NTP configuration updated successfully",
                "service_restarted": restart_result.get("success", False)
            }

        except Exception as e:
            error_msg = f"Failed to set NTP config: {e}"
            logger.error(error_msg)

            audit_service.log(
                username=username,
                action="ntp_config_update",
                resource="ntp",
                ip_address=ip_address,
                success=False,
                details={"error": error_msg}
            )

            return {"success": False, "message": error_msg}

    async def get_status(self) -> Dict[str, Any]:
        """
        Get NTP synchronization status via chronyc tracking.

        Returns:
            Dictionary with sync status:
            - synced: Whether system is synchronized
            - reference: Current NTP source
            - stratum: NTP stratum level
            - offset: Time offset from source
            - frequency: Clock frequency offset
            - last_update: Time since last update
        """
        result = {
            "synced": False,
            "reference": None,
            "stratum": None,
            "offset": None,
            "frequency": None,
            "last_update": None,
            "leap_status": None,
            "root_delay": None,
            "root_dispersion": None
        }

        try:
            stdout, stderr, rc = self._run_command(["chronyc", "tracking"])

            if rc != 0:
                logger.warning(f"chronyc tracking failed: {stderr}")
                result["error"] = stderr
                return result

            # Parse chronyc tracking output
            for line in stdout.splitlines():
                line = line.strip()

                if line.startswith("Reference ID"):
                    # Reference ID    : 8B4E6B8F (time.cloudflare.com)
                    match = re.search(r"\((.+)\)$", line)
                    if match:
                        result["reference"] = match.group(1)
                    else:
                        # Try to get the hex ID
                        parts = line.split(":")
                        if len(parts) >= 2:
                            result["reference"] = parts[1].strip().split()[0]

                elif line.startswith("Stratum"):
                    # Stratum         : 3
                    parts = line.split(":")
                    if len(parts) >= 2:
                        try:
                            result["stratum"] = int(parts[1].strip())
                        except ValueError:
                            pass

                elif line.startswith("System time"):
                    # System time     : 0.000001234 seconds fast of NTP time
                    match = re.search(r":\s*([-\d.]+)\s*seconds", line)
                    if match:
                        result["offset"] = float(match.group(1))

                elif line.startswith("Frequency"):
                    # Frequency       : 1.234 ppm slow
                    match = re.search(r":\s*([-\d.]+)\s*ppm", line)
                    if match:
                        result["frequency"] = float(match.group(1))

                elif line.startswith("Last offset"):
                    # Last offset     : +0.000000123 seconds
                    match = re.search(r":\s*([-+\d.]+)\s*seconds", line)
                    if match:
                        result["last_update"] = float(match.group(1))

                elif line.startswith("Leap status"):
                    # Leap status     : Normal
                    parts = line.split(":")
                    if len(parts) >= 2:
                        status = parts[1].strip()
                        result["leap_status"] = status
                        result["synced"] = status == "Normal"

                elif line.startswith("Root delay"):
                    # Root delay      : 0.012345 seconds
                    match = re.search(r":\s*([-\d.]+)\s*seconds", line)
                    if match:
                        result["root_delay"] = float(match.group(1))

                elif line.startswith("Root dispersion"):
                    # Root dispersion : 0.001234 seconds
                    match = re.search(r":\s*([-\d.]+)\s*seconds", line)
                    if match:
                        result["root_dispersion"] = float(match.group(1))

            logger.debug(f"NTP status: synced={result['synced']}, ref={result['reference']}")
            return result

        except Exception as e:
            logger.error(f"Failed to get NTP status: {e}")
            result["error"] = str(e)
            return result

    async def get_sources(self) -> List[Dict[str, Any]]:
        """
        Get NTP source information via chronyc sources.

        Returns:
            List of NTP sources with:
            - mode: Server mode (*, +, -, etc.)
            - state: Source state
            - name: Source hostname/IP
            - stratum: NTP stratum
            - poll: Polling interval
            - reach: Reachability register
            - last_rx: Time since last response
            - offset: Time offset
        """
        sources = []

        try:
            stdout, stderr, rc = self._run_command(["chronyc", "sources", "-v"])

            if rc != 0:
                logger.warning(f"chronyc sources failed: {stderr}")
                return sources

            # Parse chronyc sources output
            # MS Name/IP address         Stratum Poll Reach LastRx Last sample
            # ===============================================================================
            # ^* time.cloudflare.com           3   6   377    21    +123us[+456us] +/- 12ms

            in_sources = False
            for line in stdout.splitlines():
                line = line.strip()

                # Skip header lines
                if line.startswith("MS ") or line.startswith("==="):
                    in_sources = True
                    continue

                if not in_sources or not line:
                    continue

                # Parse source line
                # Mode indicators: ^ server, = peer, # local
                # State indicators: * synced, + combined, - not combined, ? unreachable
                if line[0] in "^=#":
                    mode = line[0]
                    state = line[1] if len(line) > 1 else "?"

                    # Split remaining fields
                    parts = line[2:].split()
                    if len(parts) >= 6:
                        source = {
                            "mode": mode,
                            "state": state,
                            "name": parts[0],
                            "stratum": int(parts[1]) if parts[1].isdigit() else None,
                            "poll": int(parts[2]) if parts[2].isdigit() else None,
                            "reach": int(parts[3]) if parts[3].isdigit() else None,
                            "last_rx": parts[4] if len(parts) > 4 else None,
                            "offset": parts[5] if len(parts) > 5 else None,
                            "is_selected": state == "*",
                            "is_combined": state in "*+",
                            "is_reachable": state not in "?x"
                        }
                        sources.append(source)

            logger.debug(f"Found {len(sources)} NTP sources")
            return sources

        except Exception as e:
            logger.error(f"Failed to get NTP sources: {e}")
            return sources

    async def restart_service(self) -> Dict[str, Any]:
        """
        Restart the chrony service.

        Returns:
            Dictionary with success status and message
        """
        try:
            stdout, stderr, rc = self._run_command(
                ["systemctl", "restart", "chrony"],
                sudo=True
            )

            if rc != 0:
                error_msg = f"Failed to restart chrony: {stderr}"
                logger.error(error_msg)
                return {"success": False, "message": error_msg}

            logger.info("Chrony service restarted successfully")
            return {"success": True, "message": "Chrony service restarted"}

        except Exception as e:
            error_msg = f"Failed to restart chrony: {e}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}

    async def get_timezones(self) -> List[str]:
        """
        Get list of available timezones.

        Returns:
            List of timezone names (e.g., Europe/Berlin, America/New_York)
        """
        # Return cached list if available
        if self._timezone_cache is not None:
            return self._timezone_cache

        try:
            stdout, stderr, rc = self._run_command(["timedatectl", "list-timezones"])

            if rc != 0:
                logger.warning(f"Failed to get timezones: {stderr}")
                return []

            timezones = [tz.strip() for tz in stdout.splitlines() if tz.strip()]

            # Cache the result (timezones don't change)
            self._timezone_cache = timezones

            logger.debug(f"Found {len(timezones)} available timezones")
            return timezones

        except Exception as e:
            logger.error(f"Failed to get timezones: {e}")
            return []

    async def get_current_timezone(self) -> Optional[str]:
        """
        Get the current system timezone.

        Returns:
            Current timezone name (e.g., Europe/Berlin) or None on error
        """
        try:
            stdout, stderr, rc = self._run_command(
                ["timedatectl", "show", "--property=Timezone", "--value"]
            )

            if rc != 0:
                logger.warning(f"Failed to get current timezone: {stderr}")
                return None

            timezone = stdout.strip()
            logger.debug(f"Current timezone: {timezone}")
            return timezone

        except Exception as e:
            logger.error(f"Failed to get current timezone: {e}")
            return None

    async def set_timezone(
        self,
        timezone: str,
        username: str = "system",
        ip_address: str = "127.0.0.1"
    ) -> Dict[str, Any]:
        """
        Set the system timezone.

        Args:
            timezone: Timezone name (e.g., Europe/Berlin)
            username: User making the change (for audit)
            ip_address: Client IP (for audit)

        Returns:
            Dictionary with success status and message
        """
        try:
            # Validate timezone exists
            available_timezones = await self.get_timezones()
            if timezone not in available_timezones:
                error_msg = f"Invalid timezone: {timezone}"
                logger.warning(error_msg)

                audit_service.log(
                    username=username,
                    action="timezone_update",
                    resource="ntp",
                    ip_address=ip_address,
                    success=False,
                    details={"timezone": timezone, "error": "Invalid timezone"}
                )

                return {"success": False, "message": error_msg}

            # Get current timezone for audit
            old_timezone = await self.get_current_timezone()

            # Set new timezone
            stdout, stderr, rc = self._run_command(
                ["timedatectl", "set-timezone", timezone],
                sudo=True
            )

            if rc != 0:
                error_msg = f"Failed to set timezone: {stderr}"
                logger.error(error_msg)

                audit_service.log(
                    username=username,
                    action="timezone_update",
                    resource="ntp",
                    ip_address=ip_address,
                    success=False,
                    details={"timezone": timezone, "error": error_msg}
                )

                return {"success": False, "message": error_msg}

            # Log audit
            audit_service.log(
                username=username,
                action="timezone_update",
                resource="ntp",
                ip_address=ip_address,
                success=True,
                details={
                    "old_timezone": old_timezone,
                    "new_timezone": timezone
                }
            )

            logger.info(f"Timezone changed from {old_timezone} to {timezone}")

            return {
                "success": True,
                "message": f"Timezone set to {timezone}",
                "old_timezone": old_timezone,
                "new_timezone": timezone
            }

        except Exception as e:
            error_msg = f"Failed to set timezone: {e}"
            logger.error(error_msg)

            audit_service.log(
                username=username,
                action="timezone_update",
                resource="ntp",
                ip_address=ip_address,
                success=False,
                details={"timezone": timezone, "error": error_msg}
            )

            return {"success": False, "message": error_msg}


# Global NTP service instance
ntp_service = NTPService()
