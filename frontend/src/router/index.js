import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../services/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { public: true }
  },
  {
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue')
  },
  {
    path: '/docker',
    name: 'Docker',
    component: () => import('../views/DockerManager.vue')
  },
  {
    path: '/terminal',
    name: 'Terminal',
    component: () => import('../views/Terminal.vue')
  },
  {
    path: '/interfaces',
    name: 'Interfaces',
    component: () => import('../views/Interfaces.vue'),
    redirect: '/interfaces/modem',
    children: [
      {
        path: 'modem',
        name: 'Modem',
        component: () => import('../views/ModemConfig.vue'),
        meta: { tabLabel: 'Modem', tabIcon: 'mdi-antenna' }
      },
      {
        path: 'serial',
        name: 'Serial',
        component: () => import('../views/SerialConfig.vue'),
        meta: { tabLabel: 'Serial', tabIcon: 'mdi-serial-port' }
      }
    ]
  },
  {
    path: '/network',
    name: 'Network',
    component: () => import('../views/Network.vue'),
    redirect: '/network/failover',
    children: [
      {
        path: 'failover',
        name: 'Failover',
        component: () => import('../views/NetworkStatus.vue'),
        meta: { tabLabel: 'Failover', tabIcon: 'mdi-swap-horizontal', requiresAuth: true }
      },
      {
        path: 'vpn',
        name: 'VPN',
        component: () => import('../views/VpnConfig.vue'),
        meta: { tabLabel: 'VPN', tabIcon: 'mdi-vpn' }
      },
      {
        path: 'wifi',
        name: 'WiFi',
        component: () => import('../views/WifiConfig.vue'),
        meta: { tabLabel: 'WiFi AP', tabIcon: 'mdi-wifi' }
      }
    ]
  },
  {
    path: '/system',
    name: 'System',
    component: () => import('../views/System.vue'),
    redirect: '/system/settings',
    children: [
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('../views/SystemSettings.vue'),
        meta: { tabLabel: 'Settings', tabIcon: 'mdi-cog' }
      },
      {
        path: 'ntp',
        name: 'NtpConfig',
        component: () => import('../views/NtpConfig.vue'),
        meta: { tabLabel: 'NTP', tabIcon: 'mdi-clock-outline', requiresAuth: true }
      },
      {
        path: 'backup',
        name: 'Backup',
        component: () => import('../views/Backup.vue'),
        meta: { tabLabel: 'Backup', tabIcon: 'mdi-backup-restore', requiresAuth: true }
      }
    ]
  },
  {
    path: '/monitoring',
    name: 'Monitoring',
    component: () => import('../views/Monitoring.vue'),
    redirect: '/monitoring/diagnostics',
    children: [
      {
        path: 'diagnostics',
        name: 'Diagnostics',
        component: () => import('../views/Diagnostics.vue'),
        meta: { tabLabel: 'Diagnostics', tabIcon: 'mdi-chart-line' }
      },
      {
        path: 'audit',
        name: 'Audit',
        component: () => import('../views/AuditLog.vue'),
        meta: { tabLabel: 'Audit Log', tabIcon: 'mdi-clipboard-text' }
      },
      {
        path: 'sms-alerts',
        name: 'SmsAlerts',
        component: () => import('../views/SmsAlerts.vue'),
        meta: { tabLabel: 'SMS Alerts', tabIcon: 'mdi-message-text', requiresAuth: true }
      }
    ]
  },
  {
    path: '/thingsboard',
    name: 'ThingsBoard',
    component: () => import('../views/ThingsboardConfig.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Navigation guard
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (!to.meta.public && !authStore.isAuthenticated) {
    next('/login')
  } else if (to.path === '/login' && authStore.isAuthenticated) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router
