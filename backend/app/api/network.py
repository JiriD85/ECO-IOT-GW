"""
ECO-IOT-GW Network Failover API
Network interface monitoring and failover configuration endpoints
"""
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..models.schemas import (
    ConnectivityTestRequest,
    ConnectivityTestResponse,
    FailoverConfig,
    FailoverConfigRequest,
    NetworkInterfaceDetail,
    NetworkStatusResponse,
    SuccessResponse,
    UserInfo
)
from ..security.auth import get_current_user
from ..services.network_service import network_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/network", tags=["network"])


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    return client_ip


def require_admin(user: UserInfo) -> None:
    """Require admin role for operation."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )


@router.get("/status", response_model=NetworkStatusResponse)
async def get_network_status():
    """
    Get current network status for all interfaces.

    Returns list of all network interfaces with statistics,
    active default route, and current timestamp.

    No authentication required (read-only status).
    """
    try:
        interfaces = await network_service.get_interfaces()
        active_route = await network_service.get_active_route()

        # Convert interfaces to NetworkInterface models (will be validated by response_model)
        return NetworkStatusResponse(
            interfaces=interfaces,
            active_route=active_route,
            timestamp=datetime.utcnow().isoformat() + "Z"
        )

    except Exception as e:
        logger.error(f"Failed to get network status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/interfaces/{interface_name}", response_model=NetworkInterfaceDetail)
async def get_interface_detail(interface_name: str):
    """
    Get detailed status for a specific interface.

    Returns comprehensive statistics including:
    - Operational state (up/down)
    - Link speed and MTU
    - Bytes/packets sent/received
    - Errors and drops
    - IP addresses (IPv4 and IPv6)

    No authentication required (read-only status).
    """
    try:
        interface_status = await network_service.get_interface_status(interface_name)

        if interface_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Interface '{interface_name}' not found"
            )

        return NetworkInterfaceDetail(**interface_status)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get interface detail: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/failover/config", response_model=FailoverConfig)
async def get_failover_config(user: UserInfo = Depends(get_current_user)):
    """
    Get current failover configuration.

    Returns configured primary and backup interfaces,
    their route metrics, and health check settings.

    Requires authentication (any authenticated user can view).
    """
    try:
        config = await network_service.get_failover_config()

        # Build complete failover config response
        return FailoverConfig(
            primary_interface=config.get("primary", "eth0"),
            backup_interface=config.get("backup", "wwan0"),
            primary_metric=network_service.METRIC_PRIMARY,
            backup_metric=network_service.METRIC_BACKUP,
            health_check_enabled=True,  # Currently always enabled
            health_check_interval=60,  # Default monitoring interval
            ping_targets=network_service.HEALTH_CHECK_TARGETS
        )

    except Exception as e:
        logger.error(f"Failed to get failover config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/failover/config", response_model=SuccessResponse)
async def update_failover_config(
    request: Request,
    config: FailoverConfigRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Configure network failover priority.

    Sets primary and backup interfaces with route metrics.
    Lower metric = higher priority (e.g., Ethernet=100, LTE=200).

    Requires admin role.

    - **primary_interface**: Primary interface name (e.g., eth0)
    - **backup_interface**: Backup interface name (e.g., wwan0)
    - **primary_metric**: Route metric for primary (default: 100)
    - **backup_metric**: Route metric for backup (default: 200)
    """
    client_ip = get_client_ip(request)
    require_admin(user)

    try:
        # Set failover configuration
        result = await network_service.set_failover_config(
            primary=config.primary_interface,
            backup=config.backup_interface,
            username=user.username,
            ip_address=client_ip
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("message", "Failed to configure failover")
            )

        # Apply custom metrics if provided
        if config.primary_metric is not None:
            metric_result = await network_service.set_interface_priority(
                interface_name=config.primary_interface,
                priority=config.primary_metric,
                username=user.username,
                ip_address=client_ip
            )
            if not metric_result.get("success"):
                logger.warning(f"Failed to set custom primary metric: {metric_result.get('message')}")

        if config.backup_metric is not None:
            metric_result = await network_service.set_interface_priority(
                interface_name=config.backup_interface,
                priority=config.backup_metric,
                username=user.username,
                ip_address=client_ip
            )
            if not metric_result.get("success"):
                logger.warning(f"Failed to set custom backup metric: {metric_result.get('message')}")

        return SuccessResponse(
            message=f"Failover configured: {config.primary_interface} (primary) → {config.backup_interface} (backup)"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update failover config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/connectivity/test", response_model=ConnectivityTestResponse)
async def test_connectivity(
    request: Request,
    test_request: ConnectivityTestRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Test connectivity on a specific interface.

    Performs ping health check bound to the specified interface.
    Uses multiple redundant targets (1.1.1.1, 8.8.8.8) unless specific target provided.

    Requires authentication (any user can test).

    - **interface**: Interface name to test (e.g., eth0, wwan0)
    - **target**: Optional specific IP to ping (default: multiple targets)
    """
    client_ip = get_client_ip(request)

    try:
        # Perform connectivity check
        success = await network_service.check_connectivity(
            interface_name=test_request.interface,
            target=test_request.target if test_request.target != "8.8.8.8" else None
        )

        # For now, we don't measure latency/packet loss - just pass/fail
        # Could enhance network_service.check_connectivity to parse ping output
        return ConnectivityTestResponse(
            success=success,
            interface=test_request.interface,
            target=test_request.target or "multiple",
            latency_ms=None,  # Not currently measured
            packet_loss=0.0 if success else 100.0,
            timestamp=datetime.utcnow().isoformat() + "Z"
        )

    except Exception as e:
        logger.error(f"Failed to test connectivity: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
