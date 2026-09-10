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
def list_ports(user: UserInfo = Depends(get_current_user)):
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
def get_config(user: UserInfo = Depends(get_current_user)):
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
def set_config(
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
    raise HTTPException(status_code=410, detail="Serial settings are managed by the active ThingsBoard connector")


@router.post("/test", response_model=SuccessResponse)
def test_port(request: Request, user: UserInfo = Depends(get_current_user)):
    raise HTTPException(status_code=410, detail="Direct port tests are retired; use the live meter status")
