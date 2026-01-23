"""
ECO-IOT-GW Pydantic Models
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Authentication Models
# =============================================================================

class LoginRequest(BaseModel):
    """Login request model."""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Token response model."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Refresh token request model."""
    refresh_token: str


class UserInfo(BaseModel):
    """User information model."""
    username: str
    role: str
    last_login: Optional[datetime] = None


# =============================================================================
# Docker Models
# =============================================================================

class ContainerInfo(BaseModel):
    """Container information model."""
    id: str
    name: str
    image: str
    status: str
    state: str
    created: datetime
    ports: Dict[str, Any] = {}


class DockerComposeRequest(BaseModel):
    """Docker compose upload request."""
    content: str
    filename: str = "docker-compose.yml"


class DockerComposeResponse(BaseModel):
    """Docker compose response."""
    filename: str
    content: str
    last_modified: Optional[datetime] = None


class DockerStatusResponse(BaseModel):
    """Docker status response."""
    containers: List[ContainerInfo]
    compose_running: bool


# =============================================================================
# VPN Models
# =============================================================================

class VPNType(str, Enum):
    """VPN type enumeration."""
    OPENVPN = "openvpn"
    WIREGUARD = "wireguard"
    TAILSCALE = "tailscale"


class VPNConfigRequest(BaseModel):
    """VPN configuration upload request."""
    content: str
    filename: str
    vpn_type: VPNType


class VPNStatus(BaseModel):
    """VPN status model."""
    connected: bool
    vpn_type: Optional[VPNType] = None
    interface: Optional[str] = None
    ip_address: Optional[str] = None
    connected_since: Optional[datetime] = None
    bytes_sent: Optional[int] = None
    bytes_received: Optional[int] = None


class VPNAutostart(BaseModel):
    """VPN autostart configuration."""
    enabled: bool
    vpn_type: Optional[VPNType] = None


class TailscaleAuthRequest(BaseModel):
    """Tailscale authentication request."""
    auth_key: str = Field(..., min_length=1)


# =============================================================================
# Modem Models
# =============================================================================

class ModemStatus(BaseModel):
    """Modem status model."""
    connected: bool
    signal_strength: Optional[int] = None  # dBm
    signal_quality: Optional[int] = None  # Percentage
    network_type: Optional[str] = None  # LTE, 3G, etc.
    carrier: Optional[str] = None
    imei: Optional[str] = None
    imsi: Optional[str] = None
    iccid: Optional[str] = None
    ip_address: Optional[str] = None


class ModemConfig(BaseModel):
    """Modem configuration model."""
    apn: str = Field(..., min_length=1, max_length=100)
    username: Optional[str] = Field(None, max_length=50)
    password: Optional[str] = Field(None, max_length=50)
    pin: Optional[str] = Field(None, min_length=4, max_length=8)
    auto_connect: bool = True


# =============================================================================
# Serial Models
# =============================================================================

class SerialPort(BaseModel):
    """Serial port information."""
    device: str
    description: Optional[str] = None
    hwid: Optional[str] = None


class SerialConfig(BaseModel):
    """Serial port configuration."""
    port: str
    baudrate: int = Field(default=9600, ge=300, le=4000000)
    bytesize: int = Field(default=8, ge=5, le=8)
    parity: str = Field(default="N", pattern="^[NEOSM]$")
    stopbits: float = Field(default=1, ge=1, le=2)
    timeout: Optional[float] = Field(default=1.0, ge=0)

    @field_validator("baudrate")
    @classmethod
    def validate_baudrate(cls, v):
        valid_baudrates = [300, 600, 1200, 2400, 4800, 9600, 14400, 19200,
                         38400, 57600, 115200, 230400, 460800, 921600]
        if v not in valid_baudrates:
            raise ValueError(f"Baudrate must be one of {valid_baudrates}")
        return v


# =============================================================================
# WiFi AP Models
# =============================================================================

class WiFiAPStatus(BaseModel):
    """WiFi AP status model."""
    active: bool
    ssid: Optional[str] = None
    channel: Optional[int] = None
    clients_connected: int = 0


class WiFiAPConfig(BaseModel):
    """WiFi AP configuration model."""
    ssid: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=8, max_length=63)
    channel: int = Field(default=6, ge=1, le=13)
    hidden: bool = False


# =============================================================================
# System Models
# =============================================================================

class SystemStatus(BaseModel):
    """System status model."""
    hostname: str
    uptime: int  # seconds
    cpu_percent: float
    memory_total: int
    memory_used: int
    memory_percent: float
    disk_total: int
    disk_used: int
    disk_percent: float
    temperature: Optional[float] = None  # Celsius
    load_average: List[float]


class SystemRebootRequest(BaseModel):
    """System reboot request."""
    delay_seconds: int = Field(default=0, ge=0, le=300)


class UpdateStatus(BaseModel):
    """Update status model."""
    update_available: bool
    current_version: str
    latest_version: Optional[str] = None
    changelog: Optional[str] = None


