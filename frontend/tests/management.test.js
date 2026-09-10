import { test } from 'node:test'
import assert from 'node:assert/strict'
import { managementFailures, recordRead } from '../src/services/managementHealth.js'

test('management read errors stay scoped to their page and clear after recovery', () => {
  recordRead('/api/modem/status', true, '/interfaces/modem')
  assert.equal([...managementFailures.values()].includes('/system/settings'), false)
  assert.equal([...managementFailures.values()].includes('/interfaces/modem'), true)
  recordRead('/api/modem/status', false, '/interfaces/modem')
  assert.equal(managementFailures.size, 0)
})

test('container controls dispatch the intended HTTP operations', async () => {
  globalThis.window = { location: { origin: 'http://localhost' } }
  const { default: api, dockerApi } = await import('../src/services/api.js')
  const requests = []
  api.defaults.adapter = async config => {
    requests.push([config.method, config.url])
    return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
  }
  await dockerApi.startContainer('tb-gateway')
  await dockerApi.stopContainer('tb-gateway')
  await dockerApi.restartContainer('tb-gateway')
  await dockerApi.deleteCompose()
  assert.deepEqual(requests, [
    ['post', '/api/docker/container/tb-gateway/start'],
    ['post', '/api/docker/container/tb-gateway/stop'],
    ['post', '/api/docker/container/tb-gateway/restart'],
    ['delete', '/api/docker/compose'],
  ])
})
