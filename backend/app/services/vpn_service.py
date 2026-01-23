"""
ECO-IOT-GW VPN Service
OpenVPN, WireGuard, and Tailscale management
"""
import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import settings
from ..models.schemas import VPNAutostart, VPNStatus, VPNType
from ..security.crypto import encrypt_sensitive_data, decrypt_sensitive_data

logger = logging.getLogger(__name__)


class VPNService:
    """Service for VPN management."""

    def __init__(self):
        self._config_file = settings.VPN_CONFIG_DIR / "vpn_config.json"
        self._current_type: Optional[VPNType] = None

        # Ensure directories exist
        settings.VPN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        settings.OPENVPN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        settings.WIREGUARD_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Load saved configuration
        self._load_config()

    def _load_config(self):
        """Load VPN configuration from disk."""
        if self._config_file.exists():
            try:
                with open(self._config_file) as f:
                    data = json.load(f)
                    vpn_type = data.get("vpn_type")
                    if vpn_type:
                        self._current_type = VPNType(vpn_type)
            except Exception as e:
                logger.warning(f"Failed to load VPN config: {e}")

    def _save_meta_config(self, data: Dict[str, Any]):
        """Save VPN metadata configuration."""
        with open(self._config_file, 'w') as f:
            json.dump(data, f)

    def _run_command(
        self,
        cmd: list,
        timeout: int = 30,
        check: bool = True,
        sudo: bool = False
    ) -> subprocess.CompletedProcess:
        """Run a system command."""
        if sudo:
            cmd = ["sudo"] + cmd
        logger.debug(f"Running command: {' '.join(cmd)}")
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check
        )

    def get_status(self) -> VPNStatus:
        """Get current VPN connection status."""
        if not self._current_type:
            return VPNStatus(connected=False)

        if self._current_type == VPNType.OPENVPN:
            return self._get_openvpn_status()
        elif self._current_type == VPNType.WIREGUARD:
            return self._get_wireguard_status()
        elif self._current_type == VPNType.TAILSCALE:
            return self._get_tailscale_status_internal()

        return VPNStatus(connected=False)

    def _get_openvpn_status(self) -> VPNStatus:
        """Get OpenVPN connection status."""
        try:
            # Check if openvpn service is running
            result = self._run_command(
                ["systemctl", "is-active", "openvpn-client@client"],
                check=False
            )
            is_running = result.returncode == 0

            if not is_running:
                return VPNStatus(connected=False, vpn_type=VPNType.OPENVPN)

            # Get interface info
            result = self._run_command(["ip", "addr", "show", "tun0"], check=False)
            if result.returncode != 0:
                return VPNStatus(connected=False, vpn_type=VPNType.OPENVPN)

            # Extract IP
            ip_match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
            ip_address = ip_match.group(1) if ip_match else None

            return VPNStatus(
                connected=True,
                vpn_type=VPNType.OPENVPN,
                interface="tun0",
                ip_address=ip_address
            )

        except Exception as e:
            logger.error(f"Failed to get OpenVPN status: {e}")
            return VPNStatus(connected=False, vpn_type=VPNType.OPENVPN)

    def _get_wireguard_status(self) -> VPNStatus:
        """Get WireGuard connection status."""
        try:
            result = self._run_command(["wg", "show", "wg0"], check=False)

            if result.returncode != 0:
                return VPNStatus(connected=False, vpn_type=VPNType.WIREGUARD)

            # Get interface IP
            ip_result = self._run_command(["ip", "addr", "show", "wg0"], check=False)
            ip_match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', ip_result.stdout)
            ip_address = ip_match.group(1) if ip_match else None

            # Get traffic stats
            bytes_sent = bytes_received = None
            for line in result.stdout.split('\n'):
                if 'transfer:' in line:
                    # Parse "transfer: X received, Y sent"
                    match = re.search(r'(\d+(?:\.\d+)?)\s*\w*\s*received.*?(\d+(?:\.\d+)?)\s*\w*\s*sent', line)
                    if match:
                        bytes_received = int(float(match.group(1)))
                        bytes_sent = int(float(match.group(2)))

            return VPNStatus(
                connected=True,
                vpn_type=VPNType.WIREGUARD,
                interface="wg0",
                ip_address=ip_address,
                bytes_sent=bytes_sent,
                bytes_received=bytes_received
            )

        except Exception as e:
            logger.error(f"Failed to get WireGuard status: {e}")
            return VPNStatus(connected=False, vpn_type=VPNType.WIREGUARD)

    def _get_tailscale_status_internal(self) -> VPNStatus:
        """Get Tailscale connection status."""
        try:
            result = self._run_command(["tailscale", "status", "--json"], check=False)

            if result.returncode != 0:
                return VPNStatus(connected=False, vpn_type=VPNType.TAILSCALE)

            data = json.loads(result.stdout)

            # Get self info
            self_key = data.get("Self", {}).get("PublicKey", "")
            tailnet = data.get("MagicDNSSuffix", "")

            # Get IPs
            ips = data.get("Self", {}).get("TailscaleIPs", [])
            ip_address = ips[0] if ips else None

            return VPNStatus(
                connected=True,
                vpn_type=VPNType.TAILSCALE,
                interface="tailscale0",
                ip_address=ip_address
            )

        except Exception as e:
            logger.error(f"Failed to get Tailscale status: {e}")
            return VPNStatus(connected=False, vpn_type=VPNType.TAILSCALE)

    def get_current_type(self) -> Optional[VPNType]:
        """Get currently configured VPN type."""
        return self._current_type

    def set_type(self, vpn_type: VPNType):
        """Set VPN type, disconnecting previous if necessary."""
        if self._current_type and self._current_type != vpn_type:
            self.disconnect()

        self._current_type = vpn_type
        self._save_meta_config({"vpn_type": vpn_type.value})
        logger.info(f"VPN type set to {vpn_type.value}")

    def get_config_info(self) -> Dict[str, Any]:
        """Get VPN configuration info (without sensitive data)."""
        if not self._current_type:
            return {"configured": False}

        config_exists = False

        if self._current_type == VPNType.OPENVPN:
            config_file = settings.OPENVPN_CONFIG_DIR / "client.conf"
            config_exists = config_file.exists()

        elif self._current_type == VPNType.WIREGUARD:
            config_file = settings.WIREGUARD_CONFIG_DIR / "wg0.conf"
            config_exists = config_file.exists()

        elif self._current_type == VPNType.TAILSCALE:
            # Tailscale is always "configured" if installed
            config_exists = True

        return {
            "configured": config_exists,
            "vpn_type": self._current_type.value
        }

    def save_config(self, content: str, filename: str, vpn_type: VPNType):
        """Save VPN configuration."""
        self.set_type(vpn_type)

        if vpn_type == VPNType.OPENVPN:
            config_path = settings.OPENVPN_CONFIG_DIR / "client.conf"
            config_path.write_text(content)
            # Set ownership to root and readable permissions for OpenVPN service
            self._run_command(["chown", "root:root", str(config_path)], sudo=True, check=False)
            self._run_command(["chmod", "644", str(config_path)], sudo=True, check=False)
            logger.info("OpenVPN configuration saved")

        elif vpn_type == VPNType.WIREGUARD:
            config_path = settings.WIREGUARD_CONFIG_DIR / "wg0.conf"
            config_path.write_text(content)
            # Set ownership to root and restricted permissions for WireGuard
            self._run_command(["chown", "root:root", str(config_path)], sudo=True, check=False)
            self._run_command(["chmod", "600", str(config_path)], sudo=True, check=False)
            logger.info("WireGuard configuration saved")

        else:
            raise ValueError(f"Cannot save config for {vpn_type.value}")

    def delete_config(self):
        """Delete VPN configuration."""
        if self._current_type == VPNType.OPENVPN:
            config_path = settings.OPENVPN_CONFIG_DIR / "client.conf"
            if config_path.exists():
                config_path.unlink()

        elif self._current_type == VPNType.WIREGUARD:
            config_path = settings.WIREGUARD_CONFIG_DIR / "wg0.conf"
            if config_path.exists():
                config_path.unlink()

        logger.info("VPN configuration deleted")

    def connect(self):
        """Connect to VPN."""
        if not self._current_type:
            raise ValueError("No VPN type configured")

        if self._current_type == VPNType.OPENVPN:
            self._connect_openvpn()
        elif self._current_type == VPNType.WIREGUARD:
            self._connect_wireguard()
        elif self._current_type == VPNType.TAILSCALE:
            self._connect_tailscale()

    def _connect_openvpn(self):
        """Connect OpenVPN."""
        config_path = settings.OPENVPN_CONFIG_DIR / "client.conf"
        if not config_path.exists():
            raise FileNotFoundError("OpenVPN configuration not found")

        self._run_command(["systemctl", "start", "openvpn-client@client"], sudo=True)
        logger.info("OpenVPN connection started")

    def _connect_wireguard(self):
        """Connect WireGuard."""
        config_path = settings.WIREGUARD_CONFIG_DIR / "wg0.conf"
        if not config_path.exists():
            raise FileNotFoundError("WireGuard configuration not found")

        self._run_command(["systemctl", "start", "wg-quick@wg0"], sudo=True)
        logger.info("WireGuard connection started")

    def _connect_tailscale(self):
        """Connect Tailscale."""
        self._run_command(["tailscale", "up"], sudo=True)
        logger.info("Tailscale connection started")

    def disconnect(self):
        """Disconnect from VPN."""
        if not self._current_type:
            return

        try:
            if self._current_type == VPNType.OPENVPN:
                self._run_command(
                    ["systemctl", "stop", "openvpn-client@client"],
                    check=False,
                    sudo=True
                )
            elif self._current_type == VPNType.WIREGUARD:
                self._run_command(["systemctl", "stop", "wg-quick@wg0"], check=False, sudo=True)
            elif self._current_type == VPNType.TAILSCALE:
                self._run_command(["tailscale", "down"], check=False, sudo=True)

            logger.info("VPN disconnected")

        except Exception as e:
            logger.error(f"Error disconnecting VPN: {e}")

    def get_autostart(self) -> VPNAutostart:
        """Get VPN autostart configuration."""
        if not self._current_type:
            return VPNAutostart(enabled=False)

        enabled = False

        try:
            if self._current_type == VPNType.OPENVPN:
                result = self._run_command(
                    ["systemctl", "is-enabled", "openvpn-client@client"],
                    check=False
                )
                enabled = result.returncode == 0

            elif self._current_type == VPNType.WIREGUARD:
                result = self._run_command(
                    ["systemctl", "is-enabled", "wg-quick@wg0"],
                    check=False
                )
                enabled = result.returncode == 0

            elif self._current_type == VPNType.TAILSCALE:
                result = self._run_command(
                    ["systemctl", "is-enabled", "tailscaled"],
                    check=False
                )
                enabled = result.returncode == 0

        except Exception as e:
            logger.error(f"Failed to get autostart status: {e}")

        return VPNAutostart(enabled=enabled, vpn_type=self._current_type)

    def set_autostart(self, enabled: bool):
        """Enable or disable VPN autostart."""
        if not self._current_type:
            raise ValueError("No VPN type configured")

        action = "enable" if enabled else "disable"

        if self._current_type == VPNType.OPENVPN:
            self._run_command(["systemctl", action, "openvpn-client@client"], sudo=True)

        elif self._current_type == VPNType.WIREGUARD:
            self._run_command(["systemctl", action, "wg-quick@wg0"], sudo=True)

        elif self._current_type == VPNType.TAILSCALE:
            self._run_command(["systemctl", action, "tailscaled"], sudo=True)

        logger.info(f"VPN autostart {action}d")

    def tailscale_auth(self, auth_key: str):
        """Authenticate Tailscale with auth key."""
        self.set_type(VPNType.TAILSCALE)
        self._run_command(["tailscale", "up", "--authkey", auth_key], sudo=True)
        logger.info("Tailscale authenticated")

    def tailscale_logout(self):
        """Logout from Tailscale."""
        self._run_command(["tailscale", "logout"], sudo=True)
        logger.info("Tailscale logged out")

    def get_tailscale_status(self) -> Dict[str, Any]:
        """Get detailed Tailscale status."""
        try:
            result = self._run_command(["tailscale", "status", "--json"], check=False)

            if result.returncode != 0:
                return {"connected": False, "error": result.stderr}

            return json.loads(result.stdout)

        except Exception as e:
            return {"connected": False, "error": str(e)}


# Global VPN service instance
vpn_service = VPNService()
