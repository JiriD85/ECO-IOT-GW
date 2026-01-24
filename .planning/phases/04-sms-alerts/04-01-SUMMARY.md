# Plan 04-01 Summary: Backend SMS Foundation

## Status: COMPLETE

## What Was Built

### Task 1: SMS Pydantic Models (schemas.py)
- **SMSRecipient**: name, phone (E.164), enabled
- **SMSTrigger**: event_type (vpn_down|modem_down|network_failover|backup_failed), enabled, cooldown_minutes
- **SMSConfig**: enabled, recipients list, triggers list, default_region (ISO country code)
- **SMSTestRequest**: phone, optional message
- **SMSTestResponse**: success, message, message_reference

### Task 2: SMS Service (sms_service.py)
- `validate_phone_number(phone, region)` - Normalize to E.164 format
- `get_phone_info(phone, region)` - Get detailed phone validation info
- `SMSService` class with:
  - Encrypted config storage at `/var/lib/eco-iot-gw/sms_config.json`
  - `get_config()` / `set_config()` with audit logging
  - `add_recipient()` / `remove_recipient()` with duplicate detection
  - `get_enabled_triggers()` / `get_enabled_recipients()` - Filter by enabled
  - `check_trigger_cooldown(event_type)` - Cooldown enforcement
  - `record_trigger_fired(event_type)` - Track trigger fire times
- Added `phonenumbers>=8.13.0` to requirements.txt

### Task 3: Modem Service SMS Extension (modem_service.py)
- Added `threading.Lock` (`_serial_lock`) for thread-safe serial access
- Updated `send_at_command()` to use the lock
- Added `check_sms_ready()` - Check SIM status via AT+CPIN?
- Added `send_sms(phone_number, message)` - Full AT command sequence:
  - Text mode (AT+CMGF=1)
  - GSM charset (AT+CSCS="GSM")
  - Send via AT+CMGS
  - 30s timeout for delivery confirmation
  - Returns message reference on success

## Verification Results

```bash
# Models import
python -c "from app.models.schemas import SMSConfig, SMSRecipient, SMSTrigger, SMSTestRequest, SMSTestResponse; print('OK')"
# Result: OK

# Phone validation
python -c "from app.services.sms_service import sms_service, validate_phone_number; print(validate_phone_number('+420777123456', 'CZ'))"
# Result: +420777123456

# Modem service
python -c "from app.services.modem_service import modem_service; print('Lock:', hasattr(modem_service, '_serial_lock')); print('SMS:', hasattr(modem_service, 'send_sms'))"
# Result: Lock: True, SMS: True
```

## Files Modified

| File | Changes |
|------|---------|
| `backend/app/models/schemas.py` | Added SMS models section |
| `backend/app/services/sms_service.py` | Created (new file) |
| `backend/app/services/modem_service.py` | Added threading, _serial_lock, check_sms_ready, send_sms |
| `backend/requirements.txt` | Added phonenumbers>=8.13.0 |

## Patterns Followed

- Config encryption pattern from modem_service.py (encrypt_sensitive_data/decrypt_sensitive_data)
- Audit logging for all config changes
- _run_command pattern (though not needed here - using phonenumbers library instead)
- Thread-safe serial port access with threading.Lock

## Key Decisions

- phonenumbers library version 8.13.0+ for E.164 validation
- GSM charset ("GSM") for message encoding compatibility
- 160 char message truncation for GSM-7 safety
- 30 second timeout for SMS delivery confirmation
- Cooldown tracking via in-memory dict (persists while service runs)

## Ready For

Plan 04-02 can now proceed - SMS Service and modem_service.send_sms() are available for the API layer.
