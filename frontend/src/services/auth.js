import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from './api'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(localStorage.getItem('accessToken') || null)
  const refreshToken = ref(localStorage.getItem('refreshToken') || null)
  const user = ref(null)

  const isAuthenticated = computed(() => !!accessToken.value)

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
    isAuthenticated,
    login,
    logout,
    fetchUser,
    refreshAccessToken,
    clearTokens
  }
})
