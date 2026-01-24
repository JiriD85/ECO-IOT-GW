"""
ECO-IOT-GW SMS API
SMS alert configuration and testing endpoints
"""
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..models.schemas import (
    SMSConfig,
    SMSRecipient,
    SMSTrigger,
    SMSTestRequest,
    SMSTestResponse,
    SuccessResponse,
    UserInfo,
)
from ..security.auth import get_current_user
from ..services.audit_service import audit_service
from ..services.sms_service import sms_service, validate_phone_number, get_phone_info
from ..services.modem_service import modem_service

logger = logging.getLogger(__name__)
router = APIRouter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    return client_ip


@router.get("/config", response_model=SMSConfig)
async def get_sms_config(user: UserInfo = Depends(get_current_user)):
    """
    Get current SMS configuration.

    Returns SMS alert configuration including recipients and triggers.
    Any authenticated user can view the configuration.
    """
    try:
        config = sms_service.get_config()
        return config

    except Exception as e:
        logger.error(f"Failed to get SMS config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/config", response_model=SuccessResponse)
async def update_sms_config(
    request: Request,
    config: SMSConfig,
    user: UserInfo = Depends(get_current_user)
):
    """
    Update SMS configuration.

    Update SMS alert settings including enabled state, recipients, triggers,
    and default region. Requires admin role.

    All phone numbers are validated and normalized to E.164 format.
    """
    client_ip = get_client_ip(request)

    # Require admin role for config changes
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        sms_service.set_config(
            config=config,
            username=user.username,
            ip_address=client_ip
        )

        return SuccessResponse(message="SMS configuration updated")

    except ValueError as e:
        # Invalid phone number
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to update SMS config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/recipients", response_model=SuccessResponse)
async def add_sms_recipient(
    request: Request,
    recipient: SMSRecipient,
    user: UserInfo = Depends(get_current_user)
):
    """
    Add a new SMS recipient.

    Add a recipient for SMS alerts. Requires admin role.
    Phone number is validated and normalized to E.164 format.
    """
    client_ip = get_client_ip(request)

    # Require admin role
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        sms_service.add_recipient(
            recipient=recipient,
            username=user.username,
            ip_address=client_ip
        )

        return SuccessResponse(message=f"Recipient '{recipient.name}' added")

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to add SMS recipient: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/recipients/{name}", response_model=SuccessResponse)
async def remove_sms_recipient(
    request: Request,
    name: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Remove an SMS recipient by name.

    Remove a recipient from SMS alerts. Requires admin role.
    """
    client_ip = get_client_ip(request)

    # Require admin role
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    try:
        removed = sms_service.remove_recipient(
            name=name,
            username=user.username,
            ip_address=client_ip
        )

        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Recipient '{name}' not found"
            )

        return SuccessResponse(message=f"Recipient '{name}' removed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove SMS recipient: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/validate-number")
async def validate_phone_number_endpoint(
    phone: str = Query(..., description="Phone number to validate"),
    region: str = Query(default="CZ", description="ISO country code for parsing"),
    user: UserInfo = Depends(get_current_user)
):
    """
    Validate a phone number.

    Validates the phone number and returns E.164 format and country info.
    Any authenticated user can validate phone numbers.
    """
    try:
        info = get_phone_info(phone, region)
        return info

    except Exception as e:
        logger.error(f"Phone validation error: {e}")
        return {"valid": False, "error": str(e)}


@router.post("/test", response_model=SMSTestResponse)
async def test_sms(
    request: Request,
    test_request: SMSTestRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Send a test SMS message.

    Send a test SMS to the specified phone number. Any authenticated user
    can send test messages. The message is optional; if not provided, a
    default test message with timestamp is sent.
    """
    client_ip = get_client_ip(request)

    try:
        # Validate and normalize phone number
        default_region = sms_service.get_default_region()
        validated_phone = validate_phone_number(test_request.phone, default_region)

        # Generate message if not provided
        message = test_request.message
        if not message:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"Test SMS from ECO-IOT-GW at {timestamp}"

        # Send SMS via modem
        success, result = modem_service.send_sms(validated_phone, message)

        # Audit log the test
        audit_service.log(
            username=user.username,
            action="sms_test",
            resource="sms",
            ip_address=client_ip,
            success=success,
            details={
                "phone": validated_phone,
                "message_length": len(message),
                "result": result
            }
        )

        if success:
            return SMSTestResponse(
                success=True,
                message=f"Test SMS sent to {validated_phone}",
                message_reference=result
            )
        else:
            return SMSTestResponse(
                success=False,
                message=f"Failed to send SMS: {result}"
            )

    except ValueError as e:
        return SMSTestResponse(
            success=False,
            message=f"Invalid phone number: {e}"
        )
    except Exception as e:
        logger.error(f"SMS test failed: {e}")
        return SMSTestResponse(
            success=False,
            message=f"SMS test error: {e}"
        )


@router.get("/triggers")
async def get_available_triggers(user: UserInfo = Depends(get_current_user)):
    """
    Get available SMS trigger types.

    Returns list of available trigger event types with descriptions.
    Any authenticated user can view trigger types.
    """
    return [
        {
            "event_type": "vpn_down",
            "description": "VPN connection lost",
            "default_cooldown": 30
        },
        {
            "event_type": "modem_down",
            "description": "LTE modem disconnected",
            "default_cooldown": 30
        },
        {
            "event_type": "network_failover",
            "description": "Network failover occurred",
            "default_cooldown": 60
        },
        {
            "event_type": "backup_failed",
            "description": "System backup failed",
            "default_cooldown": 60
        }
    ]
