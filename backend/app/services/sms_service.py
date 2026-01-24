"""
ECO-IOT-GW SMS Service
SMS alert configuration management with encrypted storage

Handles:
- SMS recipient management
- Phone number validation (E.164 format)
- Trigger configuration
- Encrypted storage of phone numbers
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import phonenumbers
from phonenumbers import NumberParseException

from ..config import settings
from ..models.schemas import SMSConfig, SMSRecipient, SMSTrigger
from ..security.crypto import encrypt_sensitive_data, decrypt_sensitive_data
from .audit_service import audit_service

logger = logging.getLogger(__name__)


def validate_phone_number(phone: str, default_region: str = "CZ") -> str:
    """
    Validate and normalize phone number to E.164 format.

    Args:
        phone: Phone number in any format
        default_region: ISO country code for parsing (default CZ)

    Returns:
        E.164 formatted phone number (e.g., +420777123456)

    Raises:
        ValueError: If phone number is invalid
    """
    try:
        # Parse the phone number
        parsed = phonenumbers.parse(phone, default_region)

        # Validate the number
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError(f"Invalid phone number: {phone}")

        # Return E.164 format
        return phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.E164
        )

    except NumberParseException as e:
        raise ValueError(f"Failed to parse phone number: {e}")


def get_phone_info(phone: str, default_region: str = "CZ") -> Dict:
    """
    Get detailed information about a phone number.

    Args:
        phone: Phone number in any format
        default_region: ISO country code for parsing

    Returns:
        Dictionary with phone number details
    """
    try:
        parsed = phonenumbers.parse(phone, default_region)
        is_valid = phonenumbers.is_valid_number(parsed)

        if is_valid:
            return {
                "valid": True,
                "e164": phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                ),
                "international": phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
                ),
                "country": phonenumbers.region_code_for_number(parsed),
            }
        else:
            return {"valid": False, "error": "Invalid phone number"}

    except NumberParseException as e:
        return {"valid": False, "error": str(e)}


class SMSService:
    """Service for managing SMS alert configuration."""

    def __init__(self):
        """Initialize SMS service with config file path."""
        self._config_file = settings.DATA_DIR / "sms_config.json"
        self._config: Optional[SMSConfig] = None
        self._trigger_states: Dict[str, datetime] = {}  # Last fire time per trigger
        self._load_config()

    def _load_config(self):
        """Load SMS configuration from disk with decryption."""
        if self._config_file.exists():
            try:
                with open(self._config_file) as f:
                    data = json.load(f)

                # Decrypt phone numbers in recipients
                if "recipients" in data:
                    for recipient in data["recipients"]:
                        if recipient.get("phone"):
                            try:
                                recipient["phone"] = decrypt_sensitive_data(
                                    recipient["phone"]
                                )
                            except Exception:
                                # Phone might not be encrypted (first time)
                                pass

                self._config = SMSConfig(**data)
                logger.info("SMS configuration loaded")

            except Exception as e:
                logger.warning(f"Failed to load SMS config: {e}")
                self._config = None
        else:
            self._config = None

    def _save_config(self):
        """Save SMS configuration to disk with encryption."""
        if not self._config:
            return

        data = self._config.model_dump()

        # Encrypt phone numbers in recipients
        if "recipients" in data:
            for recipient in data["recipients"]:
                if recipient.get("phone"):
                    recipient["phone"] = encrypt_sensitive_data(recipient["phone"])

        # Ensure directory exists
        self._config_file.parent.mkdir(parents=True, exist_ok=True)

        # Write config file
        with open(self._config_file, "w") as f:
            json.dump(data, f, indent=2)

        # Set secure permissions
        self._config_file.chmod(0o600)
        logger.debug("SMS configuration saved")

    def get_config(self) -> SMSConfig:
        """
        Get current SMS configuration.

        Returns:
            SMSConfig object (default if not configured)
        """
        if self._config:
            return self._config
        return SMSConfig()

    def set_config(
        self,
        config: SMSConfig,
        username: str = "system",
        ip_address: str = "127.0.0.1",
    ) -> None:
        """
        Set SMS configuration with validation and audit logging.

        Args:
            config: New SMS configuration
            username: User making the change
            ip_address: Client IP address

        Raises:
            ValueError: If any phone number is invalid
        """
        # Get old config for audit
        old_config = self._config.model_dump() if self._config else {}

        # Validate all phone numbers and normalize to E.164
        default_region = config.default_region
        for recipient in config.recipients:
            recipient.phone = validate_phone_number(recipient.phone, default_region)

        # Save configuration
        self._config = config
        self._save_config()

        # Audit log
        audit_service.log(
            username=username,
            action="sms_config_update",
            resource="sms",
            ip_address=ip_address,
            success=True,
            details={
                "enabled": config.enabled,
                "recipients_count": len(config.recipients),
                "triggers_count": len(config.triggers),
            },
        )

        logger.info(
            f"SMS config updated by {username}: enabled={config.enabled}, "
            f"recipients={len(config.recipients)}, triggers={len(config.triggers)}"
        )

    def add_recipient(
        self,
        recipient: SMSRecipient,
        username: str = "system",
        ip_address: str = "127.0.0.1",
    ) -> None:
        """
        Add a new SMS recipient.

        Args:
            recipient: Recipient to add
            username: User making the change
            ip_address: Client IP address

        Raises:
            ValueError: If phone number is invalid or name exists
        """
        if not self._config:
            self._config = SMSConfig()

        # Validate and normalize phone
        recipient.phone = validate_phone_number(
            recipient.phone, self._config.default_region
        )

        # Check for duplicate name
        for existing in self._config.recipients:
            if existing.name.lower() == recipient.name.lower():
                raise ValueError(f"Recipient with name '{recipient.name}' already exists")

        # Add recipient
        self._config.recipients.append(recipient)
        self._save_config()

        # Audit log
        audit_service.log(
            username=username,
            action="sms_recipient_add",
            resource="sms",
            ip_address=ip_address,
            success=True,
            details={"name": recipient.name, "enabled": recipient.enabled},
        )

        logger.info(f"SMS recipient added by {username}: {recipient.name}")

    def remove_recipient(
        self,
        name: str,
        username: str = "system",
        ip_address: str = "127.0.0.1",
    ) -> bool:
        """
        Remove an SMS recipient by name.

        Args:
            name: Recipient name to remove
            username: User making the change
            ip_address: Client IP address

        Returns:
            True if removed, False if not found
        """
        if not self._config:
            return False

        original_count = len(self._config.recipients)
        self._config.recipients = [
            r for r in self._config.recipients if r.name.lower() != name.lower()
        ]

        if len(self._config.recipients) < original_count:
            self._save_config()

            # Audit log
            audit_service.log(
                username=username,
                action="sms_recipient_remove",
                resource="sms",
                ip_address=ip_address,
                success=True,
                details={"name": name},
            )

            logger.info(f"SMS recipient removed by {username}: {name}")
            return True

        return False

    def get_default_region(self) -> str:
        """Get the default region code for phone number parsing."""
        if self._config:
            return self._config.default_region
        return "CZ"

    def get_enabled_triggers(self) -> List[SMSTrigger]:
        """Get list of enabled triggers."""
        if not self._config:
            return []
        return [t for t in self._config.triggers if t.enabled]

    def get_enabled_recipients(self) -> List[SMSRecipient]:
        """Get list of enabled recipients."""
        if not self._config:
            return []
        return [r for r in self._config.recipients if r.enabled]

    def check_trigger_cooldown(self, event_type: str) -> bool:
        """
        Check if a trigger can fire (not in cooldown).

        Args:
            event_type: The trigger event type

        Returns:
            True if trigger can fire, False if in cooldown
        """
        if not self._config:
            return False

        # Find the trigger config
        trigger = None
        for t in self._config.triggers:
            if t.event_type == event_type:
                trigger = t
                break

        if not trigger or not trigger.enabled:
            return False

        # Check cooldown
        last_fired = self._trigger_states.get(event_type)
        if last_fired:
            cooldown_delta = timedelta(minutes=trigger.cooldown_minutes)
            if datetime.now() < last_fired + cooldown_delta:
                return False

        return True

    def record_trigger_fired(self, event_type: str) -> None:
        """
        Record that a trigger has fired.

        Args:
            event_type: The trigger event type
        """
        self._trigger_states[event_type] = datetime.now()
        logger.debug(f"Recorded trigger fired: {event_type}")


# Global SMS service instance
sms_service = SMSService()
