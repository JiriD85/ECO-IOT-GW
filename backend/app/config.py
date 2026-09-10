"""
ECO-IOT-GW Backend Configuration
"""
import logging
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# The placeholder secrets shipped in the code. A real device MUST override these
# (install.sh / provisioning/setup-secrets.sh generate per-device values into
# /etc/eco-iot-gw/secrets.env). They are duplicated here so the boot guard below
# can recognise "still on the shipped default" and refuse to start.
DEFAULT_JWT_SECRET = "change-me-in-production"
DEFAULT_AES_KEY = "change-me-in-production-32bytes!"
DEFAULT_ADMIN_PASSWORD = "admin"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "ECO-IOT-GW"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False

    # Paths
    BASE_DIR: Path = Path("/opt/eco-iot-gw")
    CONFIG_DIR: Path = Path("/etc/eco-iot-gw")
    LOG_DIR: Path = Path("/var/log/eco-iot-gw")
    DATA_DIR: Path = Path("/var/lib/eco-iot-gw")

    # Security
    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    AES_KEY: str = os.getenv("AES_KEY", "change-me-in-production-32bytes!")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin")
    # On-site login IS this local Linux account (verified against /etc/shadow).
    # Provisioned per device with a random password; once it exists the insecure
    # in-memory admin/admin fallback is dropped. See security/system_auth.py.
    LOCAL_ADMIN_USER: str = os.getenv("LOCAL_ADMIN_USER", "ecoadmin")

    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # Database
    DATABASE_URL: str = "sqlite:///./eco-iot-gw.db"

    # Docker
    DOCKER_COMPOSE_DIR: Path = Path("/var/lib/eco-iot-gw/docker-compose")
    DOCKER_SOCKET: str = "/var/run/docker.sock"

    # VPN
    VPN_CONFIG_DIR: Path = Path("/var/lib/eco-iot-gw/vpn")
    OPENVPN_CONFIG_DIR: Path = Path("/etc/openvpn/client")
    WIREGUARD_CONFIG_DIR: Path = Path("/etc/wireguard")

    # ThingsBoard Gateway
    TB_GATEWAY_CONFIG_DIR: Path = Path("/etc/thingsboard-gateway/config")
    TB_GATEWAY_LOG_DIR: Path = Path("/var/log/thingsboard-gateway")

    # Modem
    MODEM_DEFAULT_PORT: str = "/dev/ttyUSB2"
    MODEM_BAUDRATE: int = 115200

    # Serial
    SERIAL_DEFAULT_PORT: str = "/dev/ttyAMA0"
    SERIAL_DEFAULT_BAUDRATE: int = 9600


    # Watchdog
    WATCHDOG_CHECK_INTERVAL: int = 60
    WATCHDOG_VPN_MAX_FAILURES: int = 3
    WATCHDOG_MODEM_MAX_FAILURES: int = 3
    WATCHDOG_TB_MAX_FAILURES: int = 5

    # Audit
    AUDIT_DB_PATH: Path = Path("/var/lib/eco-iot-gw/audit/audit.db")
    AUDIT_RETENTION_DAYS: int = 90

    class Config:
        env_file = "/etc/eco-iot-gw/secrets.env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings."""
    return settings


def insecure_default_secrets() -> list[str]:
    """Names of security secrets still set to the shipped placeholder value."""
    bad = []
    if settings.JWT_SECRET == DEFAULT_JWT_SECRET:
        bad.append("JWT_SECRET")
    if settings.AES_KEY == DEFAULT_AES_KEY:
        bad.append("AES_KEY")
    return bad


def is_provisioned_device() -> bool:
    """True on a real gateway. The production config dir only exists on an
    installed device; dev laptops / CI don't have it, so defaults stay usable
    there without tripping the boot guard."""
    return settings.CONFIG_DIR.is_dir()


def assert_secure_secrets() -> None:
    """Fail closed if a provisioned device is still running on the shipped
    default JWT_SECRET / AES_KEY.

    A shared, source-controlled signing key means anyone with the repo can forge
    a valid session token for the device, so this is a hard stop rather than a
    warning. Generate real secrets with `sudo provisioning/setup-secrets.sh`
    (or a full install.sh run). Set ECO_ALLOW_DEFAULT_SECRETS=1 to bypass on a
    throwaway dev box that happens to have /etc/eco-iot-gw."""
    if os.getenv("ECO_ALLOW_DEFAULT_SECRETS") == "1":
        return
    bad = insecure_default_secrets()
    if bad and is_provisioned_device():
        names = ", ".join(bad)
        raise RuntimeError(
            f"Refusing to start: {names} still set to the shipped default. "
            f"Run `sudo provisioning/setup-secrets.sh` to generate per-device "
            f"secrets in {settings.CONFIG_DIR}/secrets.env, then restart. "
            f"(Override on a dev box with ECO_ALLOW_DEFAULT_SECRETS=1.)"
        )
