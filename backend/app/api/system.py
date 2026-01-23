"""
ECO-IOT-GW System API
System status, reboot, and updates
"""
import logging
import os
import platform
import subprocess
from datetime import datetime
from typing import Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..config import settings
from ..models.schemas import (
    ErrorResponse,
    SuccessResponse,
    SystemRebootRequest,
    SystemStatus,
    UpdateRequest,
    UpdateStatus,
    UserInfo
)
from ..security.auth import get_current_user

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
            resource="system",
            ip_address=ip,
            success=success,
            details=details
        )
    except Exception as e:
        logger.warning(f"Failed to log audit: {e}")


def get_cpu_temperature() -> Optional[float]:
    """Get CPU temperature on Raspberry Pi."""
    try:
        temp_file = "/sys/class/thermal/thermal_zone0/temp"
        if os.path.exists(temp_file):
            with open(temp_file) as f:
                temp = int(f.read().strip()) / 1000.0
                return round(temp, 1)
    except Exception:
        pass
    return None


@router.get("/status", response_model=SystemStatus)
async def get_system_status(user: UserInfo = Depends(get_current_user)):
    """
    Get system status information.

    Returns CPU, memory, disk usage, temperature, and uptime.
    """
    try:
        # Get hostname
        hostname = platform.node()

        # Get uptime
        uptime = int(datetime.now().timestamp() - psutil.boot_time())

        # Get CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # Get memory info
        memory = psutil.virtual_memory()

        # Get disk info
        disk = psutil.disk_usage('/')

        # Get load average
        load = os.getloadavg()

        # Get temperature
        temperature = get_cpu_temperature()

        return SystemStatus(
            hostname=hostname,
            uptime=uptime,
            cpu_percent=cpu_percent,
            memory_total=memory.total,
            memory_used=memory.used,
            memory_percent=memory.percent,
            disk_total=disk.total,
            disk_used=disk.used,
            disk_percent=disk.percent,
            temperature=temperature,
            load_average=list(load)
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/reboot", response_model=SuccessResponse)
async def reboot_system(
    request: Request,
    data: SystemRebootRequest = SystemRebootRequest(),
    user: UserInfo = Depends(get_current_user)
):
    """
    Reboot the system.

    - **delay_seconds**: Delay before reboot (0-300 seconds)

    Requires admin role.
    """
    client_ip = get_client_ip(request)

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        log_audit(user.username, "system_reboot", client_ip,
                 {"delay": data.delay_seconds})

        if data.delay_seconds > 0:
            subprocess.Popen(
                ["shutdown", "-r", f"+{data.delay_seconds // 60}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return SuccessResponse(
                message=f"System will reboot in {data.delay_seconds} seconds"
            )
        else:
            subprocess.Popen(
                ["shutdown", "-r", "now"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return SuccessResponse(message="System is rebooting")

    except Exception as e:
        log_audit(user.username, "system_reboot", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/shutdown", response_model=SuccessResponse)
async def shutdown_system(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Shutdown the system.

    Requires admin role. Warning: System will need physical access to restart.
    """
    client_ip = get_client_ip(request)

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        log_audit(user.username, "system_shutdown", client_ip)

        subprocess.Popen(
            ["shutdown", "-h", "now"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return SuccessResponse(message="System is shutting down")

    except Exception as e:
        log_audit(user.username, "system_shutdown", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/update/status", response_model=UpdateStatus)
async def get_update_status(user: UserInfo = Depends(get_current_user)):
    """
    Check for available updates.
    """
    try:
        from ..services.update_service import update_service
        return update_service.check_updates()
    except Exception as e:
        return UpdateStatus(
            update_available=False,
            current_version=settings.APP_VERSION
        )


@router.post("/update", response_model=SuccessResponse)
async def start_update(
    request: Request,
    data: UpdateRequest = UpdateRequest(),
    user: UserInfo = Depends(get_current_user)
):
    """
    Start system update.

    - **version**: Specific version to update to (optional, defaults to latest)

    Requires admin role.
    """
    client_ip = get_client_ip(request)

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        from ..services.update_service import update_service

        log_audit(user.username, "system_update", client_ip,
                 {"version": data.version})

        update_service.start_update(data.version)
        return SuccessResponse(message="Update started")

    except Exception as e:
        log_audit(user.username, "system_update", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/rollback", response_model=SuccessResponse)
async def rollback_update(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Rollback to previous version.

    Requires admin role.
    """
    client_ip = get_client_ip(request)

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        from ..services.update_service import update_service

        log_audit(user.username, "system_rollback", client_ip)

        update_service.rollback()
        return SuccessResponse(message="Rollback initiated")

    except Exception as e:
        log_audit(user.username, "system_rollback", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/hostname")
async def get_hostname(user: UserInfo = Depends(get_current_user)):
    """Get system hostname."""
    return {"hostname": platform.node()}


@router.put("/hostname", response_model=SuccessResponse)
async def set_hostname(
    request: Request,
    hostname: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Set system hostname.

    Requires admin role.
    """
    client_ip = get_client_ip(request)

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    # Validate hostname
    import re
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$', hostname):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hostname format"
        )

    try:
        subprocess.run(["hostnamectl", "set-hostname", hostname], check=True)
        log_audit(user.username, "set_hostname", client_ip, {"hostname": hostname})
        return SuccessResponse(message=f"Hostname set to {hostname}")

    except Exception as e:
        log_audit(user.username, "set_hostname", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/time")
async def get_system_time(user: UserInfo = Depends(get_current_user)):
    """Get system time information."""
    try:
        result = subprocess.run(
            ["timedatectl", "show", "--no-pager"],
            capture_output=True,
            text=True,
            check=True
        )

        info = {}
        for line in result.stdout.split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                info[key] = value

        return {
            "timezone": info.get("Timezone"),
            "local_time": datetime.now().isoformat(),
            "utc_time": datetime.utcnow().isoformat(),
            "ntp_enabled": info.get("NTP") == "yes",
            "ntp_synced": info.get("NTPSynchronized") == "yes"
        }

    except Exception as e:
        return {
            "local_time": datetime.now().isoformat(),
            "error": str(e)
        }


@router.put("/timezone", response_model=SuccessResponse)
async def set_timezone(
    request: Request,
    timezone: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Set system timezone.

    Example: Europe/Berlin, America/New_York, UTC
    """
    client_ip = get_client_ip(request)

    try:
        subprocess.run(
            ["timedatectl", "set-timezone", timezone],
            check=True,
            capture_output=True
        )
        log_audit(user.username, "set_timezone", client_ip, {"timezone": timezone})
        return SuccessResponse(message=f"Timezone set to {timezone}")

    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timezone: {timezone}"
        )
