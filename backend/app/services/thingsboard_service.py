"""
ECO-IOT-GW ThingsBoard Service
ThingsBoard Gateway connection configuration with State Machine, Caching and Circuit Breaker
"""
import json
import logging
import os
import re
import socket
import subprocess
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..config import settings
from ..models.schemas import (
    GatewayComprehensiveStatus,
    GatewayContainerStatus,
    GatewayStatusState,
    ThingsBoardConfig,
    ThingsBoardConfigResponse,
    ThingsBoardSecurityType,
    ThingsBoardStatus,
)
from ..security.crypto import decrypt_sensitive_data, encrypt_sensitive_data

logger = logging.getLogger(__name__)


# =============================================================================
# Caching Infrastructure
# =============================================================================

class CachedValue:
    """Thread-safe cached value with TTL."""

    def __init__(self, ttl_seconds: float = 30.0):
        self._value: Any = None
        self._ttl = ttl_seconds
        self._timestamp: float = 0.0
        self._lock = threading.Lock()

    def get(self) -> Tuple[Any, bool, float]:
        """Get cached value. Returns (value, is_valid, age_seconds)."""
        with self._lock:
            age = time.time() - self._timestamp
            is_valid = self._value is not None and age < self._ttl
            return self._value, is_valid, age

    def set(self, value: Any) -> None:
        """Set cached value."""
        with self._lock:
            self._value = value
            self._timestamp = time.time()

    def invalidate(self) -> None:
        """Invalidate cache."""
        with self._lock:
            self._timestamp = 0.0


# =============================================================================
# Circuit Breaker
# =============================================================================

