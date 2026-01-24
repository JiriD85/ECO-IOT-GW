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
    path: '/vpn',
    name: 'VPN',
    component: () => import('../views/VpnConfig.vue')
  },
  {
    path: '/diagnostics',
    name: 'Diagnostics',
    component: () => import('../views/Diagnostics.vue')
  },
  {
    path: '/modem',
    name: 'Modem',
    component: () => import('../views/ModemConfig.vue')
  },
  {
    path: '/serial',
    name: 'Serial',
    component: () => import('../views/SerialConfig.vue')
  },
  {
    path: '/wifi',
    name: 'WiFi',
    component: () => import('../views/WifiConfig.vue')
  },
  {
    path: '/system',
    name: 'System',
    component: () => import('../views/SystemSettings.vue')
  },
  {
    path: '/ntp',
    name: 'NtpConfig',
    component: () => import('../views/NtpConfig.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/audit',
    name: 'Audit',
    component: () => import('../views/AuditLog.vue')
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
