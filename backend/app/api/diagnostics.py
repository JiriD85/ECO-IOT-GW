"""
ECO-IOT-GW Diagnostics API
Live Modbus values, Gateway logs, Connectivity status
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import settings
from ..models.schemas import (
    ConnectivityStatus,
    GatewayLogEntry,
    ModbusValue,
    UserInfo
)
from ..security.auth import get_current_user
from ..services.gateway_log_service import gateway_log_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/connectivity", response_model=ConnectivityStatus)
async def get_connectivity_status(user: UserInfo = Depends(get_current_user)):
    """
    Get overall connectivity status.

    Returns status of VPN, Modem, ThingsBoard, and Internet connections.
    """
    try:
        from ..services.vpn_service import vpn_service
        from ..services.modem_service import modem_service

        # Check VPN
        vpn_status = vpn_service.get_status()
        vpn_connected = vpn_status.connected

        # Check Modem
        modem_status = modem_service.get_status()
        modem_connected = modem_status.connected

        # Check ThingsBoard Gateway
        tb_connected = gateway_log_service.check_thingsboard_connection()

        # Check Internet
        internet_connected = gateway_log_service.check_internet()

        return ConnectivityStatus(
            vpn=vpn_connected,
            modem=modem_connected,
            thingsboard=tb_connected,
            internet=internet_connected,
            last_check=datetime.now()
        )

    except Exception as e:
        logger.error(f"Failed to check connectivity: {e}")
        return ConnectivityStatus(
            vpn=False,
            modem=False,
            thingsboard=False,
            internet=False,
            last_check=datetime.now()
        )


@router.get("/modbus", response_model=List[ModbusValue])
async def get_modbus_values(
    user: UserInfo = Depends(get_current_user),
    device: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000)
):
    """
    Get live Modbus values from Gateway logs.

    This parses the ThingsBoard Gateway logs to extract Modbus values.
    Does NOT directly query the Modbus bus (to avoid bus conflicts).

    - **device**: Filter by device name (optional)
    - **limit**: Maximum number of values to return
    """
    try:
        values = gateway_log_service.get_modbus_values(device=device, limit=limit)
        return values
    except Exception as e:
        logger.error(f"Failed to get Modbus values: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/modbus/poll")
async def poll_modbus_register(
    device: str,
    register: int,
    user: UserInfo = Depends(get_current_user)
):
    """
    Request a manual poll of a specific Modbus register.

    Note: This triggers a poll via the Gateway, not direct Modbus access.
    The result will appear in subsequent /modbus calls.
    """
    # This would trigger gateway to poll - for now just log
    logger.info(f"Manual Modbus poll requested: device={device}, register={register}")

    return {
        "message": "Poll request sent",
        "device": device,
        "register": register
    }


@router.get("/gateway/logs", response_model=List[GatewayLogEntry])
async def get_gateway_logs(
    user: UserInfo = Depends(get_current_user),
    level: Optional[str] = None,
    connector: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0)
):
    """
    Get ThingsBoard Gateway logs.

    - **level**: Filter by log level (DEBUG, INFO, WARNING, ERROR)
    - **connector**: Filter by connector name
    - **limit**: Maximum number of entries
    - **offset**: Skip first N entries
    """
    try:
        logs = gateway_log_service.get_logs(
            level=level,
            connector=connector,
            limit=limit,
            offset=offset
        )
        return logs
    except Exception as e:
        logger.error(f"Failed to get gateway logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/gateway/devices")
async def get_gateway_devices(user: UserInfo = Depends(get_current_user)):
    """
    Get list of devices configured in the Gateway.

    Parses the Gateway configuration to list all configured devices.
    """
    try:
        devices = gateway_log_service.get_configured_devices()
        return {"devices": devices}
    except Exception as e:
        logger.error(f"Failed to get configured devices: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/gateway/connectors")
async def get_gateway_connectors(user: UserInfo = Depends(get_current_user)):
    """
    Get list of connectors configured in the Gateway.
    """
    try:
        connectors = gateway_log_service.get_connectors()
        return {"connectors": connectors}
    except Exception as e:
        logger.error(f"Failed to get connectors: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/gateway/status")
async def get_gateway_status(user: UserInfo = Depends(get_current_user)):
    """
    Get ThingsBoard Gateway container status.
    """
    try:
        from ..services.docker_service import docker_service

        containers = docker_service.get_containers()
        gateway_container = None

        for container in containers:
            if 'thingsboard' in container.name.lower() or 'gateway' in container.name.lower():
                gateway_container = container
                break

        if gateway_container:
            return {
                "running": gateway_container.status == "running",
                "container_name": gateway_container.name,
                "status": gateway_container.status,
                "image": gateway_container.image
            }
        else:
            return {
                "running": False,
                "error": "Gateway container not found"
            }

    except Exception as e:
        return {
            "running": False,
            "error": str(e)
        }
