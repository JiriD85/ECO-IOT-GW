import { test } from 'node:test'
import assert from 'node:assert/strict'
import { pflowSlot, displayReadings } from '../src/services/meterDisplay.js'
import { createRequire } from 'node:module'
const { PFLOW_D116 } = createRequire(import.meta.url)('../../provisioning/device-maps.js')

test('fleet device names show the correct compact PFlow identity', () => {
  for (let slot = 1; slot <= 4; slot++) {
    assert.equal(pflowSlot({ name: `ECO_1F0022000D57435535333920_PF${slot}` }), String(slot))
    assert.equal(pflowSlot({ label: `P-Flow ${slot}` }), String(slot))
  }
  assert.equal(pflowSlot({ name: 'ECO_serial_TS1' }), '')
})

test('legacy/canonical mixed inventory shows canonical values without converting raw units', () => {
  const mappings = PFLOW_D116.registerGroups.flatMap(g => g.timeseries)
  const readings = mappings.flatMap(m => [{ tag: m.tag, value: 1000 }, { tag: m.canonicalTag, value: 1 }])
  const shown = displayReadings({ readings })
  assert.deepEqual(shown, mappings.map(m => ({ tag: m.canonicalTag, value: 1 })))
  assert.equal(readings.length, mappings.length * 2)
})

test('manual fields and raw-only configurations remain visible', () => {
  const readings = [{ tag: 'CHC_S_VolumeFlow', value: 1000 }, { tag: 'pressure', value: 2 }, { tag: 'auxT1_error', value: 1 }]
  assert.deepEqual(displayReadings({ readings }), readings.slice(0, 2))
})
