"""
ECO-IOT-GW Backend Configuration
"""
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "ECO-IOT-GW"
    APP_VERSION: str = "1.0.0"
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

    # WiFi AP
    HOSTAPD_CONFIG: Path = Path("/etc/hostapd/hostapd.conf")
    DNSMASQ_CONFIG: Path = Path("/etc/dnsmasq.conf")

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
