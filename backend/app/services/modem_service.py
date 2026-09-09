"""
ECO-IOT-GW Modem Service
Quectel modem management via AT commands and NetworkManager

Handles:
- Modem status and signal info via AT commands
- APN/connection configuration via NetworkManager
- SMS sending via AT+CMGS commands
- Thread-safe serial port access
"""
import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import serial

from ..config import settings
from ..models.schemas import ModemConfig, ModemStatus
from ..security.crypto import encrypt_sensitive_data, decrypt_sensitive_data

logger = logging.getLogger(__name__)


class ModemService:
    """Service for Quectel modem management."""

    def __init__(self):
        self._config_file = settings.DATA_DIR / "modem_config.json"
        self._port = settings.MODEM_DEFAULT_PORT
        self._baudrate = settings.MODEM_BAUDRATE
        self._config: Optional[ModemConfig] = None
        self._serial_lock = threading.Lock()  # Thread-safe serial access
        self._load_config()

    def _load_config(self):
        """Load modem configuration from disk."""
        if self._config_file.exists():
            try:
                with open(self._config_file) as f:
                    data = json.load(f)
                    # Decrypt sensitive fields
                    if data.get("password"):
                        data["password"] = decrypt_sensitive_data(data["password"])
                    if data.get("pin"):
                        data["pin"] = decrypt_sensitive_data(data["pin"])
                    self._config = ModemConfig(**data)
            except Exception as e:
                logger.warning(f"Failed to load modem config: {e}")
                self._config = None

    def _save_config(self):
        """Save modem configuration to disk."""
        if not self._config:
            return

        data = self._config.model_dump()

        # Encrypt sensitive fields
        if data.get("password"):
            data["password"] = encrypt_sensitive_data(data["password"])
        if data.get("pin"):
            data["pin"] = encrypt_sensitive_data(data["pin"])

        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_file, 'w') as f:
            json.dump(data, f)
        self._config_file.chmod(0o600)

    def _find_modem_port(self) -> Optional[str]:
        """Find the modem AT command port."""
        # Common Quectel modem ports
        candidates = [
            "/dev/ttyUSB2",  # Quectel AT port (usually)
            "/dev/ttyUSB1",
            "/dev/ttyUSB0",
            "/dev/ttyACM0",
        ]

        for port in candidates:
            if Path(port).exists():
                try:
                    with serial.Serial(port, self._baudrate, timeout=1) as ser:
                        ser.write(b"AT\r")
                        time.sleep(0.5)
                        response = ser.read(100).decode('utf-8', errors='ignore')
                        if 'OK' in response:
                            return port
                except Exception:
                    continue

        return None

    def send_at_command(self, command: str, timeout: float = 2.0) -> str:
        """Send AT command and return response (thread-safe)."""
        port = self._find_modem_port()
        if not port:
            raise RuntimeError("Modem not found")

        with self._serial_lock:
            try:
                with serial.Serial(port, self._baudrate, timeout=timeout) as ser:
                    # Send command
                    if not command.endswith('\r'):
                        command += '\r'
                    ser.write(command.encode())

                    # Wait and read response
                    time.sleep(0.5)
                    response = ""
                    while ser.in_waiting:
                        response += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                        time.sleep(0.1)

                    return response.strip()

            except Exception as e:
                raise RuntimeError(f"AT command failed: {e}")

    def _mmcli(self, args: list, timeout: float = 8.0) -> str:
        """Run mmcli and return stdout (empty string on failure). The backend runs as
        root, so no sudo is needed; ModemManager owns the Quectel over QMI, so this is the
        correct status source (the raw AT ports are held by ModemManager and give
        'Modem not found' if opened directly)."""
        try:
            r = subprocess.run(["mmcli", *args], capture_output=True, text=True, timeout=timeout)
            return (r.stdout or "") + (r.stderr or "")
        except Exception as e:
            logger.debug(f"mmcli {args} failed: {e}")
            return ""

    @staticmethod
    def _first(pattern: str, text: str, group: int = 1):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(group).strip() if m else None

    def _modem_path(self) -> Optional[str]:
        """The first ModemManager modem path (/org/.../Modem/N), or None if absent."""
        return self._first(r'(/org/freedesktop/ModemManager1/Modem/\d+)', self._mmcli(["-L"]))

    def get_status(self) -> ModemStatus:
        """Get modem status via ModemManager (mmcli)."""
        try:
            if not self._modem_path():
                return ModemStatus(connected=False)
            out = self._mmcli(["-m", "any"])
            if not out:
                return ModemStatus(connected=False)

            state = (self._first(r'\bstate:\s*([a-z-]+)', out) or "").lower()
            registration = (self._first(r'registration:\s*([a-z-]+)', out) or "").lower()
            # "connected" = a data bearer is up; a registered modem (home/roaming) also counts
            connected = state == "connected" or registration in ("home", "roaming")

            # signal quality % (mmcli reports a percentage on the modem summary)
            signal_quality = None
            q = self._first(r'signal quality:\s*(\d+)%', out)
            if q is not None:
                signal_quality = int(q)

            # signal strength in dBm from the periodic signal poll (RSSI)
            signal_strength = None
            sig = self._mmcli(["-m", "any", "--signal-get"])
            rssi = self._first(r'rssi:\s*(-?\d+(?:[.,]\d+)?)\s*dBm', sig)
            if rssi is not None:
                try:
                    signal_strength = int(round(float(rssi.replace(",", "."))))
                except ValueError:
                    pass

            # access technology → network type label
            atech = (self._first(r'access tech(?:nology)?:\s*([a-z0-9]+)', out) or "").lower()
            network_type = {"lte": "LTE", "umts": "3G", "hspa": "3G", "gsm": "2G", "edge": "2G"}.get(atech)
            if not network_type and atech:
                network_type = atech.upper()

            carrier = self._first(r'operator name:\s*(.+)', out)
            imei = self._first(r'equipment id:\s*(\d+)', out)

            # IP address from the CONNECTED bearer (a modem can list an idle "initial"
            # bearer too, so pick the one that is actually connected).
            ip_address = None
            for bnum in re.findall(r'/Bearer/(\d+)', out):
                bout = self._mmcli(["-b", bnum])
                if re.search(r'connected:\s*yes', bout, re.IGNORECASE):
                    ip_address = self._first(r'address:\s*(\d+\.\d+\.\d+\.\d+)', bout)
                    if ip_address:
                        break

            return ModemStatus(
                connected=connected,
                signal_strength=signal_strength,
                signal_quality=signal_quality,
                network_type=network_type,
                carrier=carrier,
                imei=imei,
                ip_address=ip_address,
            )

        except Exception as e:
            logger.error(f"Failed to get modem status: {e}")
            return ModemStatus(connected=False)

    def get_signal_info(self) -> Dict[str, Any]:
        """Get detailed signal information via ModemManager (mmcli)."""
        info = {}
        try:
            if not self._modem_path():
                return {"error": "Modem not found"}
            # arm periodic signal refresh, then read the LTE metrics
            self._mmcli(["-m", "any", "--signal-setup=5"])
            sig = self._mmcli(["-m", "any", "--signal-get"])
            info["signal"] = {
                "rssi": self._first(r'rssi:\s*(-?\d+(?:[.,]\d+)?)', sig),
                "rsrp": self._first(r'rsrp:\s*(-?\d+(?:[.,]\d+)?)', sig),
                "rsrq": self._first(r'rsrq:\s*(-?\d+(?:[.,]\d+)?)', sig),
                "snr": self._first(r's(?:n|-n)r?[^:]*:\s*(-?\d+(?:[.,]\d+)?)', sig),
            }
            modem = self._mmcli(["-m", "any"])
            info["state"] = self._first(r'\bstate:\s*([a-z-]+)', modem)
            info["registration"] = self._first(r'registration:\s*([a-z-]+)', modem)
            info["operator"] = self._first(r'operator name:\s*(.+)', modem)
            info["access_tech"] = self._first(r'access tech(?:nology)?:\s*([a-z0-9]+)', modem)
        except Exception as e:
            info["error"] = str(e)
        return info

    def get_config(self) -> ModemConfig:
        """Get current modem configuration."""
        if self._config:
            return self._config
        return ModemConfig(apn="internet", auto_connect=True)

    def set_config(self, config: ModemConfig):
        """Set modem configuration."""
        self._config = config
        self._save_config()

        # Apply configuration via NetworkManager
        self._apply_nm_config()

        logger.info(f"Modem configuration set: APN={config.apn}")

    def _apply_nm_config(self):
        """Apply configuration via NetworkManager."""
        if not self._config:
            return

        try:
            # Create/update NetworkManager connection
            conn_name = "gsm-connection"

            # Delete existing connection if present
            subprocess.run(
                ["nmcli", "connection", "delete", conn_name],
                capture_output=True,
                check=False
            )

            # Create new connection
            cmd = [
                "nmcli", "connection", "add",
                "type", "gsm",
                "con-name", conn_name,
                "ifname", "*",
                "apn", self._config.apn
            ]

            if self._config.username:
                cmd.extend(["user", self._config.username])
            if self._config.password:
                cmd.extend(["password", self._config.password])

            subprocess.run(cmd, capture_output=True, check=True)

            # Set auto-connect
            auto = "yes" if self._config.auto_connect else "no"
            subprocess.run([
                "nmcli", "connection", "modify", conn_name,
                "connection.autoconnect", auto
            ], capture_output=True, check=True)

            logger.info("NetworkManager GSM connection configured")

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to configure NetworkManager: {e.stderr}")

    def connect(self):
        """Establish modem connection."""
        # Unlock SIM if PIN is set
        if self._config and self._config.pin:
            pin_status = self.send_at_command("AT+CPIN?")
            if "SIM PIN" in pin_status:
                self.send_at_command(f"AT+CPIN={self._config.pin}")
                time.sleep(2)

        # Activate via NetworkManager
        try:
            subprocess.run([
                "nmcli", "connection", "up", "gsm-connection"
            ], capture_output=True, check=True, timeout=60)
            logger.info("Modem connected")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to connect: {e.stderr.decode()}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Connection timeout")

    def disconnect(self):
        """Disconnect modem."""
        try:
            subprocess.run([
                "nmcli", "connection", "down", "gsm-connection"
            ], capture_output=True, check=False)
            logger.info("Modem disconnected")
        except Exception as e:
            logger.warning(f"Error disconnecting modem: {e}")

    def reset(self):
        """Reset modem via ModemManager (mmcli --reset). Uses MM instead of a raw AT
        'AT+CFUN=1,1': the AT ports are held by ModemManager, so the AT path both fails
        ('Modem not found') and — if it ever succeeded — would fight MM and drop the LTE
        link. If no modem is present, do nothing rather than raise (the watchdog calls this)."""
        if not self._modem_path():
            logger.info("Modem reset skipped: no ModemManager modem present")
            return
        out = self._mmcli(["-m", "any", "--reset"], timeout=20)
        if "successfully" in out.lower() or out.strip() == "":
            logger.info("Modem reset initiated via ModemManager")
        else:
            raise RuntimeError(f"Failed to reset modem: {out.strip()[:200]}")

    def check_sms_ready(self) -> Tuple[bool, str]:
        """
        Check if modem is ready for SMS operations.

        Returns:
            Tuple of (ready: bool, message: str)
        """
        try:
            # Check SIM status
            response = self.send_at_command("AT+CPIN?")
            if "READY" in response:
                return True, "SIM ready"
            elif "SIM PIN" in response:
                return False, "SIM requires PIN"
            elif "SIM PUK" in response:
                return False, "SIM blocked, PUK required"
            else:
                return False, f"SIM not ready: {response}"
        except Exception as e:
            return False, str(e)

    def send_sms(self, phone_number: str, message: str) -> Tuple[bool, str]:
        """
        Send SMS message via AT commands.

        Args:
            phone_number: Destination phone number (E.164 format)
            message: Message text (max 160 chars for GSM-7)

        Returns:
            Tuple of (success: bool, message_or_error: str)
            On success, returns message reference from +CMGS response
        """
        # Truncate message to 160 chars (GSM-7 safe length)
        if len(message) > 160:
            message = message[:157] + "..."
            logger.warning("SMS message truncated to 160 characters")

        port = self._find_modem_port()
        if not port:
            return False, "Modem not found"

        with self._serial_lock:
            try:
                with serial.Serial(port, self._baudrate, timeout=30) as ser:
                    # Check SIM ready
                    ser.write(b"AT+CPIN?\r")
                    time.sleep(0.5)
                    response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    if "READY" not in response:
                        return False, f"SIM not ready: {response}"

                    # Set text mode
                    ser.write(b"AT+CMGF=1\r")
                    time.sleep(0.3)
                    response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    if "OK" not in response:
                        return False, f"Failed to set text mode: {response}"

                    # Set GSM charset for better compatibility
                    ser.write(b'AT+CSCS="GSM"\r')
                    time.sleep(0.3)
                    ser.read(ser.in_waiting)  # Clear buffer

                    # Send AT+CMGS with phone number
                    cmgs_cmd = f'AT+CMGS="{phone_number}"\r'
                    ser.write(cmgs_cmd.encode())
                    time.sleep(0.5)

                    # Wait for '>' prompt
                    response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    if '>' not in response:
                        # Cancel the command
                        ser.write(b'\x1b')  # ESC
                        return False, f"No prompt received: {response}"

                    # Send message text + Ctrl-Z
                    ser.write(message.encode('utf-8', errors='replace'))
                    ser.write(b'\x1a')  # Ctrl-Z

                    # Wait for response (up to 30 seconds)
                    start_time = time.time()
                    response = ""
                    while time.time() - start_time < 30:
                        time.sleep(0.5)
                        if ser.in_waiting:
                            response += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                            if "+CMGS:" in response or "ERROR" in response:
                                break

                    # Parse response
                    if "+CMGS:" in response:
                        # Extract message reference
                        match = re.search(r'\+CMGS:\s*(\d+)', response)
                        msg_ref = match.group(1) if match else "unknown"
                        logger.info(f"SMS sent successfully to {phone_number}, ref: {msg_ref}")
                        return True, msg_ref

                    elif "ERROR" in response:
                        logger.error(f"SMS send failed: {response}")
                        return False, f"SMS error: {response}"

                    else:
                        logger.error(f"SMS timeout or unknown response: {response}")
                        return False, f"Timeout or unknown response: {response}"

            except Exception as e:
                logger.error(f"SMS send exception: {e}")
                return False, str(e)


# Global modem service instance
modem_service = ModemService()
