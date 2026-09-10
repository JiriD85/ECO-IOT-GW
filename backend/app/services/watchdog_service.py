"""
ECO-IOT-GW Watchdog Service
Service monitoring and auto-recovery
"""
import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..models.schemas import ServiceStatus, WatchdogConfig, WatchdogStatus

logger = logging.getLogger(__name__)


class WatchdogService:
    """Service for monitoring and auto-recovery."""

    def __init__(self):
        self._config_file = settings.DATA_DIR / "watchdog_config.json"
        self._config: WatchdogConfig = WatchdogConfig()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._lifecycle_lock = threading.RLock()

        # Failure counters
        self._failures: Dict[str, int] = {
            "vpn": 0,
            "modem": 0,
            "gateway": 0
        }

        # Last restart times
        self._last_restart: Dict[str, Optional[datetime]] = {
            "vpn": None,
            "modem": None,
            "gateway": None
        }

        self._last_check = datetime.now()
        self._load_config()

    def _load_config(self):
        """Load watchdog configuration from disk."""
        if self._config_file.exists():
            try:
                with open(self._config_file) as f:
                    data = json.load(f)
                    self._config = WatchdogConfig(**data)
            except Exception as e:
                logger.warning(f"Failed to load watchdog config: {e}")

    def _save_config(self):
        """Save watchdog configuration to disk."""
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._config_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(self._config.model_dump()))
        temporary.replace(self._config_file)

    def get_config(self) -> WatchdogConfig:
        """Get current watchdog configuration."""
        return self._config

    def set_config(self, config: WatchdogConfig):
        """Persist the setting and apply it without concurrent start/stop races."""
        with self._lifecycle_lock:
            previous = self._config
            self._config = config
            try:
                self._save_config()
                if config.enabled and not self._running:
                    self.start()
                elif not config.enabled and self._running:
                    self.stop()
            except Exception:
                self._config = previous
                self._save_config()
                raise

    def get_status(self) -> WatchdogStatus:
        """Get watchdog status."""
        services = []

        # Check VPN service
        from .vpn_service import vpn_service
        vpn = vpn_service.get_status()
        vpn_status = {"active": vpn.connected, "running": vpn.connected,
                      "enabled": vpn_service.get_autostart().enabled}
        services.append(ServiceStatus(
            name="vpn",
            active=vpn_status["active"],
            running=vpn_status["running"],
            enabled=vpn_status["enabled"],
            failures=self._failures["vpn"],
            last_restart=self._last_restart["vpn"]
        ))

        # Check Gateway container
        gateway_running = self._check_gateway_container()
        services.append(ServiceStatus(
            name="gateway",
            active=gateway_running,
            running=gateway_running,
            enabled=True,
            failures=self._failures["gateway"],
            last_restart=self._last_restart["gateway"]
        ))

        # Check Modem
        modem_connected = self._check_modem()
        services.append(ServiceStatus(
            name="modem",
            active=modem_connected,
            running=modem_connected,
            enabled=True,
            failures=self._failures["modem"],
            last_restart=self._last_restart["modem"]
        ))

        return WatchdogStatus(
            enabled=self._running,
            services=services,
            last_check=self._last_check
        )

    def _check_service_status(self, service_name: str) -> Dict[str, bool]:
        """Check systemd service status."""
        result = {
            "active": False,
            "running": False,
            "enabled": False
        }

        try:
            # Check if active
            proc = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            result["active"] = proc.returncode == 0
            result["running"] = proc.returncode == 0

            # Check if enabled
            proc = subprocess.run(
                ["systemctl", "is-enabled", service_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            result["enabled"] = proc.returncode == 0

        except Exception as e:
            logger.warning(f"Failed to check service {service_name}: {e}")

        return result

    def _check_gateway_container(self) -> bool:
        """Check if Gateway container is running."""
        try:
            from .docker_service import docker_service
            containers = docker_service.get_containers()

            for container in containers:
                name = container.name.lower()
                if 'thingsboard' in name or 'gateway' in name:
                    return container.status == "running"

        except Exception as e:
            logger.warning(f"Failed to check gateway container: {e}")

        return False

    def _check_modem(self) -> bool:
        """Check if modem is connected."""
        try:
            from .modem_service import modem_service
            status = modem_service.get_status()
            return status.connected
        except Exception as e:
            logger.warning(f"Failed to check modem: {e}")
            return False

    def set_enabled(self, enabled: bool):
        with self._lifecycle_lock:
            self.set_config(self._config.model_copy(update={"enabled": enabled}))

    def start(self):
        with self._lifecycle_lock:
            """Start the watchdog."""
            if self._running or not self._config.enabled:
                return
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Watchdog is still stopping; retry shortly")
            self._stop_event.clear()
            self._running = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            logger.info("Watchdog started")

    def stop(self):
        with self._lifecycle_lock:
            """Stop the watchdog."""
            self._running = False
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=5)
            logger.info("Watchdog stopped")

    def _run(self):
        """Main watchdog loop."""
        while self._running:
            try:
                self._check_all()
                self._last_check = datetime.now()
            except Exception as e:
                logger.error(f"Watchdog check error: {e}")

            self._stop_event.wait(self._config.check_interval)

    def _check_all(self):
        """Check all monitored services."""
        # Check VPN
        vpn_ok = self._check_vpn_connectivity()
        with self._lock:
            if vpn_ok:
                self._failures["vpn"] = 0
            else:
                self._failures["vpn"] += 1
                if self._failures["vpn"] >= self._config.vpn_max_failures:
                    self._recover_vpn()

        if self._stop_event.is_set():
            return
        # Check Modem
        modem_ok = self._check_modem()
        with self._lock:
            if modem_ok:
                self._failures["modem"] = 0
            else:
                self._failures["modem"] += 1
                if self._failures["modem"] >= self._config.modem_max_failures:
                    self._recover_modem()

        if self._stop_event.is_set():
            return
        # Check Gateway
        gateway_ok = self._check_gateway_container()
        with self._lock:
            if gateway_ok:
                self._failures["gateway"] = 0
            else:
                self._failures["gateway"] += 1
                if self._failures["gateway"] >= self._config.tb_max_failures:
                    self._recover_gateway()

    def _check_vpn_connectivity(self) -> bool:
        """Check VPN connection is active."""
        try:
            from .vpn_service import vpn_service
            if not vpn_service.get_current_type():
                return True  # No VPN configured: there is nothing to recover.
            status = vpn_service.get_status()
            return status.connected
        except Exception:
            return False

    def _recover_vpn(self):
        """Attempt to recover VPN connection."""
        logger.warning("VPN recovery triggered")

        try:
            from .vpn_service import vpn_service
            vpn_service.disconnect()
            if self._stop_event.wait(2):
                return
            vpn_service.connect()

            self._last_restart["vpn"] = datetime.now()
            self._failures["vpn"] = 0

            logger.info("VPN recovery completed")

        except Exception as e:
            logger.error(f"VPN recovery failed: {e}")

    def _recover_modem(self):
        """Attempt to recover modem connection."""
        logger.warning("Modem recovery triggered")

        try:
            from .modem_service import modem_service
            modem_service.reset()
            if self._stop_event.wait(10):
                return
            modem_service.connect()

            self._last_restart["modem"] = datetime.now()
            self._failures["modem"] = 0

            logger.info("Modem recovery completed")

        except Exception as e:
            logger.error(f"Modem recovery failed: {e}")

    def _recover_gateway(self):
        """Attempt to recover Gateway container."""
        logger.warning("Gateway recovery triggered")

        try:
            from .docker_service import docker_service

            # Find and restart gateway container
            containers = docker_service.get_containers()
            for container in containers:
                name = container.name.lower()
                if 'thingsboard' in name or 'gateway' in name:
                    docker_service.restart_container(container.name)
                    break

            self._last_restart["gateway"] = datetime.now()
            self._failures["gateway"] = 0

            logger.info("Gateway recovery completed")

        except Exception as e:
            logger.error(f"Gateway recovery failed: {e}")

    def reset_counters(self):
        """Reset all failure counters."""
        with self._lock:
            for key in self._failures:
                self._failures[key] = 0
        logger.info("Failure counters reset")

    def trigger_recovery(self, service_name: str):
        """Manually trigger recovery for a service."""
        if service_name == "vpn":
            self._recover_vpn()
        elif service_name == "modem":
            self._recover_modem()
        elif service_name == "gateway":
            self._recover_gateway()
        else:
            raise ValueError(f"Unknown service: {service_name}")


# Global watchdog service instance
watchdog_service = WatchdogService()
