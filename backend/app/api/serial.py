"""
ECO-IOT-GW Serial API
RS485 port configuration
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..config import settings
from ..models.schemas import (
    ErrorResponse,
    SerialConfig,
    SerialPort,
    SuccessResponse,
    UserInfo
)
from ..security.auth import get_current_user
from ..services.serial_service import serial_service

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
        audit_service.log(
            username=username,
            action=action,
            resource="serial",
            ip_address=ip,
            success=success,
            details=details
        )
    except Exception as e:
        logger.warning(f"Failed to log audit: {e}")


@router.get("/ports", response_model=List[SerialPort])
async def list_ports(user: UserInfo = Depends(get_current_user)):
    """
    List available serial ports.

    Returns all detected serial ports with their descriptions.
    """
    try:
        return serial_service.list_ports()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/config", response_model=SerialConfig)
async def get_config(user: UserInfo = Depends(get_current_user)):
    """
    Get current RS485 serial configuration.
    """
    try:
        return serial_service.get_config()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/config", response_model=SuccessResponse)
async def set_config(
    request: Request,
    config: SerialConfig,
    user: UserInfo = Depends(get_current_user)
):
    """
    Update RS485 serial configuration.

    - **port**: Serial port device (e.g., /dev/ttyAMA0)
    - **baudrate**: Communication speed (9600, 19200, 38400, etc.)
    - **bytesize**: Data bits (5, 6, 7, or 8)
    - **parity**: Parity (N=None, E=Even, O=Odd)
    - **stopbits**: Stop bits (1 or 2)
    - **timeout**: Read timeout in seconds
    """
    client_ip = get_client_ip(request)

    try:
        serial_service.set_config(config)
        log_audit(user.username, "set_serial_config", client_ip, {
            "port": config.port,
            "baudrate": config.baudrate,
            "parity": config.parity
        })
        return SuccessResponse(message="Serial configuration updated")

    except Exception as e:
        log_audit(user.username, "set_serial_config", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/test", response_model=SuccessResponse)
async def test_port(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Test the configured serial port.

    Opens the port with current settings to verify it works.
    """
    client_ip = get_client_ip(request)

    try:
        serial_service.test_port()
        log_audit(user.username, "test_serial_port", client_ip)
        return SuccessResponse(message="Serial port test successful")

    except Exception as e:
        log_audit(user.username, "test_serial_port", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
