<template>
  <v-container fluid>
    <!-- Header -->
    <div class="d-flex align-center flex-wrap mb-4" style="gap:12px">
      <div>
        <h1 class="text-h4">Meters</h1>
        <div class="text-caption text-medium-emphasis">
          Latest values reported by the gateway — decoded from the connector, no extra bus polling.
        </div>
      </div>
      <v-spacer></v-spacer>

      <v-chip v-if="summary" :color="summary.color" size="small" variant="tonal">
        <v-icon start size="small">{{ summary.icon }}</v-icon>
        {{ summary.text }}
      </v-chip>

      <v-switch
        v-model="live"
        color="success"
        density="compact"
        hide-details
        inset
        label="Live"
        class="flex-grow-0"
      ></v-switch>

      <v-btn variant="tonal" :loading="loading" prepend-icon="mdi-refresh" @click="fetchData">Refresh</v-btn>
    </div>

    <v-alert v-if="error" type="warning" variant="tonal" density="compact" class="mb-4">{{ error }}</v-alert>

    <!-- Energy / flow meters -->
    <div class="text-overline text-medium-emphasis mb-1">Meters</div>
    <v-row v-if="meters.length">
      <v-col v-for="d in meters" :key="d.name" cols="12" md="6">
        <v-card :class="{ 'dev-error': d.status === 'error' }">
          <v-card-item>
            <template #prepend>
              <v-icon :color="statusColor(d.status)">mdi-meter-electric</v-icon>
            </template>
            <v-card-title>{{ d.label }}</v-card-title>
            <v-card-subtitle>
              <span class="mono">{{ d.name }}</span> · unit {{ d.address }} · {{ d.model }}
            </v-card-subtitle>
            <template #append>
              <v-chip :color="statusColor(d.status)" size="small" variant="tonal">
                <v-icon start size="x-small">{{ statusIcon(d.status) }}</v-icon>
                {{ statusLabel(d.status) }}
              </v-chip>
            </template>
          </v-card-item>
          <v-card-text>
            <div v-if="d.readings.length" class="readings">
              <div v-for="r in d.readings" :key="r.tag" class="reading-tile">
                <div class="r-tag">{{ prettyTag(r.tag) }}</div>
                <div class="r-val mono">{{ fmt(r.value) }}<small v-if="r.unit"> {{ r.unit }}</small></div>
              </div>
            </div>
            <div v-else class="text-medium-emphasis text-body-2">
              {{ d.status === 'error' ? 'No response from this meter — check wiring / address.' : 'No values reported yet.' }}
            </div>
            <div class="text-caption text-medium-emphasis mt-2">Last seen {{ ageText(d) }}</div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
    <div v-else class="text-medium-emphasis text-body-2 mb-4">No meters configured.</div>

    <!-- Temperature sensors -->
    <div class="text-overline text-medium-emphasis mt-5 mb-1">Temperature sensors</div>
    <div v-if="temps.length" class="temp-grid">
      <v-sheet
        v-for="t in temps"
        :key="t.name"
        class="temp-tile"
        :class="{ off: t.status === 'error' || t.status === 'no_report' }"
        rounded="lg"
        border
      >
        <div class="d-flex align-center justify-space-between">
          <div class="text-subtitle-2">{{ t.label }}</div>
          <v-chip :color="statusColor(t.status)" size="x-small" variant="tonal">{{ statusLabel(t.status) }}</v-chip>
        </div>
        <div class="temp-val mono">
          {{ fmt(tempValue(t)) }}<small v-if="tempValue(t) !== null">°C</small>
        </div>
        <div class="text-caption text-medium-emphasis mono">{{ t.name }} · unit {{ t.address }}</div>
        <div class="text-caption text-medium-emphasis">{{ ageText(t) }}</div>
      </v-sheet>
    </div>
    <div v-else class="text-medium-emphasis text-body-2">No temperature sensors configured.</div>

    <div class="text-caption text-medium-emphasis mt-4">
      <template v-if="updatedAt">Updated {{ ageFromNow(updatedAt) }} · </template>
      Values decoded from the gateway connector (D116 mixed-endian; AIOX temps on unit 255, ÷10).
    </div>
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { metersApi } from '../services/api'
import { useSnackbar } from '../composables/useSnackbar'

