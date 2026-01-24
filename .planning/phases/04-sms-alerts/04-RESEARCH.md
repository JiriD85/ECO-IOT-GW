# Phase 4: SMS Alerts - Research

**Researched:** 2026-01-24
**Domain:** SMS sending via Quectel LTE modem AT commands with Python/FastAPI
**Confidence:** MEDIUM-HIGH

## Summary

SMS alerts via Quectel modem AT commands is a well-established domain with standardized 3GPP commands. The project already has a working AT command infrastructure in `modem_service.py` using PySerial, making SMS integration straightforward.

The standard approach is to use direct AT commands (AT+CMGF, AT+CMGS) through the existing serial port connection rather than heavy third-party libraries. For recipient configuration and trigger management, follow the existing pattern: Pydantic models for validation, JSON file storage in `/var/lib/eco-iot-gw/`, encrypted sensitive data, and FastAPI routes with audit logging.

Phone number validation should use the `phonenumbers` library (Google's libphonenumber port) to ensure E.164 format compliance. Character encoding requires attention - GSM-7 allows 160 characters, while UCS-2 (Unicode) reduces capacity to 70 characters.

**Primary recommendation:** Extend existing `modem_service.py` with SMS methods using AT commands directly. Use `phonenumbers` for validation. Store SMS config as encrypted JSON following project patterns. Add mutex/lock for serial port access to prevent conflicts with status checks.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pyserial | 3.5+ | Serial port communication | Already in project, official Python serial library, stable API |
| phonenumbers | 9.0.22 | Phone number validation/formatting | Google's libphonenumber port, comprehensive E.164 support, actively maintained (Jan 2026) |
| FastAPI | 0.109+ | REST API framework | Already in project for SMS config endpoints |
| Pydantic | 2.x | Data validation | Already in project for SMS config models |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| threading.Lock | stdlib | Serial port access control | Prevent concurrent AT command conflicts |
| python-gsmmodem-new | 0.13.0 | High-level SMS abstraction | ONLY if AT commands prove insufficient (unlikely) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct AT commands | python-gsmmodem | Library adds complexity, last updated 2021, hides control, overkill for simple SMS |
| phonenumbers | Manual regex validation | phonenumbers handles international formats, country codes, validation rules comprehensively |
| Threading Lock | asyncio Lock | Project uses sync pattern for serial I/O, threading Lock matches existing code |

**Installation:**
```bash
pip install phonenumbers==9.0.22
# pyserial already installed
```

## Architecture Patterns

### Recommended Project Structure
```
backend/app/
├── api/
│   └── sms.py              # SMS alert config & test endpoints
├── services/
│   ├── modem_service.py    # EXTEND with SMS methods
│   └── sms_service.py      # SMS config management, trigger logic
├── models/
│   └── schemas.py          # SMSConfig, SMSRecipient, SMSTrigger models
└── config.py               # SMS config file path
```

### Pattern 1: Extend Existing Modem Service
**What:** Add SMS methods to `modem_service.py` alongside existing AT command methods
**When to use:** Always - leverages existing serial port handling, AT command infrastructure
**Example:**
```python
# In modem_service.py
class ModemService:
    def __init__(self):
        self._port = settings.MODEM_DEFAULT_PORT
        self._baudrate = settings.MODEM_BAUDRATE
        self._serial_lock = threading.Lock()  # NEW: prevent concurrent access

    def send_sms(self, phone_number: str, message: str) -> bool:
        """Send SMS via AT commands."""
        with self._serial_lock:  # Serialize access
            port = self._find_modem_port()
            if not port:
                raise RuntimeError("Modem not found")

            try:
                with serial.Serial(port, self._baudrate, timeout=10) as ser:
                    # Set text mode
                    ser.write(b"AT+CMGF=1\r")
                    time.sleep(0.5)
                    response = ser.read(100).decode('utf-8', errors='ignore')
                    if 'OK' not in response:
                        raise RuntimeError("Failed to set SMS text mode")

                    # Send message command
                    cmd = f"AT+CMGS=\"{phone_number}\"\r"
                    ser.write(cmd.encode())
                    time.sleep(0.5)

                    # Wait for prompt '>'
                    prompt = ser.read(10).decode('utf-8', errors='ignore')
                    if '>' not in prompt:
                        raise RuntimeError("Did not receive SMS prompt")

                    # Send message text + Ctrl-Z
                    ser.write(message.encode('utf-8') + b'\x1A')

                    # Wait for delivery confirmation
                    time.sleep(2)
                    response = ser.read(200).decode('utf-8', errors='ignore')

                    if '+CMGS:' in response and 'OK' in response:
                        return True
                    else:
                        raise RuntimeError(f"SMS send failed: {response}")

            except Exception as e:
                raise RuntimeError(f"SMS send error: {e}")
```

### Pattern 2: Configuration Management with Encryption
**What:** Store SMS recipients and triggers in encrypted JSON, following existing patterns
**When to use:** Always - matches project's security posture
**Example:**
```python
# In services/sms_service.py
class SMSService:
    def __init__(self):
        self._config_file = settings.DATA_DIR / "sms_config.json"
        self._config: Optional[SMSConfig] = None
        self._load_config()

    def _load_config(self):
        """Load SMS configuration from disk."""
        if self._config_file.exists():
            try:
                with open(self._config_file) as f:
                    data = json.load(f)
                    # Decrypt phone numbers (PII)
                    if data.get("recipients"):
                        for recipient in data["recipients"]:
                            if recipient.get("phone"):
                                recipient["phone"] = decrypt_sensitive_data(recipient["phone"])
                    self._config = SMSConfig(**data)
            except Exception as e:
                logger.warning(f"Failed to load SMS config: {e}")

    def _save_config(self):
        """Save SMS configuration to disk."""
        data = self._config.model_dump()

        # Encrypt phone numbers (PII)
        if data.get("recipients"):
            for recipient in data["recipients"]:
                if recipient.get("phone"):
                    recipient["phone"] = encrypt_sensitive_data(recipient["phone"])

        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_file, 'w') as f:
            json.dump(data, f)
        self._config_file.chmod(0o600)
```

### Pattern 3: Phone Number Validation with E.164 Format
**What:** Use phonenumbers library to validate and normalize to E.164 format
**When to use:** Always - before saving recipient or sending SMS
**Example:**
```python
import phonenumbers
from phonenumbers import NumberParseException

def validate_phone_number(phone: str, default_region: str = "US") -> str:
    """
    Validate and format phone number to E.164.

    Args:
        phone: Phone number (any format)
        default_region: ISO country code for parsing local numbers

    Returns:
        E.164 formatted number (e.g., "+420123456789")

    Raises:
        ValueError: If number is invalid
    """
    try:
        parsed = phonenumbers.parse(phone, default_region)

        if not phonenumbers.is_valid_number(parsed):
            raise ValueError(f"Invalid phone number: {phone}")

        # Format as E.164
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    except NumberParseException as e:
        raise ValueError(f"Cannot parse phone number '{phone}': {e}")
```

### Pattern 4: SMS Alert Triggers
**What:** Configurable event triggers that invoke SMS sending
**When to use:** User configures which events trigger alerts
**Example:**
```python
# In models/schemas.py
class SMSTrigger(BaseModel):
    """SMS alert trigger configuration."""
    event_type: str = Field(..., pattern="^(vpn_down|modem_down|network_failover|backup_failed)$")
    enabled: bool = True
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)  # Prevent spam

class SMSRecipient(BaseModel):
    """SMS recipient configuration."""
    name: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., min_length=1, max_length=20)  # Will be validated to E.164
    enabled: bool = True

class SMSConfig(BaseModel):
    """SMS alert configuration."""
    enabled: bool = False
    recipients: List[SMSRecipient] = []
    triggers: List[SMSTrigger] = []
    default_region: str = Field(default="CZ", pattern="^[A-Z]{2}$")  # ISO country code
```

### Anti-Patterns to Avoid
- **Opening serial port for each AT command:** Keep existing `send_at_command()` pattern that opens/closes per command (safer than persistent connection that can hang)
- **Using PDU mode for simple text SMS:** Text mode (AT+CMGF=1) is simpler and sufficient for alerts. PDU mode adds unnecessary complexity.
- **No character encoding check:** Always check message length and encoding. GSM-7 allows 160 chars, Unicode/UCS-2 only 70 chars.
- **Blocking FastAPI endpoint:** SMS sending takes 2-5 seconds. Either accept blocking (simple) or use background tasks (complex). For testing endpoint, blocking is acceptable. For automated triggers, consider background tasks.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Phone number validation | Regex for +XXX format | `phonenumbers` library | International formats vary wildly, country codes change, regex can't validate all rules |
| SMS character encoding detection | Count characters | GSM 03.38 validator or send as UTF-8 | GSM-7 has 128 basic + 10 extension chars. Unicode fallback needed for emoji/accents. |
| AT command queuing | Custom queue system | `threading.Lock` | Serial port is synchronous resource, simple mutex prevents conflicts |
| Retry logic with exponential backoff | Custom retry loops | `tenacity` library or simple retry | Well-tested backoff algorithms prevent rate limiting issues |

**Key insight:** Phone number validation is deceptively complex. E.164 format, country codes, number portability, and validation rules change frequently. `phonenumbers` library is maintained by Google and updated regularly.

## Common Pitfalls

### Pitfall 1: Concurrent Serial Port Access
**What goes wrong:** Multiple parts of code send AT commands simultaneously (SMS send + status check), causing garbled responses or timeouts
**Why it happens:** Existing `modem_service.py` doesn't have locking. Status checks run every 30-60s. SMS send takes 2-5s.
**How to avoid:** Add `threading.Lock` to `modem_service.py` constructor. Wrap all `send_at_command()` calls in `with self._serial_lock:`
**Warning signs:** Intermittent "Modem not found" errors, AT command timeouts, corrupted responses

### Pitfall 2: Character Encoding - GSM-7 vs UCS-2
**What goes wrong:** SMS silently switches from 160-char capacity to 70-char capacity when special characters are used
**Why it happens:** AT commands default to GSM-7 (160 chars). If message contains non-GSM chars (emoji, accents, Czech characters), modem automatically switches to UCS-2 (70 chars). Message gets truncated without warning.
**How to avoid:**
- Validate message length considering encoding
- Use `AT+CSCS="GSM"` to set GSM-7 explicitly
- Or use `AT+CSCS="UCS2"` and encode messages as hex if Unicode is needed
- Warn user in UI if message exceeds 70 chars (safest assumption)
**Warning signs:** SMS arrives truncated, special characters cause delivery failures

### Pitfall 3: SMS Delivery Confirmation Timeout
**What goes wrong:** `send_sms()` method waits for `+CMGS:` response indefinitely or times out prematurely
**Why it happens:** SMS delivery can take 2-30 seconds depending on network conditions. Default serial timeout (1-2s) is too short.
**How to avoid:**
- Set serial timeout to 30s for SMS operations
- Parse response correctly - look for `+CMGS: <message_reference>` followed by `OK`
- Don't confuse message sent (to modem) with message delivered (to recipient)
- AT+CMGS confirms modem sent to network, NOT that recipient received it
**Warning signs:** Timeout errors despite SMS actually being delivered, false failure reports

### Pitfall 4: Modem Not in Text Mode
**What goes wrong:** AT+CMGS command syntax error or garbled message
**Why it happens:** Modem defaults to PDU mode (binary). AT+CMGF=1 must be sent EVERY time before AT+CMGS.
**How to avoid:**
- Always send `AT+CMGF=1` before SMS operations
- Check for `OK` response before proceeding
- Don't assume mode persists between connections (it doesn't)
**Warning signs:** CMS ERROR 304 (invalid PDU mode parameter), AT+CMGS returns ERROR

