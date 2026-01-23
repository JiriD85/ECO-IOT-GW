"""
ECO-IOT-GW Audit API
Audit log retrieval and statistics
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..models.schemas import AuditLogEntry, AuditLogQuery, UserInfo
from ..security.auth import get_current_user
from ..services.audit_service import audit_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/logs", response_model=list[AuditLogEntry])
async def get_audit_logs(
    user: UserInfo = Depends(get_current_user),
    username: Optional[str] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0)
):
    """
    Get audit log entries.

    Supports filtering by:
    - **username**: Filter by user who performed action
    - **action**: Filter by action type (login, logout, create, update, delete, etc.)
    - **resource**: Filter by resource type (auth, docker, vpn, etc.)
    - **limit**: Max entries to return (1-1000)
    - **offset**: Skip first N entries
    """
    try:
        query = AuditLogQuery(
            username=username,
            action=action,
            resource=resource,
            limit=limit,
            offset=offset
        )
        return audit_service.query(query)

    except Exception as e:
        logger.error(f"Failed to get audit logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/stats")
async def get_audit_stats(
    user: UserInfo = Depends(get_current_user),
    days: int = Query(default=7, ge=1, le=90)
):
    """
    Get audit statistics for the last N days.

    Returns:
    - Total events
    - Failed events
    - Events by action type
    - Events by user
    """
    try:
        return audit_service.get_stats(days=days)

    except Exception as e:
        logger.error(f"Failed to get audit stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/cleanup")
async def cleanup_audit_logs(
    user: UserInfo = Depends(get_current_user),
    retention_days: int = Query(default=90, ge=30, le=365)
):
    """
    Clean up old audit logs.

    Removes logs older than retention_days (default 90, min 30, max 365).
    Requires admin role.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        deleted = audit_service.cleanup(retention_days=retention_days)
        return {
            "message": f"Cleaned up {deleted} old audit log entries",
            "deleted_count": deleted
        }

    except Exception as e:
        logger.error(f"Failed to cleanup audit logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
