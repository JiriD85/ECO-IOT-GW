import { reactive } from 'vue'
export const managementFailures = reactive(new Map())
export function recordRead(url, failed, page = window.location.pathname) {
  if (!url?.startsWith('/api/') || /\/api\/(auth|meters|branding)\//.test(url)) return
  const key = `${page}:${url}`
  if (failed) managementFailures.set(key, page)
  else managementFailures.delete(key)
}