class UpdateRequest(BaseModel):
    """Update request model."""
    version: Optional[str] = None  # None = latest


# =============================================================================
# Diagnostics Models
# =============================================================================

class ModbusValue(BaseModel):
    """Modbus value from gateway logs."""
    device: str
    register: str
    value: Any
    timestamp: datetime
    unit: Optional[str] = None


class GatewayLogEntry(BaseModel):
    """Gateway log entry model."""
    timestamp: datetime
    level: str
    message: str
    connector: Optional[str] = None


class ConnectivityStatus(BaseModel):
    """Connectivity status model."""
    vpn: bool
    modem: bool
    thingsboard: bool
    internet: bool
    last_check: datetime


# =============================================================================
# Watchdog Models
# =============================================================================

class ServiceStatus(BaseModel):
    """Service status model."""
    name: str
    active: bool
    running: bool
    enabled: bool
    failures: int = 0
    last_restart: Optional[datetime] = None


class WatchdogStatus(BaseModel):
    """Watchdog status model."""
    enabled: bool
    services: List[ServiceStatus]
    last_check: datetime


class WatchdogConfig(BaseModel):
    """Watchdog configuration model."""
    enabled: bool = True
    check_interval: int = Field(default=60, ge=10, le=600)
    vpn_max_failures: int = Field(default=3, ge=1, le=10)
    modem_max_failures: int = Field(default=3, ge=1, le=10)
    tb_max_failures: int = Field(default=5, ge=1, le=20)


# =============================================================================
# Audit Models
# =============================================================================

class AuditLogEntry(BaseModel):
    """Audit log entry model."""
    id: int
    timestamp: datetime
    username: str
    action: str
    resource: str
    details: Optional[Dict[str, Any]] = None
    ip_address: str
    success: bool


class AuditLogQuery(BaseModel):
    """Audit log query parameters."""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    username: Optional[str] = None
    action: Optional[str] = None
    resource: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


# =============================================================================
# ThingsBoard Models
# =============================================================================

class ThingsBoardSecurityType(str, Enum):
    """ThingsBoard security type enumeration."""
    ACCESS_TOKEN = "access_token"
    TLS_ACCESS_TOKEN = "tls_access_token"
    USERNAME_PASSWORD = "username_password"


class GatewayStatusState(str, Enum):
    """Gateway status state enumeration for state machine."""
    UNKNOWN = "unknown"
    STARTING = "starting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    STOPPED = "stopped"
    ERROR = "error"


class GatewayContainerStatus(BaseModel):
    """Gateway container status details."""
    running: bool = False
    status: str = "unknown"
    started_at: Optional[datetime] = None
    health: Optional[str] = None
    error: Optional[str] = None


class GatewayComprehensiveStatus(BaseModel):
    """Comprehensive gateway status with state machine."""
    state: GatewayStatusState = GatewayStatusState.UNKNOWN
    container: GatewayContainerStatus = GatewayContainerStatus()
    mqtt_connected: bool = False
    message: Optional[str] = None
    cached: bool = False
    cache_age_seconds: Optional[float] = None
    last_check: Optional[datetime] = None


class ThingsBoardConfig(BaseModel):
    """ThingsBoard configuration model."""
    host: str = Field(default="lb-mqtt.pke-iot.expert", min_length=1, max_length=255)
    port: int = Field(default=1883, ge=1, le=65535)
    security_type: ThingsBoardSecurityType = ThingsBoardSecurityType.ACCESS_TOKEN
    # Access Token security
    access_token: Optional[str] = Field(None, max_length=255)
    # TLS settings (for port 8883)
    use_tls: bool = False
    ca_cert: Optional[str] = None  # CA certificate content
    # Username/Password security
    client_id: Optional[str] = Field(None, max_length=255)
    username: Optional[str] = Field(None, max_length=255)
    password: Optional[str] = Field(None, max_length=255)


class ThingsBoardStatus(BaseModel):
    """ThingsBoard connection status model."""
    connected: bool
    host: Optional[str] = None
    port: Optional[int] = None
    security_type: Optional[ThingsBoardSecurityType] = None
    last_connected: Optional[datetime] = None
    error: Optional[str] = None


class ThingsBoardConfigResponse(BaseModel):
    """ThingsBoard config response (without sensitive data)."""
    configured: bool
    host: Optional[str] = None
    port: Optional[int] = None
    security_type: Optional[ThingsBoardSecurityType] = None
    use_tls: bool = False
    has_ca_cert: bool = False
    has_access_token: bool = False
    has_credentials: bool = False


# =============================================================================
# Generic Response Models
# =============================================================================

class SuccessResponse(BaseModel):
    """Generic success response."""
    success: bool = True
    message: str


class ErrorResponse(BaseModel):
    """Generic error response."""
    success: bool = False
    error: str
    detail: Optional[str] = None
