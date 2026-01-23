"""
ECO-IOT-GW WiFi API
WLAN Access Point management
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..models.schemas import (
    ErrorResponse,
    SuccessResponse,
    UserInfo,
    WiFiAPConfig,
    WiFiAPStatus
)
from ..security.auth import get_current_user
from ..security.validators import validate_ssid, validate_password
from ..services.wifi_service import wifi_service

logger = logging.getLogger(__name__)
router = APIRouter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    return client_ip


def log_audit(username: str, action: str, ip: str, details: dict = None, success: bool = True):
    """Log audit event."""
    try:
        from ..services.audit_service import audit_service
        # Don't log password
        safe_details = {k: v for k, v in (details or {}).items()
                       if k != 'password'}
        audit_service.log(
            username=username,
            action=action,
            resource="wifi",
            ip_address=ip,
            success=success,
            details=safe_details
        )
    except Exception as e:
        logger.warning(f"Failed to log audit: {e}")


@router.get("/ap/status", response_model=WiFiAPStatus)
async def get_ap_status(user: UserInfo = Depends(get_current_user)):
    """
    Get WiFi Access Point status.

    Returns whether AP is active, SSID, channel, and connected clients.
    """
    try:
        return wifi_service.get_status()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/ap/config", response_model=WiFiAPConfig)
async def get_ap_config(user: UserInfo = Depends(get_current_user)):
    """
    Get WiFi AP configuration.

    Note: Password is masked for security.
    """
    try:
        config = wifi_service.get_config()
        config.password = "********"
        return config
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/ap/config", response_model=SuccessResponse)
async def set_ap_config(
    request: Request,
    config: WiFiAPConfig,
    user: UserInfo = Depends(get_current_user)
):
    """
    Update WiFi AP configuration.

    - **ssid**: Network name (1-32 characters)
    - **password**: WPA2 password (8-63 characters)
    - **channel**: WiFi channel (1-13)
    - **hidden**: Hide SSID from scan results
    """
    client_ip = get_client_ip(request)

    # Validate inputs
    try:
        validate_ssid(config.ssid)
        validate_password(config.password)
    except HTTPException:
        log_audit(user.username, "set_wifi_config", client_ip,
                 {"error": "validation_failed"}, success=False)
        raise

    try:
        wifi_service.set_config(config)
        log_audit(user.username, "set_wifi_config", client_ip, {
            "ssid": config.ssid,
            "channel": config.channel,
            "hidden": config.hidden
        })
        return SuccessResponse(message="WiFi AP configuration updated")

    except Exception as e:
        log_audit(user.username, "set_wifi_config", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/ap/start", response_model=SuccessResponse)
async def start_ap(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Start the WiFi Access Point.

    This will enable hostapd and dnsmasq services.
    """
    client_ip = get_client_ip(request)

    try:
        wifi_service.start()
        log_audit(user.username, "start_wifi_ap", client_ip)
        return SuccessResponse(message="WiFi AP started")

    except Exception as e:
        log_audit(user.username, "start_wifi_ap", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/ap/stop", response_model=SuccessResponse)
async def stop_ap(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Stop the WiFi Access Point.

    This will disable hostapd and dnsmasq services.
    """
    client_ip = get_client_ip(request)

    try:
        wifi_service.stop()
        log_audit(user.username, "stop_wifi_ap", client_ip)
        return SuccessResponse(message="WiFi AP stopped")

    except Exception as e:
        log_audit(user.username, "stop_wifi_ap", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/ap/restart", response_model=SuccessResponse)
async def restart_ap(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """Restart the WiFi Access Point."""
    client_ip = get_client_ip(request)

    try:
        wifi_service.restart()
        log_audit(user.username, "restart_wifi_ap", client_ip)
        return SuccessResponse(message="WiFi AP restarted")

    except Exception as e:
        log_audit(user.username, "restart_wifi_ap", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/ap/clients")
async def get_clients(user: UserInfo = Depends(get_current_user)):
    """
    Get list of connected WiFi clients.

    Returns MAC addresses and IP addresses of connected devices.
    """
    try:
        return {"clients": wifi_service.get_clients()}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