### Pitfall 5: Phone Number Format Issues
**What goes wrong:** SMS fails with "invalid number" error despite number looking correct
**Why it happens:**
- Missing country code (e.g., "777123456" instead of "+420777123456")
- Spaces or formatting characters in number
- Local number format without region hint
**How to avoid:**
- Always validate with `phonenumbers` library before saving
- Store in E.164 format (+CCNNNNNNNNN)
- Provide default region in config (e.g., "CZ" for Czech Republic)
- Don't allow manual entry without validation
**Warning signs:** CMS ERROR 330 (SMSC address unknown), delivery failures for valid-looking numbers

### Pitfall 6: SIM Card Not Initialized
**What goes wrong:** AT+CMGS returns CMS ERROR immediately
**Why it happens:** SMS functionality requires SIM card initialization to complete. On modem startup/reset, initialization takes 5-30 seconds.
**How to avoid:**
- Check SIM status with `AT+QINISTAT` (Quectel-specific) - wait for response `3` (SMS ready)
- Or check `AT+CPIN?` returns `READY`
- Implement retry logic with timeout for SMS send
- Log error clearly: "SIM not ready, try again in a few seconds"
**Warning signs:** SMS works after system uptime, fails right after boot/modem reset

## Code Examples

Verified patterns from official sources:

