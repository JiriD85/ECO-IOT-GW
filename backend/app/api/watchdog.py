"""
ECO-IOT-GW Watchdog API
Service monitoring and auto-recovery status
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..config import settings
from ..models.schemas import (
    ErrorResponse,
    SuccessResponse,
    UserInfo,
    WatchdogConfig,
    WatchdogStatus
)
from ..security.auth import get_current_user
from ..services.watchdog_service import watchdog_service

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
            resource="watchdog",
            ip_address=ip,
            success=success,
            details=details
        )
    except Exception as e:
        logger.warning(f"Failed to log audit: {e}")


@router.get("/status", response_model=WatchdogStatus)
def get_watchdog_status(user: UserInfo = Depends(get_current_user)):
    """
    Get watchdog status for all monitored services.

    Returns status of each service including:
    - Whether service is active/running
    - Number of failures since last successful check
    - Last restart time
    """
    try:
        return watchdog_service.get_status()
    except Exception as e:
        logger.error(f"Failed to get watchdog status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/config", response_model=WatchdogConfig)
def get_watchdog_config(user: UserInfo = Depends(get_current_user)):
    """
    Get watchdog configuration.

    Returns current watchdog settings including check intervals
    and failure thresholds for automatic recovery actions.
    """
    try:
        return watchdog_service.get_config()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/config", response_model=SuccessResponse)
def set_watchdog_config(
    request: Request,
    config: WatchdogConfig,
    user: UserInfo = Depends(get_current_user)
):
    """
    Update watchdog configuration.

    - **enabled**: Enable/disable watchdog
    - **check_interval**: Seconds between health checks (10-600)
    - **vpn_max_failures**: Failures before VPN restart (1-10)
    - **modem_max_failures**: Failures before modem reset (1-10)
    - **tb_max_failures**: Failures before gateway restart (1-20)
    """
    client_ip = get_client_ip(request)

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        watchdog_service.set_config(config)
        log_audit(user.username, "set_watchdog_config", client_ip, {
            "enabled": config.enabled,
            "check_interval": config.check_interval
        })
        return SuccessResponse(message="Watchdog configuration updated")

    except Exception as e:
        log_audit(user.username, "set_watchdog_config", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/enable", response_model=SuccessResponse)
def enable_watchdog(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """Enable the watchdog."""
    client_ip = get_client_ip(request)

    try:
        watchdog_service.set_enabled(True)
        log_audit(user.username, "enable_watchdog", client_ip)
        return SuccessResponse(message="Watchdog enabled")

    except Exception as e:
        log_audit(user.username, "enable_watchdog", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/disable", response_model=SuccessResponse)
def disable_watchdog(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """Disable the watchdog."""
    client_ip = get_client_ip(request)

    try:
        watchdog_service.set_enabled(False)
        log_audit(user.username, "disable_watchdog", client_ip)
        return SuccessResponse(message="Watchdog disabled")

    except Exception as e:
        log_audit(user.username, "disable_watchdog", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/reset", response_model=SuccessResponse)
def reset_counters(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """Reset all failure counters."""
    client_ip = get_client_ip(request)

    try:
        watchdog_service.reset_counters()
        log_audit(user.username, "reset_watchdog_counters", client_ip)
        return SuccessResponse(message="Failure counters reset")

    except Exception as e:
        log_audit(user.username, "reset_watchdog_counters", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/trigger/{service_name}", response_model=SuccessResponse)
def trigger_recovery(
    request: Request,
    service_name: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Manually trigger recovery action for a service.

    Valid service names: vpn, modem, gateway
    """
    client_ip = get_client_ip(request)

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    valid_services = ["vpn", "modem", "gateway"]
    if service_name not in valid_services:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid service. Valid: {', '.join(valid_services)}"
        )

    try:
        watchdog_service.trigger_recovery(service_name)
        log_audit(user.username, "trigger_recovery", client_ip,
                 {"service": service_name})
        return SuccessResponse(message=f"Recovery triggered for {service_name}")

    except Exception as e:
        log_audit(user.username, "trigger_recovery", client_ip,
                 {"service": service_name, "error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
