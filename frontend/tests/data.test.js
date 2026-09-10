import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyMessage } from '../src/services/meterMessages.js'
import { cachedAdapter, clearApiCache } from '../src/services/cache.js'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { TEMP_SENSOR, canonicalizeGroups } = require('../../provisioning/device-maps.js')
test('AIOX channels emit their own fault register without temperature scaling', () => {
  for (const slot of [0, 1]) {
    const tags = canonicalizeGroups(TEMP_SENSOR.registerGroupsFor(slot), `auxT${slot + 1}_C`)[0].timeseries
    assert.equal(tags[0].divider, 10)
    assert.equal(tags[1].address, slot + 6)
    assert.equal(tags[1].tag, `auxT${slot + 1}_error`)
    assert.equal(tags[1].divider, undefined)
  }
})
test('partial measurement updates preserve units and unchanged numbers', () => {
  const before = { devices: [{ name: 'PF1', label: 'Flow', readings: [{ tag: 'flow', value: 0, unit: 'm³/h', last_seen: 'old' }, { tag: 'temperature', value: 30 }] }] }
  const after = applyMessage(before, { type: 'delta', devices: [{ name: 'PF1', readings: [{ tag: 'flow', last_seen: 'new' }] }] })
  assert.deepEqual(after.devices[0].readings[0], { tag: 'flow', value: 0, unit: 'm³/h', last_seen: 'new' })
  assert.equal(after.devices[0].label, 'Flow')
  assert.equal(before.devices[0].readings[0].last_seen, 'old')
})
test('device removal, tag removal and reconnect snapshot replace correctly', () => {
  const before = { devices: [{ name: 'PF1', readings: [{ tag: 'a', value: 1 }] }, { name: 'PF2', readings: [] }] }
  const after = applyMessage(before, { type: 'delta', removed: ['PF2'], devices: [{ name: 'PF1', removed_readings: ['a'] }] })
  assert.equal(after.devices.length, 1); assert.deepEqual(after.devices[0].readings, [])
  assert.deepEqual(applyMessage(after, { type: 'snapshot', devices: [] }).devices, [])
})
test('navigation reuses configuration and writes invalidate it', async () => {
  clearApiCache()
  let calls = 0
  const adapter = cachedAdapter(async config => ({ data: ++calls, status: 200, config }))
  const config = { url: '/api/modem/config', method: 'get' }
  const [a, b] = await Promise.all([adapter(config), adapter(config)])
  assert.equal(calls, 1); assert.equal(a.data, b.data)
  await adapter({ ...config, method: 'put' }); await adapter(config)
  assert.equal(calls, 3)
})
test('live telemetry and failures are never cached as success', async () => {
  clearApiCache(); let calls = 0
  const adapter = cachedAdapter(async config => ({ data: ++calls, status: 503, config }))
  await adapter({ url: '/api/modem/config' }); await adapter({ url: '/api/modem/config' })
  await adapter({ url: '/api/meters/latest' }); await adapter({ url: '/api/meters/latest' })
  assert.equal(calls, 4)
})
test('unsaved form edits never mutate cached server configuration', async () => {
  clearApiCache()
  const adapter = cachedAdapter(async () => ({ data: { nested: { enabled: false } }, status: 200 }))
  const config = { url: '/api/modem/config' }
  const response = await adapter(config)
  response.data.nested.enabled = true
  assert.equal((await adapter(config)).data.nested.enabled, false)
})
