"""
ECO-IOT-GW ThingsBoard API
ThingsBoard Gateway configuration endpoints
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from ..models.schemas import (
    SuccessResponse,
    ThingsBoardConfig,
    ThingsBoardConfigResponse,
    ThingsBoardStatus,
)
from ..security.auth import get_current_user
from ..services.thingsboard_service import thingsboard_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/config", response_model=ThingsBoardConfigResponse)
async def get_thingsboard_config(user=Depends(get_current_user)):
    """Get ThingsBoard configuration (without sensitive data)."""
    return thingsboard_service.get_config()


@router.put("/config", response_model=SuccessResponse)
async def save_thingsboard_config(
    config: ThingsBoardConfig,
    user=Depends(get_current_user)
):
    """Save ThingsBoard configuration."""
    try:
        thingsboard_service.save_config(config)

        # Log audit event
        try:
            from ..services.audit_service import audit_service
            audit_service.log(
                username=user.username,
                action="thingsboard_config_save",
                resource="thingsboard",
                details={"host": config.host, "port": config.port, "security_type": config.security_type.value},
                ip_address="api",
                success=True
            )
        except Exception:
            pass

        return SuccessResponse(message="ThingsBoard configuration saved")

    except Exception as e:
        logger.error(f"Failed to save ThingsBoard config: {e}")

        try:
            from ..services.audit_service import audit_service
            audit_service.log(
                username=user.username,
                action="thingsboard_config_save",
                resource="thingsboard",
                ip_address="api",
                success=False
            )
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/config", response_model=SuccessResponse)
async def delete_thingsboard_config(user=Depends(get_current_user)):
    """Delete ThingsBoard configuration."""
    try:
        thingsboard_service.delete_config()

        try:
            from ..services.audit_service import audit_service
            audit_service.log(
                username=user.username,
                action="thingsboard_config_delete",
                resource="thingsboard",
                ip_address="api",
                success=True
            )
        except Exception:
            pass

        return SuccessResponse(message="ThingsBoard configuration deleted")

    except Exception as e:
        logger.error(f"Failed to delete ThingsBoard config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/status", response_model=ThingsBoardStatus)
async def get_thingsboard_status(user=Depends(get_current_user)):
    """Get ThingsBoard connection status."""
    return thingsboard_service.get_status()


@router.post("/restart", response_model=SuccessResponse)
async def restart_thingsboard_gateway(user=Depends(get_current_user)):
    """Restart the ThingsBoard Gateway container."""
    try:
        thingsboard_service.restart_gateway()

        try:
            from ..services.audit_service import audit_service
            audit_service.log(
                username=user.username,
                action="thingsboard_gateway_restart",
                resource="thingsboard",
                ip_address="api",
                success=True
            )
        except Exception:
            pass

        return SuccessResponse(message="ThingsBoard Gateway restarted")

    except Exception as e:
        logger.error(f"Failed to restart gateway: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/test", response_model=Dict[str, Any])
async def test_thingsboard_connection(user=Depends(get_current_user)):
    """Test ThingsBoard connection."""
    return thingsboard_service.test_connection()


@router.post("/download-cert", response_model=Dict[str, Any])
async def download_ca_certificate(
    host: str = None,
    user=Depends(get_current_user)
):
    """Download CA certificate from ThingsBoard platform."""
    return thingsboard_service.download_ca_cert(host)


@router.get("/devices", response_model=Dict[str, Any])
async def get_available_devices(user=Depends(get_current_user)):
    """Get available serial devices on the system."""
    return thingsboard_service.get_available_devices()


@router.post("/deploy", response_model=Dict[str, Any])
async def deploy_gateway(user=Depends(get_current_user)):
    """Generate docker-compose and deploy the gateway."""
    result = thingsboard_service.deploy_gateway()

    try:
        from ..services.audit_service import audit_service
        audit_service.log(
            username=user.username,
            action="thingsboard_gateway_deploy",
            resource="thingsboard",
            ip_address="api",
            success=result.get("success", False)
        )
    except Exception:
        pass

    return result


@router.post("/stop", response_model=Dict[str, Any])
async def stop_gateway(user=Depends(get_current_user)):
    """Stop the ThingsBoard Gateway."""
    result = thingsboard_service.stop_gateway()

    try:
        from ..services.audit_service import audit_service
        audit_service.log(
            username=user.username,
            action="thingsboard_gateway_stop",
            resource="thingsboard",
            ip_address="api",
            success=result.get("success", False)
        )
    except Exception:
        pass

    return result


@router.get("/gateway-status", response_model=Dict[str, Any])
async def get_gateway_container_status(user=Depends(get_current_user)):
    """Get detailed gateway container status."""
    return thingsboard_service.get_gateway_status()


@router.get("/logs", response_model=Dict[str, Any])
async def get_gateway_logs(lines: int = 100, user=Depends(get_current_user)):
    """Get recent gateway logs."""
    return thingsboard_service.get_gateway_logs(lines)


@router.get("/compose-preview", response_model=Dict[str, Any])
async def preview_docker_compose(user=Depends(get_current_user)):
    """Preview the docker-compose.yml that would be generated."""
    try:
        content = thingsboard_service.generate_docker_compose()
        return {"success": True, "content": content}
    except Exception as e:
        return {"success": False, "error": str(e)}
