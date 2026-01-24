"""
ECO-IOT-GW Backup API
System backup and restore endpoints
"""
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from ..models.schemas import (
    BackupInfo,
    BackupValidateResponse,
    RestoreResponse,
    SuccessResponse,
    UserInfo
)
from ..security.auth import get_current_user
from ..services.backup_service import backup_service

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.post("/create")
async def create_backup(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Create and download system backup.

    Creates a tar.gz backup of critical system configuration including:
    - /etc/eco-iot-gw/
    - /etc/openvpn/
    - /etc/wireguard/
    - /etc/thingsboard-gateway/config/
    - /etc/chrony/
    - /var/lib/eco-iot-gw/audit/

    Requires admin role.
    Returns tar.gz file for download.
    """
    client_ip = get_client_ip(request)
    require_admin(user)

    try:
        result = await backup_service.create_backup(
            username=user.username,
            ip_address=client_ip
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message", "Failed to create backup")
            )

        backup_file = result.get("backup_file")
        backup_filename = result.get("backup_filename")

        # Return file for download
        return FileResponse(
            path=backup_file,
            filename=backup_filename,
            media_type="application/gzip",
            headers={
                "Content-Disposition": f'attachment; filename="{backup_filename}"'
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/restore", response_model=RestoreResponse)
async def restore_backup(
    request: Request,
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user)
):
    """
    Restore system from uploaded backup.

    Upload a backup tar.gz file to restore system configuration.
    Validates backup integrity before restoring.

    Requires admin role.
    """
    client_ip = get_client_ip(request)
    require_admin(user)

    # Validate file extension
    if not (file.filename.endswith('.tar.gz') or file.filename.endswith('.tgz')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only .tar.gz or .tgz files allowed"
        )

    temp_file = None
    try:
        # Stream upload to temp file (memory efficient)
        temp_file = NamedTemporaryFile(delete=False, suffix='.tar.gz')
        chunk_size = 8192

        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            temp_file.write(chunk)

        temp_file.close()
        temp_path = Path(temp_file.name)

        # Restore from backup
        result = await backup_service.restore_backup(
            file_path=temp_path,
            username=user.username,
            ip_address=client_ip
        )

        return RestoreResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            restored_paths=result.get("restored_paths")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to restore backup: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        # Clean up temp file
        if temp_file:
            try:
                temp_path = Path(temp_file.name)
                if temp_path.exists():
                    temp_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to clean up temp file: {e}")


@router.post("/validate", response_model=BackupValidateResponse)
async def validate_backup(
    request: Request,
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user)
):
    """
    Validate uploaded backup without restoring.

    Upload a backup file to check its integrity and view metadata.
    Does not modify system configuration.

    Requires admin role.
    """
    client_ip = get_client_ip(request)
    require_admin(user)

    # Validate file extension
    if not (file.filename.endswith('.tar.gz') or file.filename.endswith('.tgz')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only .tar.gz or .tgz files allowed"
        )

    temp_file = None
    try:
        # Stream upload to temp file
        temp_file = NamedTemporaryFile(delete=False, suffix='.tar.gz')
        chunk_size = 8192

        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            temp_file.write(chunk)

        temp_file.close()
        temp_path = Path(temp_file.name)

        # Validate backup
        try:
            manifest = await backup_service.validate_backup(temp_path)

            # Convert manifest dict to BackupInfo model
            backup_info = BackupInfo(
                version=manifest.get("version"),
                created_at=manifest.get("created_at"),
                hostname=manifest.get("hostname"),
                app_version=manifest.get("app_version"),
                paths=manifest.get("paths", [])
            )

            return BackupValidateResponse(
                valid=True,
                manifest=backup_info,
                error=None
            )

        except ValueError as e:
            # Validation failed
            return BackupValidateResponse(
                valid=False,
                manifest=None,
                error=str(e)
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate backup: {e}")
        return BackupValidateResponse(
            valid=False,
            manifest=None,
            error=str(e)
        )
    finally:
        # Clean up temp file
        if temp_file:
            try:
                temp_path = Path(temp_file.name)
                if temp_path.exists():
                    temp_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to clean up temp file: {e}")