class CircuitBreaker:
    """Circuit breaker pattern for handling repeated failures."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 3, reset_timeout: float = 60.0):
        self._state = self.CLOSED
        self._failure_count = 0
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Get current circuit state."""
        with self._lock:
            if self._state == self.OPEN:
                # Check if reset timeout has passed
                if time.time() - self._last_failure_time >= self._reset_timeout:
                    self._state = self.HALF_OPEN
            return self._state

    def can_execute(self) -> bool:
        """Check if operation can be executed."""
        state = self.state
        return state in (self.CLOSED, self.HALF_OPEN)

    def record_success(self) -> None:
        """Record successful operation."""
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        """Record failed operation."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self._failure_threshold:
                self._state = self.OPEN
                logger.warning(f"Circuit breaker opened after {self._failure_count} failures")

    def reset(self) -> None:
        """Reset circuit breaker."""
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED
            self._last_failure_time = 0.0


class ThingsBoardService:
    """Service for ThingsBoard Gateway configuration with state machine and caching."""

    # Exact container names to match (avoids matching unrelated containers)
    GATEWAY_CONTAINER_NAMES = ["tb-gateway", "thingsboard-gateway"]

    # Log patterns for connection state detection (ordered by priority)
    LOG_PATTERNS = {
        "connected": [
            re.compile(r"Connected to ThingsBoard", re.IGNORECASE),
            re.compile(r"MQTT.?client.?connected", re.IGNORECASE),
            re.compile(r"Successfully connected to", re.IGNORECASE),
            re.compile(r"connection established", re.IGNORECASE),
        ],
        "starting": [
            re.compile(r"Connecting to", re.IGNORECASE),
            re.compile(r"Starting MQTT", re.IGNORECASE),
            re.compile(r"Initializing gateway", re.IGNORECASE),
        ],
        "disconnected": [
            re.compile(r"Connection lost", re.IGNORECASE),
            re.compile(r"Disconnected from", re.IGNORECASE),
            re.compile(r"MQTT.?client.?disconnected", re.IGNORECASE),
        ],
        "error": [
            re.compile(r"Connection refused", re.IGNORECASE),
            re.compile(r"Connection failed", re.IGNORECASE),
            re.compile(r"Authentication failed", re.IGNORECASE),
            re.compile(r"Connection timed? ?out", re.IGNORECASE),  # Match "timed out" and "timeout"
            re.compile(r"TimeoutError", re.IGNORECASE),
            re.compile(r"Could not connect", re.IGNORECASE),
            re.compile(r"\|ERROR\|.*connect", re.IGNORECASE),  # Match ERROR level log entries about connection
        ],
    }

    def __init__(self):
        self._config_file = settings.DATA_DIR / "thingsboard" / "tb_config.json"
        self._ca_cert_file = settings.DATA_DIR / "thingsboard" / "ca.pem"
        self._gateway_config_file = settings.TB_GATEWAY_CONFIG_DIR / "tb_gateway.json"
        self._docker_compose_file = settings.DOCKER_COMPOSE_DIR / "docker-compose.yml"

        # Caching and circuit breaker
        self._status_cache = CachedValue(ttl_seconds=30.0)
        self._circuit_breaker = CircuitBreaker(failure_threshold=3, reset_timeout=60.0)

        # Ensure directories exist
        self._config_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> Optional[Dict[str, Any]]:
        """Load configuration from disk."""
        if self._gateway_config_file.exists():
            active = json.loads(self._gateway_config_file.read_text())['thingsboard']
            security = active.get('security', {})
            kind = security.get('type', 'accessToken')
            result = {'host': active.get('host'), 'port': active.get('port', 1883),
                      'security_type': {'accessToken': 'access_token', 'tlsAccessToken': 'tls_access_token',
                                        'usernamePassword': 'username_password'}.get(kind, 'access_token'),
                      'use_tls': bool(active.get('ssl') or kind == 'tlsAccessToken')}
            for source, target in [('accessToken', 'access_token'), ('username', 'username'), ('password', 'password')]:
                if security.get(source):
                    result[target] = encrypt_sensitive_data(security[source])
            result['client_id'] = security.get('clientId')
            return result
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
        if not self._gateway_config_file.exists():
            raise RuntimeError("Install the gateway with tui.js before changing its connection")
        active = json.loads(self._gateway_config_file.read_text())
        tb = active['thingsboard']
        previous = self._load_config()
        # Preserve the installed TLS configuration; certificate/type migration requires
        # a tested gateway release rather than guessed security keys.
        if config.ca_cert or (previous['use_tls'] and config.security_type.value != previous['security_type']) or config.use_tls != previous['use_tls'] or config.security_type == ThingsBoardSecurityType.TLS_ACCESS_TOKEN and previous['security_type'] != 'tls_access_token':
            raise RuntimeError("TLS changes require gateway provisioning; existing TLS settings were retained")
        security = dict(tb.get('security', {}))
        kinds = {'access_token': 'accessToken', 'tls_access_token': 'tlsAccessToken', 'username_password': 'usernamePassword'}
        kind = kinds[config.security_type.value]
        if security.get('type') != kind:
            security = {'type': kind}
        pairs = [('access_token', 'accessToken')] if kind != 'usernamePassword' else [('username', 'username'), ('password', 'password'), ('client_id', 'clientId')]
        for field, key in pairs:
            value = getattr(config, field)
            if value:
                security[key] = value
        if not (security.get('accessToken') or security.get('username')):
            raise ValueError("Credentials are required when changing authentication type")
        tb.update(host=config.host, port=config.port, security=security)
        # Write only connection fields; retain observer, devices, timing and statistics.
        import tempfile
        mode = self._gateway_config_file.stat()
        fd, temporary = tempfile.mkstemp(dir=self._gateway_config_file.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(active, stream, indent=2)
            os.chmod(temporary, mode.st_mode & 0o777)
            if hasattr(os, 'chown'):
                os.chown(temporary, mode.st_uid, mode.st_gid)
            os.replace(temporary, self._gateway_config_file)
        finally:
            Path(temporary).unlink(missing_ok=True)

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

        # Format devices section - must be valid YAML list or empty
        if device_lines:
            devices_section = "    devices:\n" + "\n".join(device_lines)
        else:
            devices_section = "    # No serial devices detected - devices section omitted"

        # Generate docker-compose.yml
        compose_content = f'''version: '3.4'
services:
  tb-gateway:
    image: thingsboard/tb-gateway:3.7-stable
    container_name: tb-gateway
    restart: always

    # Serial device mappings
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
            subprocess.run(['docker', 'start', 'tb-gateway'], check=True, capture_output=True, timeout=60)
            return {'success': True, 'message': 'Installed gateway started'}
        except Exception:
            return {'success': False, 'error': 'Could not start the installed gateway. Use tui.js to install or repair it.'}

    def stop_gateway(self) -> Dict[str, Any]:
        """Stop the ThingsBoard Gateway."""
        try:
            subprocess.run(['docker', 'stop', 'tb-gateway'], check=True, capture_output=True, timeout=60)
            return {'success': True, 'message': 'Gateway stopped'}
        except Exception:
            return {'success': False, 'error': 'Could not stop the installed gateway'}

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

    # =========================================================================
    # Comprehensive Gateway Status with State Machine
    # =========================================================================

    def _find_gateway_container(self) -> Optional[Dict[str, Any]]:
        """Find the gateway container by exact name matching."""
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                return None

            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                try:
                    container = json.loads(line)
                    container_name = container.get("Names", "")
                    # Exact name matching (avoid 'thingsboard' in name issues)
                    if container_name in self.GATEWAY_CONTAINER_NAMES:
                        return container
                except json.JSONDecodeError:
                    continue
            return None
        except Exception as e:
            logger.debug(f"Error finding gateway container: {e}")
            return None

    def _get_container_status(self) -> GatewayContainerStatus:
        """Get detailed container status using docker inspect."""
        for name in self.GATEWAY_CONTAINER_NAMES:
            try:
                result = subprocess.run(
                    ["docker", "inspect", name],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    container_info = json.loads(result.stdout)[0]
                    state = container_info.get("State", {})

                    started_at = None
                    if state.get("StartedAt"):
                        try:
                            started_at = datetime.fromisoformat(
                                state["StartedAt"].replace("Z", "+00:00")
                            )
                        except (ValueError, TypeError):
                            pass

                    health_status = None
                    if "Health" in state:
                        health_status = state["Health"].get("Status")

                    return GatewayContainerStatus(
                        running=state.get("Running", False),
                        status=state.get("Status", "unknown"),
                        started_at=started_at,
                        health=health_status,
                        error=state.get("Error") or None
                    )
            except Exception as e:
                logger.debug(f"Error inspecting container {name}: {e}")
                continue

        return GatewayContainerStatus(running=False, status="not_found")

    def _probe_mqtt_connection(self, host: str, port: int, timeout: int = 5) -> bool:
        """TCP probe to test MQTT port connectivity."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.debug(f"MQTT probe failed: {e}")
            return False

    def _analyze_logs_for_state(self, logs: str) -> Tuple[Optional[GatewayStatusState], Optional[str]]:
        """Analyze logs to determine connection state. Returns (state, message)."""
        if not logs:
            return None, None

        # Check lines from most recent first
        lines = logs.strip().split('\n')
        lines.reverse()

        for line in lines[:50]:  # Only check last 50 lines
            # Check error patterns first (higher priority)
            for pattern in self.LOG_PATTERNS["error"]:
                if pattern.search(line):
                    # Extract relevant part of the message
                    return GatewayStatusState.ERROR, line.strip()[-100:]

            # Check connected
            for pattern in self.LOG_PATTERNS["connected"]:
                if pattern.search(line):
                    return GatewayStatusState.CONNECTED, "MQTT connected"

            # Check disconnected
            for pattern in self.LOG_PATTERNS["disconnected"]:
                if pattern.search(line):
                    return GatewayStatusState.DISCONNECTED, "Connection lost"

            # Check starting
            for pattern in self.LOG_PATTERNS["starting"]:
                if pattern.search(line):
                    return GatewayStatusState.STARTING, "Establishing connection..."

        return None, None

    def _get_recent_logs(self, lines: int = 50) -> str:
        """Get recent logs from gateway container."""
        for name in self.GATEWAY_CONTAINER_NAMES:
            try:
                result = subprocess.run(
                    ["docker", "logs", "--tail", str(lines), name],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    return result.stdout + result.stderr
            except Exception:
                continue
        return ""

    def get_comprehensive_status(self, force_refresh: bool = False) -> GatewayComprehensiveStatus:
        """
        Get comprehensive gateway status with multi-level health checks.

        Health check strategy (in order):
        1. Docker container status (fast, reliable)
        2. Docker health check (if configured)
        3. TCP MQTT probe (active connection test)
        4. Log analysis (fallback)
        """
        # Check cache first
        if not force_refresh:
            cached_value, is_valid, age = self._status_cache.get()
            if is_valid and cached_value:
                cached_value.cached = True
                cached_value.cache_age_seconds = round(age, 1)
                return cached_value

        # Check circuit breaker
        if not self._circuit_breaker.can_execute():
            logger.debug("Circuit breaker is open, returning cached/error status")
            cached_value, _, age = self._status_cache.get()
            if cached_value:
                cached_value.cached = True
                cached_value.cache_age_seconds = round(age, 1)
                cached_value.message = "Circuit breaker open, using cached status"
                return cached_value
            return GatewayComprehensiveStatus(
                state=GatewayStatusState.ERROR,
                message="Service temporarily unavailable (circuit breaker open)"
            )

        try:
            # Step 1: Container status
            container_status = self._get_container_status()

            if not container_status.running:
                status = GatewayComprehensiveStatus(
                    state=GatewayStatusState.STOPPED,
                    container=container_status,
                    mqtt_connected=False,
                    message="Gateway container not running",
                    last_check=datetime.now()
                )
                self._status_cache.set(status)
                self._circuit_breaker.record_success()
                return status

            # Step 2: Check Docker health (if available)
            if container_status.health == "healthy":
                # Container reports healthy - likely connected
                mqtt_connected = True
                state = GatewayStatusState.CONNECTED
                message = "Container health: healthy"
            elif container_status.health == "unhealthy":
                mqtt_connected = False
                state = GatewayStatusState.ERROR
                message = "Container health: unhealthy"
            elif container_status.health == "starting":
                mqtt_connected = False
                state = GatewayStatusState.STARTING
                message = "Container starting..."
            else:
                # No health check configured, proceed to other checks
                mqtt_connected = False
                state = GatewayStatusState.UNKNOWN
                message = None

            # Step 3: TCP MQTT probe (if we don't have definitive state)
            if state == GatewayStatusState.UNKNOWN:
                config = self._load_config()
                if config:
                    host = config.get("host", "")
                    port = config.get("port", 1883)
                    if host and self._probe_mqtt_connection(host, port):
                        # Port is reachable, but doesn't confirm gateway connection
                        # Continue to log analysis
                        pass
                    else:
                        # MQTT port not reachable
                        state = GatewayStatusState.DISCONNECTED
                        message = f"Cannot reach MQTT broker at {host}:{port}"

            # Step 4: Log analysis (fallback or confirmation)
            if state == GatewayStatusState.UNKNOWN or message is None:
                logs = self._get_recent_logs(50)
                log_state, log_message = self._analyze_logs_for_state(logs)

                if log_state:
                    state = log_state
                    message = log_message
                    mqtt_connected = (state == GatewayStatusState.CONNECTED)
                elif state == GatewayStatusState.UNKNOWN:
                    # Container running but no clear state
                    state = GatewayStatusState.STARTING
                    message = "Waiting for gateway status..."

            # Check container uptime for starting state
            if container_status.started_at:
                uptime_seconds = (datetime.now(container_status.started_at.tzinfo or None)
                                  - container_status.started_at).total_seconds()
                if uptime_seconds < 30 and state not in (GatewayStatusState.ERROR,):
                    state = GatewayStatusState.STARTING
                    message = message or "Gateway initializing..."

            status = GatewayComprehensiveStatus(
                state=state,
                container=container_status,
                mqtt_connected=mqtt_connected,
                message=message,
                cached=False,
                cache_age_seconds=0,
                last_check=datetime.now()
            )

            self._status_cache.set(status)
            self._circuit_breaker.record_success()
            return status

        except Exception as e:
            logger.error(f"Error getting comprehensive status: {e}")
            self._circuit_breaker.record_failure()

            # Return error status
            return GatewayComprehensiveStatus(
                state=GatewayStatusState.ERROR,
                message=f"Error checking status: {str(e)}",
                last_check=datetime.now()
            )

    def invalidate_status_cache(self) -> None:
        """Invalidate the status cache (e.g., after config change)."""
        self._status_cache.invalidate()

    def reset_circuit_breaker(self) -> None:
        """Reset the circuit breaker (e.g., for manual recovery)."""
        self._circuit_breaker.reset()


# Global ThingsBoard service instance
thingsboard_service = ThingsBoardService()
