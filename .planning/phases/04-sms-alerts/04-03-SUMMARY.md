# Plan 04-03 Summary: Frontend SMS Alerts View

## Status: COMPLETE (pending human verification)

## What Was Built

### Task 1: smsApi in api.js

Added smsApi object following ntpApi/networkApi patterns:

```javascript
export const smsApi = {
  getConfig: () => api.get('/api/sms/config'),
  setConfig: (config) => api.put('/api/sms/config', config),
  addRecipient: (recipient) => api.post('/api/sms/recipients', recipient),
  removeRecipient: (name) => api.delete(`/api/sms/recipients/${encodeURIComponent(name)}`),
  validateNumber: (phone, region = 'CZ') => api.post('/api/sms/validate-number', null, { params: { phone, region } }),
  testSms: (phone, message = null) => api.post('/api/sms/test', { phone, message }),
  getTriggers: () => api.get('/api/sms/triggers')
}
```

### Task 2: SmsAlerts.vue Component

Created comprehensive SMS configuration UI with 4 cards:

1. **SMS Configuration Card**
   - Enable/disable toggle
   - Default region selector (CZ, DE, AT, SK, PL, US, GB)
   - Admin-only save button

2. **Test SMS Card**
   - Phone input with real-time validation
   - Shows E.164 format when valid
   - Optional message textarea (160 char limit)
   - Send Test button
   - Result display (success/error with message reference)

3. **Recipients Card**
   - v-data-table with name, phone, status, actions
   - Add Recipient dialog with validation
   - Delete confirmation dialog
   - Admin-only controls

4. **Triggers Card**
   - Grid of trigger toggles (vpn_down, modem_down, network_failover, backup_failed)
   - Shows cooldown for each trigger
   - Admin-only controls

Features:
- Role-based access control (admin checks)
- Phone validation on blur
- E.164 format display
- Snackbar notifications
- Loading states on all buttons
- Error alerts

### Task 3: Route and Navigation

- Added route `/sms-alerts` → `SmsAlerts.vue` with `requiresAuth: true`
- Added navigation item with `mdi-message-text` icon after Network

## Verification Results

```bash
# smsApi in api.js
node -e "..." # Result: smsApi found

# Route in router
node -e "..." # Result: Route found

# Frontend build
npm run build # Result: ✓ built in 1.55s
# SmsAlerts-BGvwAgwG.js (11.12 kB gzip: 3.40 kB)
```

## Files Modified

| File | Changes |
|------|---------|
| `frontend/src/services/api.js` | Added smsApi object |
| `frontend/src/views/SmsAlerts.vue` | Created (new file, ~400 lines) |
| `frontend/src/router/index.js` | Added /sms-alerts route |
| `frontend/src/App.vue` | Added SMS Alerts nav item |

## Patterns Followed

- ntpApi pattern for API calls
- NtpConfig.vue pattern for card layout
- NetworkStatus.vue pattern for admin-only controls
- useAuthStore for role checking
- Snackbar for notifications
- v-data-table for recipients list
- v-dialog for add/delete confirmations

## UI Features

| Feature | Implementation |
|---------|----------------|
| Phone validation | validateNumber API on blur, shows E.164 chip |
| Admin-only | `:disabled="!isAdmin"` on controls |
| Loading states | `:loading` prop on all action buttons |
| Error handling | v-alert for errors, snackbar for success |
| Config changes | Track original config, enable save only on change |
| Confirmation | Delete dialog before removing recipients |

## Checkpoint (Task 4)

**Human verification required** before continuing:

1. Start backend: `cd backend && source venv/bin/activate && uvicorn app.main:app --reload`
2. Start frontend: `cd frontend && npm run dev`
3. Open http://localhost:3000 and login
4. Navigate to "SMS Alerts" in sidebar
5. Verify:
   - Configuration card shows enabled toggle and region selector
   - Recipients table loads (may be empty)
   - Test SMS section has phone input and send button
6. Try adding a recipient (admin only)
7. Try phone validation (enter number, tab out) - verify E.164 format shown
8. **REQUIRED**: Send test SMS to verify modem communication

## Ready For

Plan 04-04 (SMS Alert Daemon) can run in parallel once human verification passes.
