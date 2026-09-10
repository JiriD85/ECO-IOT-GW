<template>
  <div class="overview">
    <header class="page-heading"><div><h1>Dashboard</h1></div><div class="page-actions"><span v-if="lastFetch" class="live-age" title="Time since the last telemetry update received by this browser">{{ receivedAge }}</span><button class="live-button" :class="{ active: streaming }" @click="handleLive" :aria-pressed="live"><i></i>{{ !live ? 'Paused' : streaming ? 'Live' : loading && !error ? 'Connecting…' : 'Disconnected, click to reconnect' }}</button></div></header>
    <div v-if="error" class="notice warning" role="alert">{{ error }} Connection states are unverified.</div>
    <div v-else-if="snapshot?.notice" class="notice warning" role="status">{{ snapshot.notice }}</div>
    <div v-if="!live" class="notice">Live updates are paused. Displayed readings are the last received values.</div>
    <section class="devices-section">
      <div v-if="!snapshot && loading" class="panel empty-state" role="status"><h3>Reading your gateway…</h3><p>Waiting for the local device inventory.</p></div>
      <div v-else-if="!devices.length" class="panel empty-state"><h3>{{ error ? 'Device inventory unavailable' : 'No configured devices found' }}</h3><p>{{ error ? 'Reconnect to the gateway and refresh.' : 'Check the active Modbus connector configuration.' }}</p><RouterLink to="/connector">Open connector details →</RouterLink></div>
      <div v-else class="meter-grid"><MeterCard v-for="device in meters" :key="device.name" :device="device" :now="now" :history="history" /><section v-if="temperatures.length" class="panel temperature-pair" aria-label="Temperature sensors"><MeterCard v-for="device in temperatures" :key="device.name" :device="device" :now="now" :history="history" /><ReadingTrend class="sensor-pair-trend" :series="temperatureSeries" unit="°C" :gap="Math.max(...temperatures.map(d => d.stale_after))" /></section></div>
    </section>

  </div>
</template>
<script setup>
import { computed, shallowRef, watch, onUnmounted } from 'vue'
import MeterCard from '../components/MeterCard.vue'
import ReadingTrend from '../components/ReadingTrend.vue'
import { useLiveMeters } from '../composables/useLiveMeters'
import { recordHistory, restoreHistory, saveHistory, historyKey } from '../services/telemetryHistory'
const { snapshot, devices, loading, error, live, streaming, now, refresh, toggle, lastFetch } = useLiveMeters()
const receivedAge = computed(() => { const seconds = Math.max(0, Math.floor((now.value - lastFetch.value) / 1000)); return seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ${seconds % 60}s ago` })
function handleLive() { if (live.value && !streaming.value) refresh(); else toggle() }
const meters = computed(() => devices.value.filter(d => d.role !== 'temperature'))
const temperatures = computed(() => devices.value.filter(d => d.role === 'temperature'))
const history = shallowRef(restoreHistory())
const temperatureSeries = computed(() => temperatures.value.map((d, i) => { const r = d.readings.find(r => !r.tag.endsWith('_error')); return { label: d.label, tone: i ? 'return' : 'temperature', stale: d.displayLink !== 'connected' || r?.stale, points: r ? history.value[historyKey(d, r.tag)] || [] : [] } }))
watch(devices, value => { if (snapshot.value) history.value = recordHistory(history.value, value) })
const persist = () => saveHistory(history.value)
window.addEventListener('pagehide', persist)
onUnmounted(() => { persist(); window.removeEventListener('pagehide', persist) })
</script>
