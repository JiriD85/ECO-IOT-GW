"""
ECO-IOT-GW Input Validators Module
Security-focused input validation
"""
import re
from typing import Any, List, Optional

from fastapi import HTTPException, status


# Regex patterns
SAFE_FILENAME_PATTERN = re.compile(r'^[\w\-. ]+$')
SAFE_PATH_PATTERN = re.compile(r'^[\w\-./]+$')
IP_ADDRESS_PATTERN = re.compile(
    r'^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
)
HOSTNAME_PATTERN = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
)
APN_PATTERN = re.compile(r'^[a-zA-Z0-9\-_.]+$')
SSID_PATTERN = re.compile(r'^[\w\-. ]+$')


# Dangerous patterns to block
SHELL_INJECTION_PATTERNS = [
    r'[;&|`$]',  # Shell metacharacters
    r'\$\(',     # Command substitution
    r'>\s*/',    # Redirect to root
    r'<\s*/',    # Read from root
    r'\.\.',     # Path traversal
    r'\/etc\/',  # System files
    r'\/var\/',  # Var files
    r'\/root',   # Root home
    r'rm\s+-rf', # Dangerous rm
    r'mkfs',     # Format disk
    r'dd\s+if',  # dd command
]


def validate_filename(filename: str, allowed_extensions: Optional[List[str]] = None) -> str:
    """Validate a filename for security."""
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename cannot be empty"
        )

    # Check for path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: path traversal not allowed"
        )

    # Check against safe pattern
    if not SAFE_FILENAME_PATTERN.match(filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: contains forbidden characters"
        )

    # Check extension if specified
    if allowed_extensions:
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file extension. Allowed: {', '.join(allowed_extensions)}"
            )

    return filename


def validate_path(path: str, allowed_prefixes: Optional[List[str]] = None) -> str:
    """Validate a file path for security."""
    if not path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path cannot be empty"
        )

    # Normalize path
    import os
    normalized = os.path.normpath(path)

    # Check for path traversal
    if '..' in normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path: path traversal not allowed"
        )

    # Check allowed prefixes
    if allowed_prefixes:
        if not any(normalized.startswith(prefix) for prefix in allowed_prefixes):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid path: outside allowed directories"
            )

    return normalized


def validate_shell_input(value: str) -> str:
    """Validate input that might be used in shell commands."""
    if not value:
        return value

    for pattern in SHELL_INJECTION_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid input: potentially dangerous characters detected"
            )

    return value


def validate_ip_address(ip: str) -> str:
    """Validate an IPv4 address."""
    if not IP_ADDRESS_PATTERN.match(ip):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid IP address format"
        )
    return ip


def validate_hostname(hostname: str) -> str:
    """Validate a hostname."""
    if len(hostname) > 253:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hostname too long (max 253 characters)"
        )

    if not HOSTNAME_PATTERN.match(hostname):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hostname format"
        )

    return hostname


def validate_apn(apn: str) -> str:
    """Validate an APN string."""
    if not apn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="APN cannot be empty"
        )

    if len(apn) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="APN too long (max 100 characters)"
        )

    if not APN_PATTERN.match(apn):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid APN format"
        )

    return apn


def validate_ssid(ssid: str) -> str:
    """Validate a WiFi SSID."""
    if not ssid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSID cannot be empty"
        )

    if len(ssid) > 32:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSID too long (max 32 characters)"
        )

    if not SSID_PATTERN.match(ssid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid SSID format"
        )

    return ssid


def validate_password(password: str, min_length: int = 8) -> str:
    """Validate a password meets requirements."""
    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password cannot be empty"
        )

    if len(password) < min_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {min_length} characters"
        )

    return password


def validate_docker_compose(content: str) -> str:
    """Validate docker-compose.yml content."""
    import yaml

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Docker compose content cannot be empty"
        )

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid YAML format: {str(e)}"
        )

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid docker-compose format: must be a YAML object"
        )

    # Check for required keys
    if 'services' not in parsed and 'version' not in parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid docker-compose format: missing services section"
        )

    # Check for dangerous mounts
    dangerous_mounts = ['/etc', '/root', '/boot', '/sys', '/proc']
    services = parsed.get('services', {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        volumes = service_config.get('volumes', [])
        for volume in volumes:
            if isinstance(volume, str):
                host_path = volume.split(':')[0]
                for dangerous in dangerous_mounts:
                    if host_path.startswith(dangerous):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Dangerous volume mount not allowed: {host_path}"
                        )

    return content


def validate_vpn_config(content: str, vpn_type: str) -> str:
    """Validate VPN configuration content."""
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="VPN configuration cannot be empty"
        )

    if vpn_type == "openvpn":
        # Basic OpenVPN config validation
        required_directives = ['client', 'remote']
        for directive in required_directives:
            if directive not in content.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid OpenVPN config: missing '{directive}' directive"
                )

    elif vpn_type == "wireguard":
        # Basic WireGuard config validation
        if '[Interface]' not in content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid WireGuard config: missing [Interface] section"
            )
        if '[Peer]' not in content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid WireGuard config: missing [Peer] section"
            )

    return content


def sanitize_log_message(message: str) -> str:
    """Sanitize a message for logging (remove sensitive data)."""
    # Patterns for sensitive data
    sensitive_patterns = [
        (r'password["\']?\s*[:=]\s*["\']?[^"\'\s,}]+', 'password=***'),
        (r'key["\']?\s*[:=]\s*["\']?[^"\'\s,}]+', 'key=***'),
        (r'secret["\']?\s*[:=]\s*["\']?[^"\'\s,}]+', 'secret=***'),
        (r'token["\']?\s*[:=]\s*["\']?[^"\'\s,}]+', 'token=***'),
        (r'api_key["\']?\s*[:=]\s*["\']?[^"\'\s,}]+', 'api_key=***'),
    ]

    result = message
    for pattern, replacement in sensitive_patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result
