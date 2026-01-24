# Plan 04-02 Summary: Backend SMS API

## Status: COMPLETE

## What Was Built

### Task 1: SMS API Router (sms.py)

Created SMS API router with 7 endpoints following ntp.py patterns:

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/config` | User | Get SMS configuration |
| PUT | `/config` | Admin | Update SMS configuration |
| POST | `/recipients` | Admin | Add SMS recipient |
| DELETE | `/recipients/{name}` | Admin | Remove SMS recipient |
| POST | `/validate-number` | User | Validate phone number |
| POST | `/test` | User | Send test SMS |
| GET | `/triggers` | User | Get available trigger types |

Key features:
- `get_client_ip()` helper for audit logging
- Admin role check for config changes
- Phone number validation with E.164 normalization
- Test SMS with default timestamp message
- Proper error handling (400 for validation, 403 for auth, 500 for server errors)

### Task 2: Router Registration (main.py)

- Added `sms` import to API imports
- Registered router at `/api/sms` with tag "SMS Alerts"

## Verification Results

```bash
# Router endpoints
python -c "from app.api.sms import router; print('Endpoints:', len(router.routes))"
# Result: Endpoints: 7

# Route paths
python -c "from app.api.sms import router; print([r.path for r in router.routes])"
# Result: ['/config', '/config', '/recipients', '/recipients/{name}', '/validate-number', '/test', '/triggers']
```

## Files Modified

| File | Changes |
|------|---------|
| `backend/app/api/sms.py` | Created (new file) - 7 endpoints |
| `backend/app/main.py` | Added sms import and router registration |

## Patterns Followed

- `get_client_ip()` helper from ntp.py
- Admin role check pattern: `if user.role != "admin": raise HTTPException(403)`
- Audit logging for all state-changing operations
- HTTPException re-raise pattern for proper error propagation
- Response models for structured responses

## Key Decisions

- `/validate-number` uses query params (phone, region) for simplicity
- `/test` returns SMSTestResponse even on failure (not HTTP error) for better UX
- `/triggers` returns static list of available trigger types with descriptions
- Any authenticated user can test SMS (not admin-only) for easier troubleshooting

## API Examples

```bash
# Get config
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/sms/config

# Update config (admin)
curl -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"enabled":true,"recipients":[{"name":"Admin","phone":"+420777123456","enabled":true}],"triggers":[],"default_region":"CZ"}' \
  http://localhost:8000/api/sms/config

# Validate phone number
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/sms/validate-number?phone=777123456&region=CZ"

# Send test SMS
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"phone":"+420777123456"}' \
  http://localhost:8000/api/sms/test
```

## Ready For

- Plan 04-03: Frontend can now call these API endpoints
- Plan 04-04: SMS alert daemon can use the service layer (already using sms_service.py)
