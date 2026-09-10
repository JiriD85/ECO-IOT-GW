import { ref } from 'vue'
import companyLogo from '../assets/eco-energy.svg'

import { brandingApi } from '../services/api'

// Module-scope state (singleton pattern)
const kitName = ref('ECO-IOT-GW')
const hasLogo = ref(false)
const hasFavicon = ref(false)
const logoUrl = ref(companyLogo)
const faviconUrl = ref(null)
const isLoaded = ref(false)

const themeName = ref(localStorage.getItem('theme') || 'light')
let adminTheme
export function setAdminTheme(vuetify) {
  adminTheme = vuetify.theme
  adminTheme.global.name.value = themeName.value
}
function applyTheme(name) {
  themeName.value = name
  document.documentElement.dataset.theme = name
  if (adminTheme) adminTheme.global.name.value = name
}
applyTheme(themeName.value)
let loading
export function useBranding() {

  const fetchBranding = async (refreshAssets = false) => {
    try {
      const response = await brandingApi.getConfig()
      kitName.value = response.data.kit_name || 'ECO-IOT-GW'
      hasLogo.value = response.data.has_logo
      hasFavicon.value = response.data.has_favicon

      const revision = refreshAssets ? `?v=${Date.now()}` : ''
      logoUrl.value = hasLogo.value ? '/api/branding/logo' + revision : companyLogo
      faviconUrl.value = hasFavicon.value ? '/api/branding/favicon' + revision : companyLogo

      // Apply theme
      const savedTheme = localStorage.getItem('theme') || response.data.theme || 'light'
      applyTheme(savedTheme)

      // Update favicon
      updateFavicon(faviconUrl.value)

      isLoaded.value = true
    } catch (error) {
      console.error('Failed to load branding:', error)
      isLoaded.value = true
    }
  }

  const loadBranding = (force = false) => {
    if (force) loading = null
    return loading ||= fetchBranding(force)
  }

  const toggleTheme = async () => {
    const newTheme = themeName.value === 'light' ? 'dark' : 'light'
    applyTheme(newTheme)
    localStorage.setItem('theme', newTheme)

  }

  const updateFavicon = (url) => {
    let link = document.querySelector("link[rel*='icon']")
    if (!link) {
      link = document.createElement('link')
      link.rel = 'icon'
      document.head.appendChild(link)
    }
    link.href = url
  }

  const isDark = () => themeName.value === 'dark'

  return {
    kitName,
    hasLogo,
    hasFavicon,
    logoUrl,
    faviconUrl,
    isLoaded,
    loadBranding,
    toggleTheme,
    isDark
  }
}
