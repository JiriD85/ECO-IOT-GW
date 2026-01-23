"""
ECO-IOT-GW Modem API
Quectel modem management via AT commands and NetworkManager
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..config import settings
from ..models.schemas import (
    ErrorResponse,
    ModemConfig,
    ModemStatus,
    SuccessResponse,
    UserInfo
)
from ..security.auth import get_current_user
from ..security.validators import validate_apn
from ..services.modem_service import modem_service

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
        # Remove sensitive data
        safe_details = {k: v for k, v in (details or {}).items()
                       if k not in ('password', 'pin')}
        audit_service.log(
            username=username,
            action=action,
            resource="modem",
            ip_address=ip,
            success=success,
            details=safe_details
        )
    except Exception as e:
        logger.warning(f"Failed to log audit: {e}")


@router.get("/status", response_model=ModemStatus)
async def get_modem_status(user: UserInfo = Depends(get_current_user)):
    """
    Get modem status and signal information.

    Returns:
    - Connection state
    - Signal strength (dBm and quality percentage)
    - Network type (LTE, 3G, etc.)
    - Carrier name
    - IMEI, IMSI, ICCID
    - IP address if connected
    """
    try:
        return modem_service.get_status()
    except Exception as e:
        logger.error(f"Failed to get modem status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/config", response_model=ModemConfig)
async def get_modem_config(user: UserInfo = Depends(get_current_user)):
    """
    Get current modem configuration.

    Note: Password and PIN are not returned for security.
    """
    try:
        config = modem_service.get_config()
        # Mask sensitive fields
        if config.password:
            config.password = "********"
        if config.pin:
            config.pin = "****"
        return config
    except Exception as e:
        logger.error(f"Failed to get modem config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/config", response_model=SuccessResponse)
async def set_modem_config(
    request: Request,
    config: ModemConfig,
    user: UserInfo = Depends(get_current_user)
):
    """
    Update modem configuration.

    - **apn**: Access Point Name
    - **username**: APN username (optional)
    - **password**: APN password (optional)
    - **pin**: SIM PIN (optional)
    - **auto_connect**: Automatically connect on boot
    """
    client_ip = get_client_ip(request)

    # Validate APN
    try:
        validate_apn(config.apn)
    except HTTPException:
        log_audit(user.username, "set_modem_config", client_ip,
                 {"error": "invalid_apn"}, success=False)
        raise

    try:
        modem_service.set_config(config)
        log_audit(user.username, "set_modem_config", client_ip,
                 {"apn": config.apn, "auto_connect": config.auto_connect})
        return SuccessResponse(message="Modem configuration updated")

    except Exception as e:
        log_audit(user.username, "set_modem_config", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/connect", response_model=SuccessResponse)
async def connect_modem(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Establish modem connection.

    Uses the configured APN settings to connect.
    """
    client_ip = get_client_ip(request)

    try:
        modem_service.connect()
        log_audit(user.username, "modem_connect", client_ip)
        return SuccessResponse(message="Modem connection initiated")

    except Exception as e:
        log_audit(user.username, "modem_connect", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/disconnect", response_model=SuccessResponse)
async def disconnect_modem(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """Disconnect modem."""
    client_ip = get_client_ip(request)

    try:
        modem_service.disconnect()
        log_audit(user.username, "modem_disconnect", client_ip)
        return SuccessResponse(message="Modem disconnected")

    except Exception as e:
        log_audit(user.username, "modem_disconnect", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/reset", response_model=SuccessResponse)
async def reset_modem(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Reset modem.

    Sends AT+CFUN=1,1 to perform a soft reset.
    """
    client_ip = get_client_ip(request)

    try:
        modem_service.reset()
        log_audit(user.username, "modem_reset", client_ip)
        return SuccessResponse(message="Modem reset initiated")

    except Exception as e:
        log_audit(user.username, "modem_reset", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/signal")
async def get_signal(user: UserInfo = Depends(get_current_user)):
    """
    Get detailed signal information.

    Returns signal strength, quality, network type, and cell info.
    """
    try:
        return modem_service.get_signal_info()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/at")
async def send_at_command(
    request: Request,
    command: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Send raw AT command to modem (admin only).

    Warning: Use with caution. Incorrect commands can disrupt connectivity.
    """
    client_ip = get_client_ip(request)

    # Only allow admin users
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    # Block dangerous commands
    dangerous = ['AT+CFUN=0', 'AT+QPOWD', 'AT&F']
    if any(d in command.upper() for d in dangerous):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This command is not allowed"
        )

    try:
        response = modem_service.send_at_command(command)
        log_audit(user.username, "modem_at_command", client_ip,
                 {"command": command})
        return {"command": command, "response": response}

    except Exception as e:
        log_audit(user.username, "modem_at_command", client_ip,
                 {"command": command, "error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