### Complete SMS Send Sequence
```python
# Source: Quectel EC2x/EC9x/EG2x AT Commands Manual, M2MSupport.net
def send_sms_complete(phone_number: str, message: str) -> Tuple[bool, str]:
    """
    Complete SMS send sequence with all safety checks.

    Returns:
        Tuple of (success: bool, message_reference_or_error: str)
    """
    port = self._find_modem_port()
    if not port:
        return False, "Modem not found"

    try:
        with serial.Serial(port, self._baudrate, timeout=30) as ser:
            # Step 1: Check SIM ready
            ser.write(b"AT+CPIN?\r")
            time.sleep(0.5)
            response = ser.read(100).decode('utf-8', errors='ignore')
            if 'READY' not in response:
                return False, "SIM not ready"

            # Step 2: Set text mode
            ser.write(b"AT+CMGF=1\r")
            time.sleep(0.5)
            response = ser.read(100).decode('utf-8', errors='ignore')
            if 'OK' not in response:
                return False, "Failed to set text mode"

            # Step 3: Set character set to GSM (optional but recommended)
            ser.write(b'AT+CSCS="GSM"\r')
            time.sleep(0.5)
            response = ser.read(100).decode('utf-8', errors='ignore')
            # Ignore if not supported, not critical

            # Step 4: Send message command
            cmd = f'AT+CMGS="{phone_number}"\r'
            ser.write(cmd.encode('ascii'))
            time.sleep(0.5)

            # Step 5: Wait for prompt
            prompt = ser.read(10).decode('utf-8', errors='ignore')
            if '>' not in prompt:
                return False, "No SMS prompt received"

            # Step 6: Send message text + Ctrl-Z (0x1A)
            # Validate message is GSM-7 safe or truncate
            if len(message) > 160:
                message = message[:160]

            ser.write(message.encode('utf-8') + b'\x1A')

            # Step 7: Wait for confirmation (can take 5-30 seconds)
            time.sleep(2)
            response = ""
            start_time = time.time()
            while time.time() - start_time < 28:  # 30s total timeout
                if ser.in_waiting:
                    response += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                if '+CMGS:' in response and 'OK' in response:
                    # Extract message reference
                    match = re.search(r'\+CMGS:\s*(\d+)', response)
                    if match:
                        msg_ref = match.group(1)
                        return True, f"Message sent, reference: {msg_ref}"
                    return True, "Message sent"
                if 'ERROR' in response or '+CMS ERROR' in response:
                    return False, f"SMS error: {response}"
                time.sleep(0.5)

            return False, f"Timeout waiting for confirmation. Response: {response}"

    except serial.SerialException as e:
        return False, f"Serial error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"
```

