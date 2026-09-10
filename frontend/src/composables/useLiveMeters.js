import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../services/auth'
import { applyMessage } from '../services/meterMessages'
// Memory survives route changes. No telemetry is persisted to disk/browser storage.
const snapshot = ref(null), lastFetch = ref(0)
let sessionKey
export function useLiveMeters() {
  const auth = useAuthStore()
  const key = `${auth.identity}:${auth.authMethod}`
  if (key !== sessionKey) { snapshot.value = null; lastFetch.value = 0; sessionKey = key }
  const loading = ref(true), error = ref(''), live = ref(true), streaming = ref(false), now = ref(Date.now())
  let socket, retry, watchdog, clock, active = false, failures = 0, generation = 0
  function stop() {
    streaming.value = false
    generation++; clearTimeout(retry); clearTimeout(watchdog)
    if (socket) { socket.onclose = null; socket.close(); socket = null }
  }
  function connect() {
    if (!active || !live.value || document.hidden) return
    stop()
    const mine = generation
    loading.value = !snapshot.value
    const ws = socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/meters/stream`)
    function armWatchdog() {
      clearTimeout(watchdog)
      watchdog = setTimeout(() => { error.value = 'Live connection timed out. Reconnecting…'; ws.close() }, 45000)
    }
    armWatchdog()
    ws.onopen = () => ws.send(JSON.stringify({ token: auth.accessToken || null }))
    ws.onmessage = event => {
      if (mine !== generation) return
      armWatchdog()
      const message = JSON.parse(event.data)
      if (message.type === 'heartbeat') return
      snapshot.value = applyMessage(snapshot.value, message)
      streaming.value = true
      lastFetch.value = Date.now(); loading.value = false; error.value = ''; failures = 0
    }
    ws.onclose = async event => {
      clearTimeout(watchdog)
      if (mine !== generation || !active || !live.value) return
      streaming.value = false
      loading.value = false
      error.value = 'Live connection interrupted. Last readings are retained; reconnecting…'
      if (event.code === 4401) {
        if (!auth.refreshToken || !await auth.refreshAccessToken()) {
          error.value = 'Your session expired. Sign in again to resume live data.'
          return
        }
      }
      if (mine !== generation) return
      retry = setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(failures++, 5)))
    }
  }
  function refresh() { if (live.value) connect() }
  function toggle() { live.value = !live.value; if (live.value) connect(); else { stop(); loading.value = false } }
  function visibility() { if (document.hidden) stop(); else connect() }
  onMounted(() => {
    active = true; connect()
    clock = setInterval(() => { if (!document.hidden) now.value = Date.now() }, 1000)
    document.addEventListener('visibilitychange', visibility)
  })
  onUnmounted(() => { active = false; stop(); clearInterval(clock); document.removeEventListener('visibilitychange', visibility) })
  const devices = computed(() => (snapshot.value?.devices || []).map(device => {
    const expired = device.last_poll && now.value - Date.parse(device.last_poll) > (device.stale_after || 180) * 1000
    const link = device.role === 'temperature' && device.link === 'connected' ? (device.sensor_state === 'fault' ? 'disconnected' : device.sensor_state === 'ok' ? 'connected' : 'pending') : device.link
    return { ...device, displayLink: error.value || !streaming.value || expired ? 'pending' : link }
  }))
  return { snapshot, devices, loading, error, live, streaming, now, refresh, toggle, lastFetch }
}
