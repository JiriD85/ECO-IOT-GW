"""
ECO-IOT-GW Meters API

Read-only child-device telemetry + connector health, derived from the gateway.
No direct Modbus access, no config editing (that stays in ThingsBoard).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from typing import Optional

from ..models.schemas import UserInfo
from ..security.auth import get_optional_user
from ..services.meters_service import meters_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/latest")
async def get_latest(user: Optional[UserInfo] = Depends(get_optional_user)):
    """
    Latest values reported by each child device (P-Flow meters, AIOX temperatures)
    plus a connector health summary.

    Values are parsed from the ThingsBoard gateway's own logs; the RS485 bus is
    never queried directly (that would collide with the gateway's polling).
    """
    try:
        return meters_service.get_latest()
    except Exception as e:
        logger.error(f"Failed to read meter values: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read meter values from the gateway.",
        )
