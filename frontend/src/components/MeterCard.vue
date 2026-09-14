<template>
  <article class="panel meter-card" :class="[device.displayLink, { 'temperature-card': device.role === 'temperature' }]">
    <header class="meter-heading"><div class="meter-identity">
      <h3 v-if="isPflow" class="pflow-title" :aria-label="`PFlow ${pflowNumber}`"><img class="pflow-logo" :src="pflowLogo" alt="" aria-hidden="true" /><span class="pflow-number">{{ pflowNumber }}</span></h3>
      <h3 v-else-if="device.role === 'temperature'" class="sensor-title" :aria-label="device.label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M9 14V5a3 3 0 0 1 6 0v9a5 5 0 1 1-6 0Z M12 7v10"/><circle cx="12" cy="18" r="1.5" fill="currentColor"/></svg>{{ pflowNumber }}</h3><h3 v-else>{{ device.label }}</h3>
      <span v-if="device.address != null" class="modbus-address" :title="`Modbus address ${device.address}`" :aria-label="`Modbus address ${device.address}`">Addr {{ device.address }}</span>
    </div><span class="state-badge" :class="device.displayLink"><i></i>{{ linkLabel }}</span></header>
    <div v-if="readings.length" class="primary-readings">
      <div v-for="group in groups" :key="group[0].tag" :class="{ 'paired-temperatures': group.length > 1, 'has-trend': showTrend(group), 'reading-stale': group.every(stale), 'compact-reading': !showTrend(group) }" :data-tone="tone(group[0].tag)">
        <div class="reading-values"><div v-for="r in group" :key="r.tag" :data-tone="tone(r.tag)" :class="{ 'reading-stale': stale(r), 'flow-reading': r.tag === 'Vdot_m3h' }"><span v-if="device.role !== 'temperature'" class="reading-label"><svg class="reading-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path :d="icon(r.tag)"/></svg>{{ group.length > 1 ? (r.tag === 'T_flow_C' ? 'Flow' : 'Return') : label(r.tag) }}</span><div class="reading-number" :title="`${format(r.value)} ${r.unit || ''}`">{{ format(r.value) }} <small>{{ r.unit }}</small></div><small v-if="stale(r)" class="error-text">Last known</small></div></div>
        <ReadingTrend v-if="showTrend(group)" :points="history[historyKey(device, group[0].tag)] || []" :series="group.length > 1 ? group.map(r => ({ points: history[historyKey(device, r.tag)] || [], tone: tone(r.tag), stale: stale(r) })) : undefined" :unit="group[0].unit" :gap="device.stale_after" />
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
import { pflowSlot, displayReadings } from '../services/meterDisplay'
const props = defineProps({ device: Object, now: Number, history: { type: Object, default: () => ({}) } })
const isPflow = computed(() => Boolean(pflowSlot(props.device)))
const pflowNumber = computed(() => pflowSlot(props.device) || (props.device.label || '').match(/(\d+)$/)?.[1] || '')
const labels = { Vdot_m3h: 'Volume flow', T_flow_C: 'Flow temperature', T_return_C: 'Return temperature', v_ms: 'Velocity', V_m3: 'Volume total', E_th_heating_kWh: 'Heating energy', E_th_cooling_kWh: 'Cooling energy' }
const label = tag => /^auxT\d+_C$/.test(tag) ? 'Temperature' : labels[tag] || tag.replace(/_(m3h|m3|ms|kWh|C)$/i, '').replace(/_/g, ' ')
const tones = { Vdot_m3h: 'flow', v_ms: 'velocity', T_flow_C: 'temperature', T_return_C: 'return', V_m3: 'volume', V_neg_m3: 'negative', V_net_m3: 'net', E_th_heating_kWh: 'heating', E_th_cooling_kWh: 'cooling', E_th_heating_exp: 'heating-exp', E_th_cooling_exp: 'cooling-exp' }
const tone = tag => tones[tag] || (/^auxT\d+_C$/.test(tag) ? 'temperature' : 'energy')
const isCounter = tag => ['V_m3', 'V_neg_m3', 'V_net_m3', 'E_th_heating_kWh', 'E_th_cooling_kWh'].includes(tag)
const icon = tag => isCounter(tag) ? 'M3 6h18v12H3z M9 6v12m6-12v12 M6 10v4m6-4v4m6-4v4' : ['T_flow_C', 'T_return_C'].includes(tag) ? 'M9 14V5a3 3 0 0 1 6 0v9a5 5 0 1 1-6 0Z M12 7v11' : 'M3 12h4l3-7 4 14 3-7h4'
const format = value => typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : '—'
const linkLabel = computed(() => props.device.sensor_state === 'fault' && props.device.displayLink === 'disconnected' ? 'Sensor fault' : ({ connected: 'Connected', disconnected: 'No response', pending: 'Unknown' })[props.device.displayLink] || 'Unknown')
const readings = computed(() => displayReadings(props.device))
const trendTags = ['Vdot_m3h', 'T_flow_C', 'T_return_C']
const showTrend = group => group.some(r => trendTags.includes(r.tag))
const order = group => ['Vdot_m3h', 'T_flow_C', 'T_return_C', 'V_m3', 'v_ms', 'V_neg_m3', 'V_net_m3', 'E_th_heating_kWh', 'E_th_heating_exp', 'E_th_cooling_kWh', 'E_th_cooling_exp'].indexOf(group[0].tag)
const groups = computed(() => {
  const temperatures = readings.value.filter(r => ['T_flow_C', 'T_return_C'].includes(r.tag))
  return readings.value.flatMap(r => temperatures.includes(r) ? (r === temperatures[0] ? [temperatures] : []) : [[r]])
    .sort((a, b) => Number(showTrend(b)) - Number(showTrend(a)) || order(a) - order(b))
})

const stale = r => props.device.displayLink !== 'connected' || r.stale || (r.last_seen && props.now - Date.parse(r.last_seen) > props.device.stale_after * 1000)
</script>
