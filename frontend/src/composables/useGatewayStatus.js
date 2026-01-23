/**
 * Gateway Status Composable
 *
 * Provides reactive gateway status with exponential backoff,
 * state-specific UI configuration, and manual refresh capability.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '../services/api'

// State configuration for UI rendering
const STATE_CONFIG = {
  connected: {
    color: 'success',
    icon: 'mdi-cloud-check',
    label: 'Connected',
    description: 'Gateway is connected to ThingsBoard'
  },
  starting: {
    color: 'info',
    icon: 'mdi-cloud-sync',
    label: 'Starting...',
    description: 'Gateway is initializing connection'
  },
  disconnected: {
    color: 'warning',
    icon: 'mdi-cloud-off-outline',
    label: 'Disconnected',
    description: 'Gateway is not connected to ThingsBoard'
  },
  stopped: {
    color: 'grey',
    icon: 'mdi-stop-circle-outline',
    label: 'Stopped',
    description: 'Gateway container is not running'
  },
  error: {
    color: 'error',
    icon: 'mdi-alert-circle',
    label: 'Error',
    description: 'Gateway encountered an error'
  },
  unknown: {
    color: 'grey',
    icon: 'mdi-help-circle-outline',
    label: 'Unknown',
    description: 'Unable to determine gateway status'
  }
}

// Exponential backoff configuration
const BACKOFF_CONFIG = {
  initialInterval: 5000,    // 5 seconds
  maxInterval: 60000,       // 60 seconds max
  multiplier: 1.5,
  resetOnSuccess: true
}

export function useGatewayStatus(options = {}) {
  const {
    autoStart = true,
    pollInterval = 10000,    // Normal polling interval
    enableBackoff = true
  } = options

  // Reactive state
  const status = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const lastFetch = ref(null)

  // Backoff state
  const currentInterval = ref(pollInterval)
  const consecutiveErrors = ref(0)

  // Abort controller for cancelling requests
  let abortController = null
  let pollTimer = null

  // Computed properties for UI
  const state = computed(() => status.value?.state || 'unknown')

  const stateConfig = computed(() => STATE_CONFIG[state.value] || STATE_CONFIG.unknown)

  const stateColor = computed(() => stateConfig.value.color)

  const stateIcon = computed(() => stateConfig.value.icon)

  const stateLabel = computed(() => stateConfig.value.label)

  const stateDescription = computed(() => stateConfig.value.description)

  const containerRunning = computed(() => status.value?.container?.running ?? false)

  const containerStatus = computed(() => status.value?.container?.status || null)

  const mqttConnected = computed(() => status.value?.mqtt_connected ?? false)

  const message = computed(() => status.value?.message || null)

  const isCached = computed(() => status.value?.cached ?? false)

  const cacheAge = computed(() => status.value?.cache_age_seconds ?? null)

  const isHealthy = computed(() => state.value === 'connected')

  const needsAttention = computed(() =>
    ['error', 'disconnected'].includes(state.value) && containerRunning.value
  )

  /**
   * Fetch gateway status from API
   */
  async function fetchStatus(forceRefresh = false) {
    // Cancel any pending request
    if (abortController) {
      abortController.abort()
    }
    abortController = new AbortController()

    loading.value = true
    error.value = null

    try {
      const response = await api.get('/api/thingsboard/gateway-status', {
        params: { force_refresh: forceRefresh },
        signal: abortController.signal
      })

      status.value = response.data
      lastFetch.value = new Date()

      // Reset backoff on success
      if (enableBackoff && BACKOFF_CONFIG.resetOnSuccess) {
        consecutiveErrors.value = 0
        currentInterval.value = pollInterval
      }

      return response.data
    } catch (err) {
      if (err.name === 'AbortError' || err.name === 'CanceledError') {
        // Request was cancelled, don't treat as error
        return null
      }

      console.error('Failed to fetch gateway status:', err)
      error.value = err.response?.data?.detail || err.message || 'Failed to fetch status'

      // Apply exponential backoff on error
      if (enableBackoff) {
        consecutiveErrors.value++
        currentInterval.value = Math.min(
          BACKOFF_CONFIG.initialInterval * Math.pow(BACKOFF_CONFIG.multiplier, consecutiveErrors.value),
          BACKOFF_CONFIG.maxInterval
        )
      }

      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * Force refresh (bypass cache)
   */
  async function forceRefresh() {
    return fetchStatus(true)
  }

  /**
   * Start polling
   */
  function startPolling() {
    stopPolling()

    const poll = async () => {
      await fetchStatus()
      pollTimer = setTimeout(poll, currentInterval.value)
    }

    poll()
  }

  /**
   * Stop polling
   */
  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
    if (abortController) {
      abortController.abort()
      abortController = null
    }
  }

  /**
   * Reset backoff timer
   */
  function resetBackoff() {
    consecutiveErrors.value = 0
    currentInterval.value = pollInterval
  }

  // Lifecycle hooks
  onMounted(() => {
    if (autoStart) {
      startPolling()
    }
  })

  onUnmounted(() => {
    stopPolling()
  })

  return {
    // State
    status,
    loading,
    error,
    lastFetch,

    // Computed UI properties
    state,
    stateColor,
    stateIcon,
    stateLabel,
    stateDescription,
    containerRunning,
    containerStatus,
    mqttConnected,
    message,
    isCached,
    cacheAge,
    isHealthy,
    needsAttention,

    // Methods
    fetchStatus,
    forceRefresh,
    startPolling,
    stopPolling,
    resetBackoff,

    // Configuration
    STATE_CONFIG
  }
}

export default useGatewayStatus
