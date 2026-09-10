// Session memory only. Writes/auth changes invalidate every entry; live telemetry
// and logs deliberately never use this cache. Shared promises deduplicate mounts.
const entries = new Map()
let generation = 0
export function clearApiCache() { entries.clear(); generation++ }
export function cachedAdapter(adapter) {
  return async config => {
    const method = (config.method || 'get').toLowerCase()
    if (method !== 'get') { clearApiCache(); return adapter(config) }
    const ttl = /\/api\/(branding\/config|.*\/config|.*\/autostart|.*\/compose|.*\/timezones|.*\/timezone|.*\/sources|.*\/ports|vpn\/type)$/.test(config.url) ? 60000
      : config.url === '/api/system/status' ? 30000 : 0
    if (!ttl || config.signal || config.params?.force_refresh) return adapter(config)
    const key = `${config.url}:${JSON.stringify(config.params || {})}`
    const previous = entries.get(key)
    const copy = r => ({ ...r, data: structuredClone(r.data), config })
    if (previous && previous.until > Date.now()) return previous.promise.then(copy)
    const epoch = generation
    const promise = adapter(config).then(response => {
      if (response.status >= 400 && generation === epoch) entries.delete(key)
      return response
    }).catch(error => { if (generation === epoch) entries.delete(key); throw error })
    entries.set(key, { promise, until: Date.now() + ttl })
    return promise.then(copy)
  }
}
