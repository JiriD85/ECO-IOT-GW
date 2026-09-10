// Tab-local rolling history; never fetched from or sent to the gateway.
export const WINDOW = 30 * 60 * 1000
const KEY = 'eco-meter-history-v2'
export const historyKey = (device, tag) => JSON.stringify([device.name, device.address, tag])
export function recordHistory(previous, devices, now = Date.now()) {
  const next = {}
  for (const device of devices.slice(0, 6)) {
    for (const r of (device.readings || []).slice(0, 32)) {
      if (r.tag.endsWith('_error')) continue
      const key = historyKey(device, r.tag)
      const points = (previous[key] || []).filter(p => p[0] >= now - WINDOW && p[0] <= now)
      const t = Date.parse(r.last_seen)
      if (device.displayLink === 'connected' && !r.stale && Number.isFinite(r.value) && Number.isFinite(t) && t <= now && t >= now - WINDOW && now - t <= device.stale_after * 1000 && (!points.length || t > points.at(-1)[0])) {
        // At most one point per five seconds, preserving the latest reading.
        if (points.length && Math.floor(t / 5000) === Math.floor(points.at(-1)[0] / 5000)) points[points.length - 1] = [t, r.value]
        else points.push([t, r.value])
      }
      next[key] = points.slice(-360)
    }
  }
  return next
}
export function restoreHistory() {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw || raw.length > 3000000) return {}
    const parsed = JSON.parse(raw), clean = {}, now = Date.now()
    for (const [key, points] of Object.entries(parsed).slice(0, 192)) {
      if (!Array.isArray(points)) continue
      clean[key] = points.filter(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite) && p[0] >= now - WINDOW && p[0] <= now).slice(-360).sort((a,b) => a[0]-b[0])
    }
    return clean
  } catch { return {} }
}
export function saveHistory(history) { try { sessionStorage.setItem(KEY, JSON.stringify(history)) } catch { /* Storage may be disabled. In-memory graphs still work. */ } }
