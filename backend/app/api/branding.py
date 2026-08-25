"""
ECO-IOT-GW Branding API
Kit identification and branding asset endpoints
"""
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, status
from fastapi.responses import Response

from ..models.schemas import BrandingConfig, BrandingStatus, UserInfo
from ..security.auth import get_current_user
from ..services.branding_service import branding_service

logger = logging.getLogger(__name__)
router = APIRouter()


def require_admin(user: UserInfo) -> None:
    """Require admin role for operation."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )


@router.get("/config", response_model=BrandingStatus)
async def get_config():
    """
    Get branding configuration and status.

    Public endpoint - no authentication required.
    Needed for login page to display kit name and logo.

    Returns:
        BrandingStatus with kit name, theme, and asset availability
    """
    try:
        return branding_service.get_config()
    except Exception as e:
        logger.error(f"Failed to get branding config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/config", response_model=BrandingStatus)
async def update_config(
    config: BrandingConfig,
    user: UserInfo = Depends(get_current_user)
):
    """
    Update branding configuration.

    Admin only endpoint.
    Updates kit name and theme.

    Args:
        config: New branding configuration
        user: Current authenticated user

    Returns:
        Updated BrandingStatus
    """
    require_admin(user)

    try:
        return branding_service.set_config(config)
    except Exception as e:
        logger.error(f"Failed to update branding config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/logo")
async def get_logo():
    """
    Get logo image.

    Public endpoint - no authentication required.
    Needed for login page to display custom logo.

    Returns:
        Image file with appropriate content type
    """
    result = branding_service.get_logo()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No logo configured"
        )

    content, content_type = result
    return Response(content=content, media_type=content_type)


@router.post("/logo")
async def upload_logo(
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user)
):
    """
    Upload logo image.

    Admin only endpoint.
    Accepts PNG, JPEG, or SVG images up to 1MB.

    Args:
        file: Image file to upload
        user: Current authenticated user

    Returns:
        Success status
    """
    require_admin(user)

    # Validate content type
    if file.content_type not in branding_service.LOGO_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content type. Allowed: {', '.join(branding_service.LOGO_CONTENT_TYPES)}"
        )

    try:
        # Read file content
        content = await file.read()

        # Save logo
        branding_service.save_logo(content, file.content_type)

        return {"status": "success", "message": "Logo uploaded successfully"}

    except ValueError as e:
        # Validation error from service
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to upload logo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/logo")
async def delete_logo(user: UserInfo = Depends(get_current_user)):
    """
    Delete logo image.

    Admin only endpoint.
    Removes uploaded logo file.

    Args:
        user: Current authenticated user

    Returns:
        Success status
    """
    require_admin(user)

    try:
        branding_service.delete_logo()
        return {"status": "success", "message": "Logo deleted successfully"}
    except Exception as e:
        logger.error(f"Failed to delete logo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/favicon")
async def get_favicon():
    """
    Get favicon image.

    Public endpoint - no authentication required.
    Needed for browser to display custom favicon.

    Returns:
        Image file with appropriate content type
    """
    result = branding_service.get_favicon()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No favicon configured"
        )

    content, content_type = result
    return Response(content=content, media_type=content_type)


@router.post("/favicon")
async def upload_favicon(
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user)
):
    """
    Upload favicon image.

    Admin only endpoint.
    Accepts .ico or PNG images up to 100KB.

    Args:
        file: Image file to upload
        user: Current authenticated user

    Returns:
        Success status
    """
    require_admin(user)

    # Validate content type
    if file.content_type not in branding_service.FAVICON_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content type. Allowed: {', '.join(branding_service.FAVICON_CONTENT_TYPES)}"
        )

    try:
        # Read file content
        content = await file.read()

        # Save favicon
        branding_service.save_favicon(content, file.content_type)

        return {"status": "success", "message": "Favicon uploaded successfully"}

    except ValueError as e:
        # Validation error from service
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to upload favicon: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/favicon")
async def delete_favicon(user: UserInfo = Depends(get_current_user)):
    """
    Delete favicon image.

    Admin only endpoint.
    Removes uploaded favicon file.

    Args:
        user: Current authenticated user

    Returns:
        Success status
    """
    require_admin(user)

    try:
        branding_service.delete_favicon()
        return {"status": "success", "message": "Favicon deleted successfully"}
    except Exception as e:
        logger.error(f"Failed to delete favicon: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
