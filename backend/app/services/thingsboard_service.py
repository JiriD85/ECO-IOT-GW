"""
ECO-IOT-GW ThingsBoard Service
ThingsBoard Gateway connection configuration
"""
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import settings
from ..models.schemas import (
    ThingsBoardConfig,
    ThingsBoardConfigResponse,
    ThingsBoardSecurityType,
    ThingsBoardStatus,
)
from ..security.crypto import decrypt_sensitive_data, encrypt_sensitive_data

logger = logging.getLogger(__name__)


class ThingsBoardService:
    """Service for ThingsBoard Gateway configuration."""

    def __init__(self):
        self._config_file = settings.DATA_DIR / "thingsboard" / "tb_config.json"
        self._ca_cert_file = settings.DATA_DIR / "thingsboard" / "ca.pem"
        self._gateway_config_file = settings.TB_GATEWAY_CONFIG_DIR / "tb_gateway.json"
        self._docker_compose_file = settings.DOCKER_COMPOSE_DIR / "docker-compose.yml"

        # Ensure directories exist
        self._config_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> Optional[Dict[str, Any]]:
        """Load configuration from disk."""
        if not self._config_file.exists():
            return None
        try:
            with open(self._config_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load ThingsBoard config: {e}")
            return None

    def _save_config(self, config: Dict[str, Any]):
        """Save configuration to disk."""
        with open(self._config_file, 'w') as f:
            json.dump(config, f, indent=2)
        # Set proper permissions
        os.chmod(self._config_file, 0o600)

    def get_config(self) -> ThingsBoardConfigResponse:
        """Get ThingsBoard configuration (without sensitive data)."""
        config = self._load_config()

        if not config:
            return ThingsBoardConfigResponse(configured=False)

        return ThingsBoardConfigResponse(
            configured=True,
            host=config.get("host"),
            port=config.get("port"),
            security_type=ThingsBoardSecurityType(config.get("security_type", "access_token")),
            use_tls=config.get("use_tls", False),
            has_ca_cert=self._ca_cert_file.exists(),
            has_access_token=bool(config.get("access_token")),
            has_credentials=bool(config.get("username"))
        )

    def save_config(self, config: ThingsBoardConfig):
        """Save ThingsBoard configuration."""
        config_data = {
            "host": config.host,
            "port": config.port,
            "security_type": config.security_type.value,
            "use_tls": config.use_tls,
        }

        # Handle security credentials
        if config.security_type == ThingsBoardSecurityType.ACCESS_TOKEN:
            if config.access_token:
                config_data["access_token"] = encrypt_sensitive_data(config.access_token)

        elif config.security_type == ThingsBoardSecurityType.TLS_ACCESS_TOKEN:
            config_data["use_tls"] = True
            if config.access_token:
                config_data["access_token"] = encrypt_sensitive_data(config.access_token)

        elif config.security_type == ThingsBoardSecurityType.USERNAME_PASSWORD:
            if config.client_id:
                config_data["client_id"] = config.client_id
            if config.username:
                config_data["username"] = encrypt_sensitive_data(config.username)
            if config.password:
                config_data["password"] = encrypt_sensitive_data(config.password)

        # Save CA certificate if provided
        if config.ca_cert:
            self._ca_cert_file.write_text(config.ca_cert)
            os.chmod(self._ca_cert_file, 0o600)
            config_data["ca_cert_path"] = str(self._ca_cert_file)

        self._save_config(config_data)

        # Update docker-compose.yml environment variables
        self._update_docker_compose(config_data)

        logger.info("ThingsBoard configuration saved")

    def _update_docker_compose(self, config_data: Dict[str, Any]):
        """Update the docker-compose.yml environment variables for ThingsBoard Gateway."""
        try:
            import yaml

            if not self._docker_compose_file.exists():
                logger.warning(f"Docker compose file not found: {self._docker_compose_file}")
                return

            with open(self._docker_compose_file) as f:
                compose_config = yaml.safe_load(f)

            # Find tb-gateway service
            services = compose_config.get("services", {})
            tb_service = services.get("tb-gateway") or services.get("tb_gateway")

            if not tb_service:
                logger.warning("tb-gateway service not found in docker-compose.yml")
                return

            # Build environment variables
            env_vars = []
            env_vars.append(f"host={config_data['host']}")
            env_vars.append(f"port={config_data['port']}")

            security_type = config_data.get("security_type", "access_token")

            if security_type in ("access_token", "tls_access_token"):
                if config_data.get("access_token"):
                    token = decrypt_sensitive_data(config_data["access_token"])
                    env_vars.append(f"accessToken={token}")
            elif security_type == "username_password":
                if config_data.get("client_id"):
                    env_vars.append(f"clientId={config_data['client_id']}")
                if config_data.get("username"):
                    username = decrypt_sensitive_data(config_data["username"])
                    env_vars.append(f"username={username}")
                if config_data.get("password"):
                    password = decrypt_sensitive_data(config_data["password"])
                    env_vars.append(f"password={password}")

            # Update environment
            tb_service["environment"] = env_vars

            # Handle TLS/CA cert volume mount if needed
            if config_data.get("use_tls") and config_data.get("ca_cert_path"):
                volumes = tb_service.get("volumes", [])
                ca_mount = f"{config_data['ca_cert_path']}:/thingsboard_gateway/config/ca.pem:ro"
                if ca_mount not in volumes:
                    volumes.append(ca_mount)
                tb_service["volumes"] = volumes

            # Write back with proper YAML formatting
            with open(self._docker_compose_file, 'w') as f:
                yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)

            logger.info("Docker compose configuration updated")

        except ImportError:
            logger.error("PyYAML not installed, cannot update docker-compose.yml")
            raise RuntimeError("PyYAML required for docker-compose updates")
        except Exception as e:
            logger.error(f"Failed to update docker-compose config: {e}")
            raise

    def delete_config(self):
        """Delete ThingsBoard configuration."""
        if self._config_file.exists():
            self._config_file.unlink()
        if self._ca_cert_file.exists():
            self._ca_cert_file.unlink()
        logger.info("ThingsBoard configuration deleted")

    def get_status(self) -> ThingsBoardStatus:
        """Get ThingsBoard connection status."""
        config = self._load_config()

        if not config:
            return ThingsBoardStatus(connected=False)

        # Check if gateway container is running and connected
        connected = False
        error = None

        try:
            # Check gateway logs for connection status (try both container names)
            result = subprocess.run(
                ["docker", "logs", "--tail", "50", "tb-gateway"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                # Try alternative container name
                result = subprocess.run(
                    ["docker", "logs", "--tail", "50", "thingsboard-gateway"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

            if result.returncode == 0:
                # Look for connection success message
                if "Connected to ThingsBoard" in result.stdout or "MQTT client connected" in result.stdout.lower():
                    connected = True
                elif "Connection refused" in result.stdout or "Connection failed" in result.stdout:
                    error = "Connection refused"
                elif "Authentication failed" in result.stdout:
                    error = "Authentication failed"
            else:
                # Container might not exist
                error = "Gateway container not running"

        except subprocess.TimeoutExpired:
            error = "Timeout checking gateway status"
        except Exception as e:
            error = str(e)

        return ThingsBoardStatus(
            connected=connected,
            host=config.get("host"),
            port=config.get("port"),
            security_type=ThingsBoardSecurityType(config.get("security_type", "access_token")),
            error=error
        )

    def restart_gateway(self):
        """Restart the ThingsBoard Gateway container."""
        try:
            # Try tb-gateway first (standard name from docker-compose)
            result = subprocess.run(
                ["docker", "restart", "tb-gateway"],
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                # Try alternative container name
                result = subprocess.run(
                    ["docker", "restart", "thingsboard-gateway"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=True
                )
            logger.info("ThingsBoard Gateway restarted")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to restart gateway: {e.stderr}")
            raise RuntimeError(f"Failed to restart gateway: {e.stderr}")
        except Exception as e:
            logger.error(f"Failed to restart gateway: {e}")
            raise

    def test_connection(self) -> Dict[str, Any]:
        """Test ThingsBoard connection."""
        config = self._load_config()

        if not config:
            return {"success": False, "error": "No configuration found"}

        try:
            import socket

            host = config.get("host", "")
            port = config.get("port", 1883)

            # Simple TCP connection test
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                return {"success": True, "message": f"Successfully connected to {host}:{port}"}
            else:
                return {"success": False, "error": f"Cannot connect to {host}:{port}"}

        except socket.gaierror:
            return {"success": False, "error": f"Cannot resolve hostname: {config.get('host')}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_available_devices(self) -> Dict[str, Any]:
        """Get available serial devices on the system."""
        devices = []

        # Check for ttyAMA devices (Raspberry Pi hardware UART)
        for i in range(10):
            device_path = f"/dev/ttyAMA{i}"
            if os.path.exists(device_path):
                devices.append({"path": device_path, "type": "UART", "description": f"Hardware UART {i}"})

        # Check for ttyUSB devices (USB-Serial adapters)
        for i in range(10):
            device_path = f"/dev/ttyUSB{i}"
            if os.path.exists(device_path):
                devices.append({"path": device_path, "type": "USB", "description": f"USB Serial {i}"})

        # Check for ttyACM devices (USB CDC ACM)
        for i in range(10):
            device_path = f"/dev/ttyACM{i}"
            if os.path.exists(device_path):
                devices.append({"path": device_path, "type": "ACM", "description": f"USB ACM {i}"})

        return {"devices": devices}

    def generate_docker_compose(self, config_data: Optional[Dict[str, Any]] = None) -> str:
        """Generate docker-compose.yml content from configuration."""
        if not config_data:
            config_data = self._load_config() or {}

        # Build environment variables
        env_vars = []
        env_vars.append(f"      - host={config_data.get('host', 'lb-mqtt.pke-iot.expert')}")
        env_vars.append(f"      - port={config_data.get('port', 1883)}")

        security_type = config_data.get("security_type", "access_token")

        if security_type in ("access_token", "tls_access_token"):
            if config_data.get("access_token"):
                token = decrypt_sensitive_data(config_data["access_token"])
                env_vars.append(f"      - accessToken={token}")
        elif security_type == "username_password":
            if config_data.get("client_id"):
                env_vars.append(f"      - clientId={config_data['client_id']}")
            if config_data.get("username"):
                username = decrypt_sensitive_data(config_data["username"])
                env_vars.append(f"      - username={username}")
            if config_data.get("password"):
                password = decrypt_sensitive_data(config_data["password"])
                env_vars.append(f"      - password={password}")

        env_section = "\n".join(env_vars)

        # Build devices section
        device_lines = []
        available = self.get_available_devices()
        for dev in available.get("devices", []):
            device_lines.append(f'      - "{dev["path"]}:{dev["path"]}"')

        devices_section = "\n".join(device_lines) if device_lines else "      # No serial devices detected"

        # Generate docker-compose.yml
        compose_content = f'''version: '3.4'
services:
  tb-gateway:
    image: thingsboard/tb-gateway:3.7-stable
    container_name: tb-gateway
    restart: always

    # Serial device mappings
    devices:
{devices_section}

    # Port bindings
    ports:
      - "5000:5000"    # REST connector
      - "47808:47808/tcp"  # BACnet TCP
      - "47808:47808/udp"  # BACnet UDP
      - "502:502"      # Modbus TCP
      - "50000:50000/tcp"  # Socket TCP
      - "50000:50000/udp"  # Socket UDP

    # Docker host networking
    extra_hosts:
      - "host.docker.internal:host-gateway"

    # ThingsBoard connection settings
    environment:
{env_section}

    # Persistent volumes
    volumes:
      - tb-gw-config:/thingsboard_gateway/config
      - tb-gw-logs:/thingsboard_gateway/logs
      - tb-gw-extensions:/thingsboard_gateway/extensions

volumes:
  tb-gw-config:
    name: tb-gw-config
  tb-gw-logs:
    name: tb-gw-logs
  tb-gw-extensions:
    name: tb-gw-extensions
'''
        return compose_content

    def deploy_gateway(self) -> Dict[str, Any]:
        """Generate docker-compose.yml and start the gateway."""
        try:
            config_data = self._load_config()

            if not config_data:
                return {"success": False, "error": "No ThingsBoard configuration found. Please save configuration first."}

            # Ensure docker-compose directory exists
            settings.DOCKER_COMPOSE_DIR.mkdir(parents=True, exist_ok=True)

            # Generate and write docker-compose.yml
            compose_content = self.generate_docker_compose(config_data)
            self._docker_compose_file.write_text(compose_content)

            logger.info(f"Docker compose file written to {self._docker_compose_file}")

            # Run docker-compose up
            result = subprocess.run(
                ["docker", "compose", "-f", str(self._docker_compose_file), "up", "-d"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(settings.DOCKER_COMPOSE_DIR)
            )

            if result.returncode != 0:
                logger.error(f"Docker compose up failed: {result.stderr}")
                return {"success": False, "error": f"Failed to start gateway: {result.stderr}"}

            logger.info("ThingsBoard Gateway deployed successfully")
            return {"success": True, "message": "Gateway deployed and started successfully"}

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout starting gateway"}
        except Exception as e:
            logger.error(f"Failed to deploy gateway: {e}")
            return {"success": False, "error": str(e)}

    def stop_gateway(self) -> Dict[str, Any]:
        """Stop the ThingsBoard Gateway."""
        try:
            if not self._docker_compose_file.exists():
                # Try stopping by container name
                result = subprocess.run(
                    ["docker", "stop", "tb-gateway"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    return {"success": True, "message": "Gateway stopped"}
                return {"success": False, "error": "No gateway running"}

            result = subprocess.run(
                ["docker", "compose", "-f", str(self._docker_compose_file), "down"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(settings.DOCKER_COMPOSE_DIR)
            )

            if result.returncode != 0:
                logger.error(f"Docker compose down failed: {result.stderr}")
                return {"success": False, "error": f"Failed to stop gateway: {result.stderr}"}

            logger.info("ThingsBoard Gateway stopped")
            return {"success": True, "message": "Gateway stopped successfully"}

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout stopping gateway"}
        except Exception as e:
            logger.error(f"Failed to stop gateway: {e}")
            return {"success": False, "error": str(e)}

    def get_gateway_status(self) -> Dict[str, Any]:
        """Get detailed gateway container status."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "tb-gateway"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return {
                    "running": False,
                    "status": "Not deployed",
                    "error": None
                }

            import json as json_module
            container_info = json_module.loads(result.stdout)[0]
            state = container_info.get("State", {})

            return {
                "running": state.get("Running", False),
                "status": state.get("Status", "unknown"),
                "started_at": state.get("StartedAt"),
                "health": state.get("Health", {}).get("Status"),
                "error": state.get("Error") if state.get("Error") else None
            }

        except Exception as e:
            return {
                "running": False,
                "status": "Error",
                "error": str(e)
            }

    def get_gateway_logs(self, lines: int = 100) -> Dict[str, Any]:
        """Get recent gateway logs."""
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(lines), "tb-gateway"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return {"success": False, "error": "Gateway not running", "logs": ""}

            # Combine stdout and stderr
            logs = result.stdout + result.stderr

            return {"success": True, "logs": logs}

        except Exception as e:
            return {"success": False, "error": str(e), "logs": ""}

    def download_ca_cert(self, platform_host: Optional[str] = None) -> Dict[str, Any]:
        """Download CA certificate from ThingsBoard platform."""
        try:
            import urllib.request
            import ssl

            # Use provided host or get from config
            if not platform_host:
                config = self._load_config()
                if config:
                    platform_host = config.get("host", "")

            if not platform_host:
                return {"success": False, "error": "No platform host specified"}

            # Build the URL for certificate download
            cert_url = f"https://{platform_host}/api/device-connectivity/mqtts/certificate/download"

            logger.info(f"Downloading CA certificate from {cert_url}")

            # Create SSL context that doesn't verify (for initial cert download)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            # Download certificate
            req = urllib.request.Request(cert_url)
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                cert_content = response.read().decode('utf-8')

            # Validate it looks like a certificate
            if "-----BEGIN CERTIFICATE-----" not in cert_content:
                return {"success": False, "error": "Downloaded content is not a valid certificate"}

            # Save the certificate
            self._ca_cert_file.write_text(cert_content)
            os.chmod(self._ca_cert_file, 0o600)

            logger.info("CA certificate downloaded and saved")
            return {
                "success": True,
                "message": "CA certificate downloaded successfully",
                "cert_path": str(self._ca_cert_file)
            }

        except urllib.error.HTTPError as e:
            logger.error(f"HTTP error downloading certificate: {e}")
            return {"success": False, "error": f"HTTP error: {e.code} - {e.reason}"}
        except urllib.error.URLError as e:
            logger.error(f"URL error downloading certificate: {e}")
            return {"success": False, "error": f"Connection error: {str(e.reason)}"}
        except Exception as e:
            logger.error(f"Error downloading certificate: {e}")
            return {"success": False, "error": str(e)}


# Global ThingsBoard service instance
thingsboard_service = ThingsBoardService()
