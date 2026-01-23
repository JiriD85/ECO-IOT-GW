"""
ECO-IOT-GW VPN API
OpenVPN, WireGuard, and Tailscale management
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status

from ..config import settings
from ..models.schemas import (
    ErrorResponse,
    SuccessResponse,
    TailscaleAuthRequest,
    UserInfo,
    VPNAutostart,
    VPNConfigRequest,
    VPNStatus,
    VPNType
)
from ..security.auth import get_current_user
from ..security.validators import validate_vpn_config
from ..services.vpn_service import vpn_service

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
        # Don't log sensitive VPN details
        safe_details = {k: v for k, v in (details or {}).items()
                       if k not in ('content', 'auth_key', 'key', 'password')}
        audit_service.log(
            username=username,
            action=action,
            resource="vpn",
            ip_address=ip,
            success=success,
            details=safe_details
        )
    except Exception as e:
        logger.warning(f"Failed to log audit: {e}")


@router.get("/status", response_model=VPNStatus)
async def get_vpn_status(user: UserInfo = Depends(get_current_user)):
    """
    Get current VPN connection status.

    Returns connection state, IP address, and traffic stats.
    """
    return vpn_service.get_status()


@router.get("/type")
async def get_vpn_type(user: UserInfo = Depends(get_current_user)):
    """Get currently configured VPN type."""
    current_type = vpn_service.get_current_type()
    return {"vpn_type": current_type.value if current_type else None}


@router.put("/type")
async def set_vpn_type(
    request: Request,
    vpn_type: VPNType,
    user: UserInfo = Depends(get_current_user)
):
    """
    Set VPN type.

    Changing VPN type will disconnect and disable the previous VPN.
    """
    client_ip = get_client_ip(request)

    try:
        vpn_service.set_type(vpn_type)
        log_audit(user.username, "set_vpn_type", client_ip, {"vpn_type": vpn_type.value})
        return SuccessResponse(message=f"VPN type set to {vpn_type.value}")

    except Exception as e:
        log_audit(user.username, "set_vpn_type", client_ip,
                 {"vpn_type": vpn_type.value, "error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/config")
async def get_vpn_config(user: UserInfo = Depends(get_current_user)):
    """
    Get current VPN configuration (without sensitive data).

    Returns filename and metadata, not the actual keys/certificates.
    """
    config_info = vpn_service.get_config_info()
    return config_info


@router.post("/config", response_model=SuccessResponse)
async def upload_vpn_config(
    request: Request,
    data: VPNConfigRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Upload VPN configuration.

    - **content**: Configuration file content
    - **filename**: Original filename
    - **vpn_type**: VPN type (openvpn, wireguard)

    For OpenVPN: Upload .ovpn file
    For WireGuard: Upload .conf file
    """
    client_ip = get_client_ip(request)

    # Validate configuration
    try:
        validate_vpn_config(data.content, data.vpn_type.value)
    except HTTPException:
        log_audit(user.username, "upload_vpn_config", client_ip,
                 {"vpn_type": data.vpn_type.value, "error": "validation_failed"}, success=False)
        raise

    try:
        vpn_service.save_config(data.content, data.filename, data.vpn_type)
        log_audit(user.username, "upload_vpn_config", client_ip,
                 {"vpn_type": data.vpn_type.value, "filename": data.filename})
        return SuccessResponse(message="VPN configuration uploaded successfully")

    except Exception as e:
        log_audit(user.username, "upload_vpn_config", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/config/upload", response_model=SuccessResponse)
async def upload_vpn_config_file(
    request: Request,
    file: UploadFile = File(...),
    vpn_type: Optional[VPNType] = None,
    user: UserInfo = Depends(get_current_user)
):
    """
    Upload VPN configuration file (for drag & drop).

    Accepts .ovpn files for OpenVPN and .conf files for WireGuard.
    VPN type is auto-detected from file extension if not specified.
    """
    client_ip = get_client_ip(request)

    # Auto-detect VPN type from filename
    if vpn_type is None:
        if file.filename.endswith('.ovpn'):
            vpn_type = VPNType.OPENVPN
        elif file.filename.endswith('.conf'):
            vpn_type = VPNType.WIREGUARD
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot determine VPN type from filename. Use .ovpn for OpenVPN or .conf for WireGuard."
            )

    # Read content
    content = await file.read()
    try:
        content_str = content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be valid UTF-8"
        )

    # Validate configuration
    try:
        validate_vpn_config(content_str, vpn_type.value)
    except HTTPException:
        log_audit(user.username, "upload_vpn_config_file", client_ip,
                 {"vpn_type": vpn_type.value, "filename": file.filename,
                  "error": "validation_failed"}, success=False)
        raise

    try:
        vpn_service.save_config(content_str, file.filename, vpn_type)
        log_audit(user.username, "upload_vpn_config_file", client_ip,
                 {"vpn_type": vpn_type.value, "filename": file.filename})
        return SuccessResponse(message="VPN configuration uploaded successfully")

    except Exception as e:
        log_audit(user.username, "upload_vpn_config_file", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/config", response_model=SuccessResponse)
async def delete_vpn_config(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """Delete VPN configuration."""
    client_ip = get_client_ip(request)

    try:
        vpn_service.delete_config()
        log_audit(user.username, "delete_vpn_config", client_ip)
        return SuccessResponse(message="VPN configuration deleted")

    except Exception as e:
        log_audit(user.username, "delete_vpn_config", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/connect", response_model=SuccessResponse)
async def connect_vpn(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Connect to VPN.

    Requires VPN configuration to be uploaded first.
    """
    client_ip = get_client_ip(request)

    try:
        vpn_service.connect()
        log_audit(user.username, "vpn_connect", client_ip)
        return SuccessResponse(message="VPN connection initiated")

    except Exception as e:
        log_audit(user.username, "vpn_connect", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/disconnect", response_model=SuccessResponse)
async def disconnect_vpn(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """Disconnect from VPN."""
    client_ip = get_client_ip(request)

    try:
        vpn_service.disconnect()
        log_audit(user.username, "vpn_disconnect", client_ip)
        return SuccessResponse(message="VPN disconnected")

    except Exception as e:
        log_audit(user.username, "vpn_disconnect", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/autostart", response_model=VPNAutostart)
async def get_autostart(user: UserInfo = Depends(get_current_user)):
    """Get VPN autostart configuration."""
    return vpn_service.get_autostart()


@router.put("/autostart", response_model=SuccessResponse)
async def set_autostart(
    request: Request,
    config: VPNAutostart,
    user: UserInfo = Depends(get_current_user)
):
    """
    Enable or disable VPN autostart.

    When enabled, VPN will connect automatically after system boot.
    """
    client_ip = get_client_ip(request)

    try:
        vpn_service.set_autostart(config.enabled)
        log_audit(user.username, "set_vpn_autostart", client_ip,
                 {"enabled": config.enabled})
        status_msg = "enabled" if config.enabled else "disabled"
        return SuccessResponse(message=f"VPN autostart {status_msg}")

    except Exception as e:
        log_audit(user.username, "set_vpn_autostart", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# Tailscale-specific endpoints

@router.post("/tailscale/auth", response_model=SuccessResponse)
async def tailscale_auth(
    request: Request,
    data: TailscaleAuthRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Authenticate Tailscale with auth key.

    Get an auth key from https://login.tailscale.com/admin/settings/keys
    """
    client_ip = get_client_ip(request)

    try:
        vpn_service.tailscale_auth(data.auth_key)
        log_audit(user.username, "tailscale_auth", client_ip)
        return SuccessResponse(message="Tailscale authentication initiated")

    except Exception as e:
        log_audit(user.username, "tailscale_auth", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/tailscale/logout", response_model=SuccessResponse)
async def tailscale_logout(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """Logout from Tailscale."""
    client_ip = get_client_ip(request)

    try:
        vpn_service.tailscale_logout()
        log_audit(user.username, "tailscale_logout", client_ip)
        return SuccessResponse(message="Tailscale logged out")

    except Exception as e:
        log_audit(user.username, "tailscale_logout", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/tailscale/status")
async def tailscale_status(user: UserInfo = Depends(get_current_user)):
    """Get Tailscale-specific status information."""
    return vpn_service.get_tailscale_status()
