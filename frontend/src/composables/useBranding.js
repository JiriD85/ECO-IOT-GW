import { ref } from 'vue'
import { useTheme } from 'vuetify'
import { brandingApi } from '../services/api'

// Module-scope state (singleton pattern)
const kitName = ref('ECO-IOT-GW')
const hasLogo = ref(false)
const hasFavicon = ref(false)
const logoUrl = ref(null)
const faviconUrl = ref(null)
const isLoaded = ref(false)

export function useBranding() {
  const theme = useTheme()

  const loadBranding = async () => {
    try {
      const response = await brandingApi.getConfig()
      kitName.value = response.data.kit_name || 'ECO-IOT-GW'
      hasLogo.value = response.data.has_logo
      hasFavicon.value = response.data.has_favicon

      // Add cache-busting param
      const timestamp = Date.now()
      logoUrl.value = hasLogo.value ? `/api/branding/logo?t=${timestamp}` : null
      faviconUrl.value = hasFavicon.value ? `/api/branding/favicon?t=${timestamp}` : null

      // Apply theme
      const savedTheme = response.data.theme || localStorage.getItem('theme') || 'light'
      theme.global.name.value = savedTheme

      // Update favicon
      if (hasFavicon.value) {
        updateFavicon(faviconUrl.value)
      }

      isLoaded.value = true
    } catch (error) {
      console.error('Failed to load branding:', error)
      isLoaded.value = true
    }
  }

  const toggleTheme = async () => {
    const newTheme = theme.global.name.value === 'light' ? 'dark' : 'light'
    theme.global.name.value = newTheme
    localStorage.setItem('theme', newTheme)

    // Optionally save to backend (don't await, fire and forget)
    brandingApi.updateConfig({ theme: newTheme }).catch(() => {})
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

  const isDark = () => theme.global.name.value === 'dark'

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
