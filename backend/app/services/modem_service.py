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

    def get_status(self) -> ModemStatus:
        """Get modem status."""
        try:
            # Check if modem is present
            port = self._find_modem_port()
            if not port:
                return ModemStatus(connected=False)

            # Get registration status
            reg_response = self.send_at_command("AT+CREG?")
            connected = ",1" in reg_response or ",5" in reg_response

            # Get signal quality
            signal_response = self.send_at_command("AT+CSQ")
            signal_strength = signal_quality = None
            match = re.search(r'\+CSQ:\s*(\d+)', signal_response)
            if match:
                csq = int(match.group(1))
                if csq != 99:
                    # Convert CSQ to dBm: dBm = -113 + (CSQ * 2)
                    signal_strength = -113 + (csq * 2)
                    # Quality percentage
                    signal_quality = min(100, max(0, (csq * 100) // 31))

            # Get network type
            network_response = self.send_at_command("AT+COPS?")
            network_type = None
            if ',7' in network_response:
                network_type = "LTE"
            elif ',2' in network_response:
                network_type = "3G"
            elif ',0' in network_response:
                network_type = "2G"

            # Get carrier
            carrier = None
            match = re.search(r'"([^"]+)"', network_response)
            if match:
                carrier = match.group(1)

            # Get IMEI
            imei_response = self.send_at_command("AT+GSN")
            imei = None
            for line in imei_response.split('\n'):
                line = line.strip()
                if line.isdigit() and len(line) == 15:
                    imei = line
                    break

            # Get IP address (if connected)
            ip_address = None
            if connected:
                ip_response = self.send_at_command("AT+CGPADDR=1")
                match = re.search(r'"(\d+\.\d+\.\d+\.\d+)"', ip_response)
                if match:
                    ip_address = match.group(1)

            return ModemStatus(
                connected=connected,
                signal_strength=signal_strength,
                signal_quality=signal_quality,
                network_type=network_type,
                carrier=carrier,
                imei=imei,
                ip_address=ip_address
            )

        except Exception as e:
            logger.error(f"Failed to get modem status: {e}")
            return ModemStatus(connected=False)

    def get_signal_info(self) -> Dict[str, Any]:
        """Get detailed signal information."""
        info = {}

        try:
            # Basic signal quality
            csq = self.send_at_command("AT+CSQ")
            info["csq_response"] = csq

            # Extended signal quality (Quectel specific)
            qcsq = self.send_at_command("AT+QCSQ")
            info["qcsq_response"] = qcsq

            # Serving cell info (Quectel specific)
            qeng = self.send_at_command("AT+QENG=\"servingcell\"")
            info["serving_cell"] = qeng

            # Network registration
            creg = self.send_at_command("AT+CREG?")
            info["registration"] = creg

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
        """Reset modem."""
        try:
            self.send_at_command("AT+CFUN=1,1")
            logger.info("Modem reset initiated")
        except Exception as e:
            raise RuntimeError(f"Failed to reset modem: {e}")

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
