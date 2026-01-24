"""
ECO-IOT-GW NTP API
NTP time synchronization configuration and status
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..models.schemas import (
    ErrorResponse,
    SuccessResponse,
    NTPConfig,
    NTPConfigRequest,
    NTPStatus,
    NTPSource,
    TimezoneInfo,
    TimezoneRequest,
    UserInfo
)
from ..security.auth import get_current_user
from ..services.audit_service import audit_service
from ..services.ntp_service import ntp_service

logger = logging.getLogger(__name__)
router = APIRouter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    return client_ip


@router.get("/config", response_model=NTPConfig)
async def get_ntp_config(user: UserInfo = Depends(get_current_user)):
    """
    Get current NTP configuration.

    Returns the configured NTP servers and pools from chrony.conf.
    """
    try:
        config = await ntp_service.get_config()

        # Extract just addresses for the response
        servers = [s["address"] for s in config.get("servers", [])]
        pools = [p["address"] for p in config.get("pools", [])]

        return NTPConfig(servers=servers, pools=pools)

    except Exception as e:
        logger.error(f"Failed to get NTP config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/config", response_model=SuccessResponse)
async def update_ntp_config(
    request: Request,
    config: NTPConfigRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Update NTP configuration.

    Configure NTP servers and pools. Requires admin role.
    Restarts chrony service after update.

    - **servers**: List of NTP server addresses (max 10)
    - **pools**: List of NTP pool addresses (max 10)
    """
    client_ip = get_client_ip(request)

    # Require admin role for config changes
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        result = await ntp_service.set_config(
            servers=config.servers,
            pools=config.pools,
            username=user.username,
            ip_address=client_ip
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message", "Failed to update NTP config")
            )

        return SuccessResponse(message=result.get("message", "NTP configuration updated"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update NTP config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/status", response_model=NTPStatus)
async def get_ntp_status(user: UserInfo = Depends(get_current_user)):
    """
    Get NTP synchronization status.

    Returns sync status from chronyc tracking including offset, stratum,
    and leap status.
    """
    try:
        status_data = await ntp_service.get_status()

        return NTPStatus(
            synchronized=status_data.get("synced", False),
            reference_id=status_data.get("reference"),
            stratum=status_data.get("stratum"),
            system_time=status_data.get("offset"),
            last_offset=status_data.get("last_update"),
            frequency=status_data.get("frequency"),
            root_delay=status_data.get("root_delay"),
            root_dispersion=status_data.get("root_dispersion"),
            leap_status=status_data.get("leap_status"),
            error=status_data.get("error")
        )

    except Exception as e:
        logger.error(f"Failed to get NTP status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/sources", response_model=List[NTPSource])
async def get_ntp_sources(user: UserInfo = Depends(get_current_user)):
    """
    Get NTP sources status.

    Returns list of configured NTP sources with their sync status
    from chronyc sources.
    """
    try:
        sources = await ntp_service.get_sources()

        return [
            NTPSource(
                mode=s.get("mode", "?"),
                state=s.get("state", "?"),
                name=s.get("name", "unknown"),
                stratum=s.get("stratum"),
                poll=s.get("poll"),
                reach=s.get("reach"),
                last_rx=s.get("last_rx"),
                last_sample=s.get("offset"),
                is_selected=s.get("is_selected", False),
                is_combined=s.get("is_combined", False),
                is_reachable=s.get("is_reachable", True)
            )
            for s in sources
        ]

    except Exception as e:
        logger.error(f"Failed to get NTP sources: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/timezones", response_model=TimezoneInfo)
async def get_timezones(user: UserInfo = Depends(get_current_user)):
    """
    Get available timezones and current timezone.

    Returns list of all available timezones and the currently set timezone.
    """
    try:
        current = await ntp_service.get_current_timezone()
        available = await ntp_service.get_timezones()

        return TimezoneInfo(
            current=current or "UTC",
            available=available
        )

    except Exception as e:
        logger.error(f"Failed to get timezones: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/timezone")
async def get_current_timezone(user: UserInfo = Depends(get_current_user)):
    """
    Get current system timezone.

    Returns the currently configured system timezone.
    """
    try:
        timezone = await ntp_service.get_current_timezone()

        return {"timezone": timezone or "UTC"}

    except Exception as e:
        logger.error(f"Failed to get current timezone: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/timezone", response_model=SuccessResponse)
async def set_timezone(
    request: Request,
    data: TimezoneRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Set system timezone.

    Update the system timezone. Any authenticated user can set the timezone.

    - **timezone**: Timezone name (e.g., Europe/Berlin, America/New_York, UTC)
    """
    client_ip = get_client_ip(request)

    try:
        result = await ntp_service.set_timezone(
            timezone=data.timezone,
            username=user.username,
            ip_address=client_ip
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("message", "Failed to set timezone")
            )

        return SuccessResponse(message=result.get("message", f"Timezone set to {data.timezone}"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set timezone: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/restart", response_model=SuccessResponse)
async def restart_ntp_service(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Restart the NTP (chrony) service.

    Requires admin role.
    """
    client_ip = get_client_ip(request)

    # Require admin role for service restart
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        result = await ntp_service.restart_service()

        # Log audit
        audit_service.log(
            username=user.username,
            action="ntp_service_restart",
            resource="ntp",
            ip_address=client_ip,
            success=result.get("success", False),
            details={"message": result.get("message")}
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message", "Failed to restart NTP service")
            )

        return SuccessResponse(message=result.get("message", "NTP service restarted"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to restart NTP service: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