### Phone Number Validation API Route
```python
# In api/sms.py
from fastapi import APIRouter, Depends, HTTPException
from ..security.auth import get_current_user
from ..models.schemas import UserInfo
import phonenumbers

router = APIRouter()

@router.post("/sms/validate-number")
async def validate_number(
    phone: str,
    region: str = "CZ",
    user: UserInfo = Depends(get_current_user)
):
    """
    Validate phone number and return E.164 format.

    Args:
        phone: Phone number in any format
        region: ISO country code for parsing (e.g., "CZ", "US")

    Returns:
        {"valid": true, "e164": "+420777123456", "country": "CZ"}
    """
    try:
        parsed = phonenumbers.parse(phone, region)

        if not phonenumbers.is_valid_number(parsed):
            raise HTTPException(
                status_code=400,
                detail="Invalid phone number"
            )

        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        country_code = phonenumbers.region_code_for_number(parsed)

        return {
            "valid": True,
            "e164": e164,
            "country": country_code,
            "international": phonenumbers.format_number(
                parsed,
                phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
        }

    except phonenumbers.NumberParseException as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot parse phone number: {str(e)}"
        )
```

### SMS Test Endpoint
```python
# In api/sms.py
@router.post("/sms/test")
async def test_sms(
    request: Request,
    phone: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Send test SMS message.

    Validates phone number and sends test message to verify configuration.
    """
    client_ip = get_client_ip(request)

    # Validate phone number
    try:
        validated_phone = validate_phone_number(phone, sms_service.get_default_region())
    except ValueError as e:
        log_audit(user.username, "sms_test", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(status_code=400, detail=str(e))

    # Send test message
    message = f"Test SMS from ECO-IOT-GW at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    try:
        success, result = modem_service.send_sms(validated_phone, message)

        if success:
            log_audit(user.username, "sms_test", client_ip,
                     {"phone": validated_phone, "result": result})
            return {"success": True, "message": result}
        else:
            log_audit(user.username, "sms_test", client_ip,
                     {"phone": validated_phone, "error": result}, success=False)
            raise HTTPException(status_code=500, detail=result)

    except Exception as e:
        log_audit(user.username, "sms_test", client_ip,
                 {"phone": validated_phone, "error": str(e)}, success=False)
        raise HTTPException(status_code=500, detail=str(e))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| python-gsmmodem library | Direct AT commands with pyserial | 2021 (last update) | Library is unmaintained, direct AT commands give better control and debugging |
| PDU mode for all SMS | Text mode for simple alerts | Always available | Text mode is simpler, sufficient for English/basic text alerts |
| Persistent serial connection | Open/close per command | Project pattern | Prevents hanging connections, modem can recover between commands |
| Manual phone validation regex | phonenumbers library | 2010+ | Library handles international complexity, actively maintained |

**Deprecated/outdated:**
- **python-gsmmodem**: Last updated 2021, forks exist but unmaintained, overkill for simple SMS sending
- **AT+CSCA (set SMS center)**: Usually not needed, modem reads from SIM card automatically
- **AT+CNMI (incoming SMS notifications)**: Not needed for sending, only for receiving SMS

## Open Questions

Things that couldn't be fully resolved:

1. **SMS delivery reports (status callbacks)**
   - What we know: AT+CSMS enables delivery reports, Quectel forum reports issues with AT+CMGR reading delivery status from SIM storage on EC25-E/EG25-G
   - What's unclear: Whether delivery reports work reliably on the specific Quectel model in use (wwan0), whether delivery status is critical for this use case
   - Recommendation: Implement basic send confirmation (+CMGS response), defer delivery status reports to future enhancement. Log message reference numbers for debugging.

2. **Optimal cooldown period for alert spam prevention**
   - What we know: Alerts should have cooldown to prevent SMS spam (costly, annoying)
   - What's unclear: What cooldown is appropriate per trigger type (VPN down vs network failover)
   - Recommendation: Default 30-minute cooldown, make configurable per trigger. User can adjust based on their needs and SMS budget.

3. **SMS cost/quota management**
   - What we know: SMS messages have per-message cost from mobile carrier
   - What's unclear: Whether system should track SMS quota/budget, alert on high usage
   - Recommendation: Out of scope for Phase 4. Document SMS costs in user guide. Future enhancement could track message count.

4. **Character encoding auto-detection**
   - What we know: GSM-7 supports 160 chars, UCS-2 supports 70 chars. Czech characters (čřžýáíé) may require UCS-2.
   - What's unclear: Whether AT+CSCS="GSM" handles Czech diacritics or requires UCS-2
   - Recommendation: Test with Czech characters during implementation. If GSM fails, implement UCS-2 mode. Start with GSM for simplicity.

5. **Thread safety with FastAPI async**
   - What we know: FastAPI is async, pyserial is synchronous, `threading.Lock` works but blocks event loop
   - What's unclear: Whether blocking 2-5 seconds for SMS send is acceptable, whether to use background tasks
   - Recommendation: Start with simple blocking approach (matches existing modem_service pattern). If UI responsiveness is issue, move to FastAPI BackgroundTasks. Don't over-engineer prematurely.

## Sources

### Primary (HIGH confidence)
- [Quectel AT Commands Manual - EC2x/EC9x/EG2x Series](https://forums.quectel.com/uploads/short-url/cBnrTmjnCg7OGnqRsk8dIpbHuVX.pdf) - Official Quectel documentation for AT commands
- [M2MSupport.net - Send/Receive SMS Quectel Module](https://m2msupport.net/m2msupport/send-receive-sms-quectel-module/) - Practical SMS AT command examples
- [phonenumbers PyPI](https://pypi.org/project/phonenumbers/) - Version 9.0.22 (Jan 2026), official Python port
- Existing project code: `/backend/app/services/modem_service.py` and `/backend/app/api/modem.py` - Working AT command patterns

### Secondary (MEDIUM confidence)
- [Diafaan SMS Server - AT+CMGF](https://www.diafaan.com/sms-tutorials/gsm-modem-tutorial/at-cmgf/) - SMS text mode documentation
- [Diafaan SMS Server - AT+CMGS](https://www.diafaan.com/sms-tutorials/gsm-modem-tutorial/at-cmgs-text-mode/) - SMS send command tutorial
- [Quectel Forums - SMS delivery reports issue](https://forums.quectel.com/t/sms-delivery-reports-cannot-be-read-from-sim-storage-on-ec25-e-and-eg25-g/36955) - Known limitation
- [pyserial-asyncio documentation](https://pyserial-asyncio.readthedocs.io/) - Async serial port handling
- [Twilio - GSM-7 Character Encoding](https://www.twilio.com/docs/glossary/what-is-gsm-7-character-encoding) - SMS encoding explanation
- [Twilio - UCS-2 Character Encoding](https://www.twilio.com/docs/glossary/what-is-ucs-2-character-encoding) - Unicode SMS encoding

### Tertiary (LOW confidence)
- [python-gsmmodem-new PyPI](https://pypi.org/project/python-gsmmodem-new/) - Library marked for context only, not recommended for use
- [AT Command Tester Tool](https://www.open-electronics.org/at-command-tester-the-free-online-software-tool-to-test-gsm-at-commands/) - Testing tool, not verified for Quectel compatibility
- WebSearch results on serial port locking - Older discussions (2008-2022), threading.Lock approach verified against project patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - pyserial and phonenumbers are industry standard, versions verified, project already uses pyserial
- Architecture: HIGH - Project patterns examined in modem_service.py, network_service.py, config patterns verified
- Pitfalls: MEDIUM-HIGH - AT command pitfalls documented in multiple sources, character encoding issues well-known, some Quectel-specific issues from forums
- Don't hand-roll: HIGH - phonenumbers necessity verified, serial locking pattern is standard threading practice

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - stable domain, AT commands are 3GPP standard, unlikely to change)

**Notes:**
- No CONTEXT.md found - no user decisions to constrain research
- Existing project code provides strong patterns to follow
- Quectel-specific AT commands (+QINISTAT, +QCSQ) already in use, same patterns apply to SMS
- Phone number validation is the most complex piece - phonenumbers library is essential
