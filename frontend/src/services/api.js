import axios from 'axios'

const api = axios.create({
  baseURL: window.location.origin,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Response interceptor for handling errors
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Handle 401 Unauthorized
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true

      // Try to refresh token
      const { useAuthStore } = await import('./auth')
      const authStore = useAuthStore()

      if (await authStore.refreshAccessToken()) {
        originalRequest.headers['Authorization'] = `Bearer ${authStore.accessToken}`
        return api(originalRequest)
      }

      // Refresh failed. A locked action needs a login — send them to the login
      // page and bring them back afterwards. (Open pages never hit this.)
      if (!window.location.pathname.startsWith('/login')) {
        const redirect = encodeURIComponent(window.location.pathname + window.location.search)
        window.location.href = `/login?redirect=${redirect}`
      }
    }

    return Promise.reject(error)
  }
)

export default api

// API helper functions
export const dockerApi = {
  getStatus: () => api.get('/api/docker/status'),
  getCompose: () => api.get('/api/docker/compose'),
  uploadCompose: (content) => api.post('/api/docker/compose', { content, filename: 'docker-compose.yml' }),
  uploadComposeFile: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/api/docker/compose/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  composeUp: () => api.post('/api/docker/up'),
  composeDown: () => api.post('/api/docker/down'),
  getLogs: (containerName, lines = 100) => api.get(`/api/docker/logs/${containerName}?lines=${lines}`)
}