const { showSnackbar } = useSnackbar()

const devices = ref([])
const updatedAt = ref(null)
const loading = ref(false)
const error = ref('')
const live = ref(false)
let timer = null
const now = ref(Date.now())
let clock = null

const meters = computed(() => devices.value.filter(d => d.role !== 'temperature'))
const temps = computed(() => devices.value.filter(d => d.role === 'temperature'))

const summary = computed(() => {
  if (!devices.value.length) return null
  const ok = devices.value.filter(d => d.status === 'ok').length
  const stale = devices.value.filter(d => d.status === 'stale').length
  const err = devices.value.filter(d => d.status === 'error').length
  if (err) return { color: 'error', icon: 'mdi-alert-circle', text: `${ok} ok · ${err} error` }
  if (stale) return { color: 'warning', icon: 'mdi-clock-alert', text: `${ok} ok · ${stale} stale` }
  return { color: 'success', icon: 'mdi-check-circle', text: `${ok} reporting` }
})

const fmt = (v) => {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v !== 'number') return v
  return v.toLocaleString(undefined, { maximumFractionDigits: 3 })
}
const prettyTag = (tag) => (tag || '').replace(/_(m3h|m3|ms|kWh|C|exp)$/i, '').replace(/_/g, ' ')
const tempValue = (t) => (t.readings && t.readings.length ? t.readings[0].value : null)

const statusColor = (s) => ({ ok: 'success', stale: 'warning', error: 'error', no_report: 'grey' }[s] || 'grey')
const statusIcon = (s) => ({ ok: 'mdi-check-circle', stale: 'mdi-clock-alert', error: 'mdi-alert-circle', no_report: 'mdi-minus-circle-outline' }[s] || 'mdi-help-circle')
const statusLabel = (s) => ({ ok: 'OK', stale: 'Stale', error: 'Error', no_report: 'No report' }[s] || s)

const secondsAgo = (iso) => (iso ? Math.max(0, Math.round((now.value - new Date(iso).getTime()) / 1000)) : null)
const humanAge = (secs) => {
  if (secs === null) return '—'
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}
const ageText = (d) => (['error', 'no_report'].includes(d.status) && !d.last_seen ? '—' : humanAge(secondsAgo(d.last_seen)))
const ageFromNow = (iso) => humanAge(secondsAgo(iso))

const fetchData = async () => {
  try {
    loading.value = true
    error.value = ''
    const res = await metersApi.getLatest()
    devices.value = res.data.devices || []
    updatedAt.value = res.data.updated_at || null
    now.value = Date.now()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Could not read meter values from the gateway.'
    if (!devices.value.length) showSnackbar(error.value, 'error')
  } finally {
    loading.value = false
  }
}

const applyLive = () => {
  if (timer) { clearInterval(timer); timer = null }
  if (live.value) timer = setInterval(fetchData, 5000)
}
watch(live, applyLive)

onMounted(() => {
  fetchData()
  clock = setInterval(() => { now.value = Date.now() }, 1000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (clock) clearInterval(clock)
})
</script>

<style scoped>
.mono { font-family: ui-monospace, "Cascadia Code", "SF Mono", Menlo, Consolas, monospace; }
.dev-error { border-left: 3px solid rgb(var(--v-theme-error)); }

.readings { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px; }
.reading-tile { background: rgba(128,128,128,.06); border-radius: 8px; padding: 8px 10px; }
.r-tag { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; opacity: .65; }
.r-val { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.r-val small { font-size: 12px; opacity: .6; font-weight: 400; }

.temp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
.temp-tile { padding: 14px 16px; }
.temp-tile.off { opacity: .55; }
.temp-val { font-size: 32px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.2; margin: 4px 0; }
.temp-val small { font-size: 15px; opacity: .6; margin-left: 2px; }
</style>
