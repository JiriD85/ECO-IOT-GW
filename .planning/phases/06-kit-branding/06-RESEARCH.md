# Phase 6: Kit Identification & Branding - Research

**Researched:** 2026-01-24
**Domain:** Vue 3 + Vuetify 3 Branding, File Upload, Theme Toggle
**Confidence:** HIGH

## Summary

This phase adds kit identification (custom name like DBKIT25EU-0099), branding (logo/favicon upload), and theme switching to the ECO-IOT-GW application.

## Existing Patterns to Follow

### Backend
- Config storage: JSON files in `/etc/eco-iot-gw/` (see `secrets.env` pattern)
- File storage: `/var/lib/eco-iot-gw/` for data files
- WiFi SSID: `wifi_service.py` has `set_config()` method that sets SSID in hostapd.conf
- API pattern: Router in `api/`, service in `services/`, schemas in `models/schemas.py`

### Frontend
- Login.vue shows "ECO-IOT-GW" in toolbar title (line 7)
- App.vue shows "ECO-IOT-GW" in drawer header (line 19)
- Composables in `src/composables/` for shared state

## Implementation Approach

### Kit Name Storage
```json
// /etc/eco-iot-gw/branding.json
{
  "kit_name": "DBKIT25EU-0099",
  "theme": "light"
}
```

### Logo/Favicon Storage
```
/var/lib/eco-iot-gw/branding/
├── logo.png      # User uploaded logo
└── favicon.ico   # User uploaded favicon
```

### WLAN SSID Update
When kit_name changes, call `wifi_service.set_config()` with new SSID.

### Theme Toggle
Vuetify 3 uses `useTheme()` composable:
```javascript
import { useTheme } from 'vuetify'
const theme = useTheme()
theme.global.name.value = 'dark' // or 'light'
```

### Dynamic Favicon
VueUse `useFavicon()` or manual DOM manipulation:
```javascript
const link = document.querySelector("link[rel*='icon']")
link.href = '/api/branding/favicon'
```

### Composable Pattern for Branding
```javascript
// useBranding.js - singleton pattern
let kitName = ref('ECO-IOT-GW')
let logoUrl = ref(null)

export function useBranding() {
  const loadBranding = async () => {
    const response = await brandingApi.getConfig()
    kitName.value = response.kit_name || 'ECO-IOT-GW'
    logoUrl.value = response.has_logo ? '/api/branding/logo' : null
  }
  return { kitName, logoUrl, loadBranding }
}
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| /api/branding/config | GET | Get kit_name, theme, has_logo, has_favicon |
| /api/branding/config | PUT | Update kit_name and/or theme |
| /api/branding/logo | GET | Serve logo image |
| /api/branding/logo | POST | Upload logo (multipart/form-data) |
| /api/branding/logo | DELETE | Remove custom logo |
| /api/branding/favicon | GET | Serve favicon |
| /api/branding/favicon | POST | Upload favicon |
| /api/branding/favicon | DELETE | Remove custom favicon |

## Files to Create/Modify

### Backend
- **NEW**: `backend/app/services/branding_service.py` - Config and file management
- **NEW**: `backend/app/api/branding.py` - API endpoints
- **MODIFY**: `backend/app/models/schemas.py` - Add BrandingConfig schema
- **MODIFY**: `backend/app/main.py` - Register branding router

### Frontend
- **NEW**: `frontend/src/views/AdminConfig.vue` - Kit name, logo/favicon upload
- **NEW**: `frontend/src/composables/useBranding.js` - Shared branding state
- **MODIFY**: `frontend/src/views/System.vue` - Add Admin tab
- **MODIFY**: `frontend/src/router/index.js` - Add admin child route
- **MODIFY**: `frontend/src/views/Login.vue` - Show kit name and logo
- **MODIFY**: `frontend/src/App.vue` - Show kit name, theme toggle
- **MODIFY**: `frontend/src/services/api.js` - Add brandingApi

## Pitfalls to Avoid

1. **File size limits**: Limit logo to 1MB, favicon to 100KB
2. **Image format validation**: Accept only PNG, JPG, SVG for logo; ICO, PNG for favicon
3. **SSID length limit**: Max 32 characters for WiFi SSID
4. **Theme flicker**: Load theme preference before app renders
5. **Caching**: Add cache-busting query param when logo/favicon changes
