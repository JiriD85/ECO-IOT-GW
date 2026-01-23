"""
ECO-IOT-GW Serial Service
RS485 port management
"""
import json
import logging
from pathlib import Path
from typing import List, Optional

import serial
import serial.tools.list_ports

from ..config import settings
from ..models.schemas import SerialConfig, SerialPort

logger = logging.getLogger(__name__)


class SerialService:
    """Service for RS485 serial port management."""

    def __init__(self):
        self._config_file = settings.DATA_DIR / "serial_config.json"
        self._config: Optional[SerialConfig] = None
        self._load_config()

    def _load_config(self):
        """Load serial configuration from disk."""
        if self._config_file.exists():
            try:
                with open(self._config_file) as f:
                    data = json.load(f)
                    self._config = SerialConfig(**data)
            except Exception as e:
                logger.warning(f"Failed to load serial config: {e}")
                self._config = None

    def _save_config(self):
        """Save serial configuration to disk."""
        if not self._config:
            return

        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_file, 'w') as f:
            json.dump(self._config.model_dump(), f)

    def list_ports(self) -> List[SerialPort]:
        """List available serial ports."""
        ports = []

        for port in serial.tools.list_ports.comports():
            ports.append(SerialPort(
                device=port.device,
                description=port.description,
                hwid=port.hwid
            ))

        # Add common Raspberry Pi serial ports if not detected
        common_ports = [
            "/dev/ttyAMA0",  # Primary UART
            "/dev/ttyS0",    # Mini UART
            "/dev/serial0",  # Symlink
        ]

        existing_devices = {p.device for p in ports}
        for port in common_ports:
            if port not in existing_devices and Path(port).exists():
                ports.append(SerialPort(
                    device=port,
                    description="Raspberry Pi UART"
                ))

        return ports

    def get_config(self) -> SerialConfig:
        """Get current serial configuration."""
        if self._config:
            return self._config

        # Return default configuration
        return SerialConfig(
            port=settings.SERIAL_DEFAULT_PORT,
            baudrate=settings.SERIAL_DEFAULT_BAUDRATE,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=1.0
        )

    def set_config(self, config: SerialConfig):
        """Set serial configuration."""
        # Validate port exists
        if not Path(config.port).exists():
            raise ValueError(f"Serial port {config.port} does not exist")

        self._config = config
        self._save_config()

        # Update ThingsBoard Gateway modbus connector config if exists
        self._update_gateway_config()

        logger.info(f"Serial configuration set: {config.port} @ {config.baudrate}")

    def _update_gateway_config(self):
        """Update ThingsBoard Gateway configuration with serial settings."""
        if not self._config:
            return

        gateway_config = settings.TB_GATEWAY_CONFIG_DIR / "modbus.json"
        if not gateway_config.exists():
            return

        try:
            with open(gateway_config) as f:
                config = json.load(f)

            # Update serial settings in modbus config
            if "master" in config:
                config["master"]["port"] = self._config.port
                config["master"]["baudrate"] = self._config.baudrate
                config["master"]["bytesize"] = self._config.bytesize
                config["master"]["parity"] = self._config.parity
                config["master"]["stopbits"] = self._config.stopbits

                with open(gateway_config, 'w') as f:
                    json.dump(config, f, indent=2)

                logger.info("Updated ThingsBoard Gateway modbus config")

        except Exception as e:
            logger.warning(f"Failed to update gateway config: {e}")

    def test_port(self) -> bool:
        """Test the configured serial port."""
        config = self.get_config()

        # Map parity string to constant
        parity_map = {
            'N': serial.PARITY_NONE,
            'E': serial.PARITY_EVEN,
            'O': serial.PARITY_ODD,
            'M': serial.PARITY_MARK,
            'S': serial.PARITY_SPACE
        }

        try:
            with serial.Serial(
                port=config.port,
                baudrate=config.baudrate,
                bytesize=config.bytesize,
                parity=parity_map.get(config.parity, serial.PARITY_NONE),
                stopbits=config.stopbits,
                timeout=config.timeout
            ) as ser:
                # Port opened successfully
                logger.info(f"Serial port {config.port} test successful")
                return True

        except serial.SerialException as e:
            raise RuntimeError(f"Failed to open serial port: {e}")


# Global serial service instance
serial_service = SerialService()