export const vpnApi = {
  getStatus: () => api.get('/api/vpn/status'),
  getType: () => api.get('/api/vpn/type'),
  setType: (vpnType) => api.put('/api/vpn/type', null, { params: { vpn_type: vpnType } }),
  uploadConfig: (file, vpnType) => {
    const formData = new FormData()
    formData.append('file', file)
    if (vpnType) {
      formData.append('vpn_type', vpnType)
    }
    return api.post('/api/vpn/config/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  connect: () => api.post('/api/vpn/connect'),
  disconnect: () => api.post('/api/vpn/disconnect'),
  getAutostart: () => api.get('/api/vpn/autostart'),
  setAutostart: (enabled) => api.put('/api/vpn/autostart', { enabled })
}

export const modemApi = {
  getStatus: () => api.get('/api/modem/status'),
  getConfig: () => api.get('/api/modem/config'),
  setConfig: (config) => api.put('/api/modem/config', config),
  connect: () => api.post('/api/modem/connect'),
  disconnect: () => api.post('/api/modem/disconnect'),
  reset: () => api.post('/api/modem/reset')
}

export const serialApi = {
  getPorts: () => api.get('/api/serial/ports'),
  getConfig: () => api.get('/api/serial/config'),
  setConfig: (config) => api.put('/api/serial/config', config),
  testPort: () => api.post('/api/serial/test')
}

export const wifiApi = {
  getStatus: () => api.get('/api/wifi/ap/status'),
  getConfig: () => api.get('/api/wifi/ap/config'),
  setConfig: (config) => api.put('/api/wifi/ap/config', config),
  start: () => api.post('/api/wifi/ap/start'),
  stop: () => api.post('/api/wifi/ap/stop'),
  getClients: () => api.get('/api/wifi/ap/clients')
}

export const systemApi = {
  getStatus: () => api.get('/api/system/status'),
  reboot: (delay = 0) => api.post('/api/system/reboot', { delay_seconds: delay }),
  shutdown: () => api.post('/api/system/shutdown'),
  getUpdateStatus: () => api.get('/api/system/update/status'),
  startUpdate: (version = null) => api.post('/api/system/update', { version }),
  rollback: () => api.post('/api/system/rollback')
}

export const diagnosticsApi = {
  getConnectivity: () => api.get('/api/diagnostics/connectivity'),
  getModbusValues: (device = null, limit = 100) => api.get('/api/diagnostics/modbus', { params: { device, limit } }),
  getGatewayLogs: (level = null, limit = 100) => api.get('/api/diagnostics/gateway/logs', { params: { level, limit } }),
  getGatewayStatus: () => api.get('/api/diagnostics/gateway/status')
}

export const watchdogApi = {
  getStatus: () => api.get('/api/watchdog/status'),
  getConfig: () => api.get('/api/watchdog/config'),
  setConfig: (config) => api.put('/api/watchdog/config', config),
  enable: () => api.post('/api/watchdog/enable'),
  disable: () => api.post('/api/watchdog/disable')
}

export const auditApi = {
  getLogs: (params = {}) => api.get('/api/audit/logs', { params }),
  getStats: (days = 7) => api.get('/api/audit/stats', { params: { days } })
}

export const ntpApi = {
  // Configuration
  getConfig: () => api.get('/api/ntp/config'),
  setConfig: (config) => api.put('/api/ntp/config', config),

  // Status
  getStatus: () => api.get('/api/ntp/status'),
  getSources: () => api.get('/api/ntp/sources'),

  // Timezone
  getTimezones: () => api.get('/api/ntp/timezones'),
  getTimezone: () => api.get('/api/ntp/timezone'),
  setTimezone: (timezone) => api.put('/api/ntp/timezone', { timezone })
}

export const backupApi = {
  // Create and download backup
  create: () => api.post('/api/backup/create', null, {
    responseType: 'blob'  // Important: receive as blob for file download
  }),

  // Upload and restore from backup
  restore: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/api/backup/restore', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  // Validate backup without restoring
  validate: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/api/backup/validate', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  }
}

// SMS Alerts API
export const smsApi = {
  // Configuration
  getConfig: () => api.get('/api/sms/config'),
  setConfig: (config) => api.put('/api/sms/config', config),

  // Recipients
  addRecipient: (recipient) => api.post('/api/sms/recipients', recipient),
  removeRecipient: (name) => api.delete(`/api/sms/recipients/${encodeURIComponent(name)}`),

  // Phone validation
  validateNumber: (phone, region = 'CZ') => api.post('/api/sms/validate-number', null, {
    params: { phone, region }
  }),

  // Test SMS
  testSms: (phone, message = null) => api.post('/api/sms/test', { phone, message }),

  // Get available triggers
  getTriggers: () => api.get('/api/sms/triggers')
}

// Network Failover API
export const networkApi = {
  // Get current network status for all interfaces
  getStatus: () => api.get('/api/network/status'),

  // Get detailed status for specific interface
  getInterface: (interfaceName) => api.get(`/api/network/interfaces/${interfaceName}`),

  // Get current failover configuration
  getFailoverConfig: () => api.get('/api/network/failover/config'),

  // Set failover configuration (admin only)
  setFailoverConfig: (config) => api.put('/api/network/failover/config', config),

  // Test connectivity on specific interface
  testConnectivity: (interfaceName, target = '8.8.8.8') =>
    api.post('/api/network/connectivity/test', {
      interface: interfaceName,
      target
    }),
}

// Auth API
export const authApi = {
  changePassword: (currentPassword, newPassword) => api.post('/api/auth/change-password', null, {
    params: { current_password: currentPassword, new_password: newPassword }
  })
}

// Meters / connector health - read-only. Latest child-device telemetry + connector status,
// parsed from the gateway (no direct bus access, no local editing). Editing stays in ThingsBoard.
export const metersApi = {
  getLatest: () => api.get('/api/meters/latest')
}

// Branding API
export const brandingApi = {
  getConfig: () => api.get('/api/branding/config'),
  updateConfig: (config) => api.put('/api/branding/config', config),

  uploadLogo: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/api/branding/logo', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  deleteLogo: () => api.delete('/api/branding/logo'),
  getLogoUrl: () => '/api/branding/logo',

  uploadFavicon: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/api/branding/favicon', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  deleteFavicon: () => api.delete('/api/branding/favicon'),
  getFaviconUrl: () => '/api/branding/favicon'
}
