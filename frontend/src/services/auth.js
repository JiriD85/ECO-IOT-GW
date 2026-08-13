import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from './api'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(localStorage.getItem('accessToken') || null)
  const refreshToken = ref(localStorage.getItem('refreshToken') || null)
  const user = ref(null)

  // Session identity resolved from the backend (Tailscale login or password user)
  const identity = ref(null)
  const authMethod = ref(null)   // 'tailscale' | 'password' | null
  const sessionChecked = ref(false)
  let sessionPromise = null

  // Authenticated if we hold a token OR the tailnet already identifies us.
  const isAuthenticated = computed(() => !!accessToken.value || authMethod.value === 'tailscale')

  const setTokens = (access, refresh) => {
    accessToken.value = access
    refreshToken.value = refresh
    localStorage.setItem('accessToken', access)
    localStorage.setItem('refreshToken', refresh)
    api.defaults.headers.common['Authorization'] = `Bearer ${access}`
  }

  const clearTokens = () => {
    accessToken.value = null
    refreshToken.value = null
    user.value = null
    localStorage.removeItem('accessToken')
    localStorage.removeItem('refreshToken')
    delete api.defaults.headers.common['Authorization']
  }

  const login = async (username, password) => {
    try {
      const response = await api.post('/api/auth/login', { username, password })
      setTokens(response.data.access_token, response.data.refresh_token)
      identity.value = username
      authMethod.value = 'password'
      await fetchUser()
      return { success: true }
    } catch (error) {
      const message = error.response?.data?.detail || 'Login failed'
      return { success: false, error: message }
    }
  }

  const logout = async () => {
    try {
      await api.post('/api/auth/logout')
    } catch (error) {
      // Ignore errors during logout
    }
    clearTokens()
    // Re-evaluate: over the tailnet we're still identified even without a token.
    sessionPromise = null
    await checkSession()
  }

  // Ask the backend who we are (open endpoint). Over Tailscale this returns our
  // SSO login with no token; locally it reflects any bearer token we hold.
  // Returns true only when we got a definitive answer from the server.
  const checkSession = async () => {
    try {
      const res = await api.get('/api/auth/whoami', { timeout: 8000 })
      identity.value = res.data.authenticated ? res.data.identity : null
      authMethod.value = res.data.authenticated ? res.data.method : null
      sessionChecked.value = true
      return true
    } catch (error) {
      // Network blip (flaky tailnet/SIM): don't downgrade to anonymous here.
      return false
    }
  }

  // Resolve the session once, with a retry so a single dropped request over a
  // flaky link doesn't wrongly bounce a Tailscale user to the login page.
  const ensureSession = async () => {
    if (sessionChecked.value) return
    if (!sessionPromise) {
      sessionPromise = (async () => {
        let ok = await checkSession()
        if (!ok) {
          await new Promise((r) => setTimeout(r, 400))
          ok = await checkSession()
        }
        // If still unresolved, allow a later navigation to try again.
        sessionPromise = null
      })()
    }
    return sessionPromise
  }

  const fetchUser = async () => {
    try {
      const response = await api.get('/api/auth/me')
      user.value = response.data
    } catch (error) {
      clearTokens()
    }
  }

  const refreshAccessToken = async () => {
    if (!refreshToken.value) {
      clearTokens()
      return false
    }

    try {
      const response = await api.post('/api/auth/refresh', {
        refresh_token: refreshToken.value
      })
      setTokens(response.data.access_token, response.data.refresh_token)
      return true
    } catch (error) {
      clearTokens()
      return false
    }
  }

  // Initialize auth header if token exists
  if (accessToken.value) {
    api.defaults.headers.common['Authorization'] = `Bearer ${accessToken.value}`
  }

  return {
    accessToken,
    refreshToken,
    user,
    identity,
    authMethod,
    sessionChecked,
    isAuthenticated,
    login,
    logout,
    fetchUser,
    refreshAccessToken,
    clearTokens,
    checkSession,
    ensureSession
  }
})
