<template>
  <article class="panel meter-card" :class="[device.displayLink, { 'temperature-card': device.role === 'temperature' }]">
    <header class="meter-heading"><div class="meter-identity">
      <h3 v-if="isPflow" class="pflow-title" :aria-label="device.label"><img class="pflow-logo" :src="pflowLogo" alt="" aria-hidden="true" /><span class="pflow-number">{{ pflowNumber }}</span></h3>
      <h3 v-else-if="device.role === 'temperature'" class="sensor-title" :aria-label="device.label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M9 14V5a3 3 0 0 1 6 0v9a5 5 0 1 1-6 0Z M12 7v10"/><circle cx="12" cy="18" r="1.5" fill="currentColor"/></svg>{{ pflowNumber }}</h3><h3 v-else>{{ device.label }}</h3>
    </div><span class="state-badge" :class="device.displayLink"><i></i>{{ linkLabel }}</span></header>
    <div v-if="readings.length" class="primary-readings">
      <div v-for="group in groups" :key="group[0].tag" :class="{ 'paired-temperatures': group.length > 1, 'reading-stale': group.every(stale) }" :data-tone="tone(group[0].tag)">
        <div class="reading-values"><div v-for="r in group" :key="r.tag" :data-tone="tone(r.tag)" :class="{ 'reading-stale': stale(r), 'flow-reading': r.tag === 'Vdot_m3h' }"><span v-if="device.role !== 'temperature'" class="reading-label">{{ group.length > 1 ? (r.tag === 'T_flow_C' ? 'Flow' : 'Return') : label(r.tag) }}</span><div class="reading-number" :title="`${format(r.value)} ${r.unit || ''}`">{{ format(r.value) }} <small>{{ r.unit }}</small></div><small v-if="stale(r)" class="error-text">Last known</small></div></div>
        <ReadingTrend :points="history[historyKey(device, group[0].tag)] || []" :series="group.length > 1 ? group.map(r => ({ points: history[historyKey(device, r.tag)] || [], tone: tone(r.tag), stale: stale(r) })) : undefined" :unit="group[0].unit" :gap="device.stale_after" />
      </div>
    </div>
    <div v-else class="meter-empty"><span>Awaiting measurements</span><small>{{ device.displayLink === 'disconnected' ? 'No answer on the latest bus poll.' : 'Values will appear after a successful local read.' }}</small></div>


  </article>
</template>
<script setup>
import { computed } from 'vue'
import pflowLogo from '../assets/pflow.svg'
import ReadingTrend from './ReadingTrend.vue'
import { historyKey } from '../services/telemetryHistory'
const props = defineProps({ device: Object, now: Number, history: { type: Object, default: () => ({}) } })
const isPflow = computed(() => /^p[- ]?flow\s*\d+$/i.test(props.device.label || ''))
const pflowNumber = computed(() => (props.device.label || '').match(/(\d+)$/)?.[1] || (props.device.name || '').match(/pf(\d+)$/i)?.[1] || '')
const labels = { Vdot_m3h: 'Volume flow', T_flow_C: 'Flow temperature', T_return_C: 'Return temperature', v_ms: 'Velocity', V_m3: 'Volume total', E_th_heating_kWh: 'Heating energy', E_th_cooling_kWh: 'Cooling energy' }
const label = tag => /^auxT\d+_C$/.test(tag) ? 'Temperature' : labels[tag] || tag.replace(/_(m3h|m3|ms|kWh|C)$/i, '').replace(/_/g, ' ')
const tone = tag => tag === 'Vdot_m3h' || tag === 'v_ms' ? 'flow' : tag === 'T_return_C' ? 'return' : tag === 'T_flow_C' || /^auxT\d+_C$/.test(tag) ? 'temperature' : tag === 'V_m3' ? 'volume' : 'energy'
const format = value => typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : '—'
const linkLabel = computed(() => props.device.sensor_state === 'fault' && props.device.displayLink === 'disconnected' ? 'Sensor fault' : ({ connected: 'Connected', disconnected: 'No response', pending: 'Unknown' })[props.device.displayLink] || 'Unknown')
const readings = computed(() => (props.device.readings || []).filter(r => !r.tag.endsWith('_error')))
const groups = computed(() => {
  const temperatures = readings.value.filter(r => ['T_flow_C', 'T_return_C'].includes(r.tag))
  return readings.value.flatMap(r => temperatures.includes(r) ? (r === temperatures[0] ? [temperatures] : []) : [[r]])
})

const stale = r => props.device.displayLink !== 'connected' || r.stale || (r.last_seen && props.now - Date.parse(r.last_seen) > props.device.stale_after * 1000)
</script>
