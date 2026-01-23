"""
ECO-IOT-GW WiFi Service
WLAN Access Point management using hostapd/dnsmasq
"""
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import settings
from ..models.schemas import WiFiAPConfig, WiFiAPStatus

logger = logging.getLogger(__name__)


class WiFiService:
    """Service for WiFi Access Point management."""

    def __init__(self):
        self._hostapd_config = settings.HOSTAPD_CONFIG
        self._dnsmasq_config = settings.DNSMASQ_CONFIG
        self._interface = "wlan0"
        self._ap_ip = "192.168.4.1"
        self._dhcp_range = "192.168.4.2,192.168.4.254"

    def _run_command(
        self,
        cmd: list,
        timeout: int = 30,
        check: bool = True
    ) -> subprocess.CompletedProcess:
        """Run a system command."""
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check
        )

    def get_status(self) -> WiFiAPStatus:
        """Get WiFi AP status."""
        try:
            # Check if hostapd is running
            result = self._run_command(
                ["systemctl", "is-active", "hostapd"],
                check=False
            )
            is_active = result.returncode == 0

            if not is_active:
                return WiFiAPStatus(active=False, clients_connected=0)

            # Get current config
            config = self.get_config()

            # Count connected clients
            clients = self.get_clients()

            return WiFiAPStatus(
                active=True,
                ssid=config.ssid,
                channel=config.channel,
                clients_connected=len(clients)
            )

        except Exception as e:
            logger.error(f"Failed to get WiFi status: {e}")
            return WiFiAPStatus(active=False, clients_connected=0)

    def get_config(self) -> WiFiAPConfig:
        """Get current WiFi AP configuration."""
        ssid = "ECO-IOT-GW"
        password = "ecoiotgw123"
        channel = 6
        hidden = False

        if self._hostapd_config.exists():
            try:
                content = self._hostapd_config.read_text()

                # Parse SSID
                match = re.search(r'^ssid=(.+)$', content, re.MULTILINE)
                if match:
                    ssid = match.group(1)

                # Parse password
                match = re.search(r'^wpa_passphrase=(.+)$', content, re.MULTILINE)
                if match:
                    password = match.group(1)

                # Parse channel
                match = re.search(r'^channel=(\d+)$', content, re.MULTILINE)
                if match:
                    channel = int(match.group(1))

                # Parse hidden
                match = re.search(r'^ignore_broadcast_ssid=(\d)$', content, re.MULTILINE)
                if match:
                    hidden = match.group(1) == '1'

            except Exception as e:
                logger.warning(f"Failed to parse hostapd config: {e}")

        return WiFiAPConfig(
            ssid=ssid,
            password=password,
            channel=channel,
            hidden=hidden
        )

    def set_config(self, config: WiFiAPConfig):
        """Set WiFi AP configuration."""
        # Generate hostapd configuration
        hostapd_content = f"""# ECO-IOT-GW Access Point Configuration
interface={self._interface}
driver=nl80211
ssid={config.ssid}
hw_mode=g
channel={config.channel}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid={'1' if config.hidden else '0'}
wpa=2
wpa_passphrase={config.password}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
"""

        # Write hostapd config
        self._hostapd_config.parent.mkdir(parents=True, exist_ok=True)
        self._hostapd_config.write_text(hostapd_content)
        self._hostapd_config.chmod(0o600)

        # Generate dnsmasq configuration
        dnsmasq_content = f"""# ECO-IOT-GW DHCP Configuration
interface={self._interface}
dhcp-range={self._dhcp_range},24h
address=/eco-iot-gw.local/{self._ap_ip}
"""

        # Write dnsmasq config
        self._dnsmasq_config.write_text(dnsmasq_content)

        logger.info(f"WiFi AP configured: SSID={config.ssid}, channel={config.channel}")

        # Restart if already running
        status = self.get_status()
        if status.active:
            self.restart()

    def start(self):
        """Start the WiFi AP."""
        try:
            # Configure interface IP
            self._run_command([
                "ip", "addr", "add", f"{self._ap_ip}/24",
                "dev", self._interface
            ], check=False)

            # Start dnsmasq
            self._run_command(["systemctl", "start", "dnsmasq"])

            # Start hostapd
            self._run_command(["systemctl", "start", "hostapd"])

            # Enable NAT if we have internet connection
            self._enable_nat()

            logger.info("WiFi AP started")

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to start WiFi AP: {e.stderr}")

    def stop(self):
        """Stop the WiFi AP."""
        try:
            self._run_command(["systemctl", "stop", "hostapd"], check=False)
            self._run_command(["systemctl", "stop", "dnsmasq"], check=False)

            # Remove interface IP
            self._run_command([
                "ip", "addr", "del", f"{self._ap_ip}/24",
                "dev", self._interface
            ], check=False)

            # Disable NAT
            self._disable_nat()

            logger.info("WiFi AP stopped")

        except Exception as e:
            logger.warning(f"Error stopping WiFi AP: {e}")

    def restart(self):
        """Restart the WiFi AP."""
        self.stop()
        self.start()

    def _enable_nat(self):
        """Enable NAT for internet sharing."""
        try:
            # Enable IP forwarding
            Path("/proc/sys/net/ipv4/ip_forward").write_text("1")

            # Get default interface
            result = self._run_command([
                "ip", "route", "show", "default"
            ], check=False)

            if result.returncode == 0:
                match = re.search(r'dev\s+(\S+)', result.stdout)
                if match:
                    default_if = match.group(1)

                    # Setup NAT
                    self._run_command([
                        "iptables", "-t", "nat", "-A", "POSTROUTING",
                        "-o", default_if, "-j", "MASQUERADE"
                    ], check=False)

                    self._run_command([
                        "iptables", "-A", "FORWARD",
                        "-i", self._interface, "-o", default_if,
                        "-j", "ACCEPT"
                    ], check=False)

        except Exception as e:
            logger.warning(f"Failed to enable NAT: {e}")

    def _disable_nat(self):
        """Disable NAT."""
        try:
            self._run_command([
                "iptables", "-t", "nat", "-F", "POSTROUTING"
            ], check=False)
        except Exception:
            pass

    def get_clients(self) -> List[Dict[str, str]]:
        """Get list of connected clients."""
        clients = []

        try:
            # Get associated stations from hostapd
            result = self._run_command([
                "hostapd_cli", "-i", self._interface, "all_sta"
            ], check=False)

            if result.returncode == 0:
                current_mac = None
                for line in result.stdout.split('\n'):
                    # MAC address line
                    if re.match(r'^[0-9a-f:]{17}$', line.strip(), re.IGNORECASE):
                        current_mac = line.strip()
                        clients.append({"mac": current_mac, "ip": None})

            # Get IP addresses from DHCP leases
            leases_file = Path("/var/lib/misc/dnsmasq.leases")
            if leases_file.exists():
                leases_content = leases_file.read_text()
                for client in clients:
                    for line in leases_content.split('\n'):
                        parts = line.split()
                        if len(parts) >= 3 and parts[1].lower() == client["mac"].lower():
                            client["ip"] = parts[2]

        except Exception as e:
            logger.warning(f"Failed to get client list: {e}")

        return clients


# Global WiFi service instance
wifi_service = WiFiService()
