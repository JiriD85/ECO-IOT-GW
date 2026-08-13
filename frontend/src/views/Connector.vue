<template>
  <v-container fluid>
    <div class="d-flex align-center flex-wrap mb-4" style="gap:12px">
      <div>
        <h1 class="text-h4">Connector</h1>
        <div class="text-caption text-medium-emphasis">
          Read-only health of the Modbus connector. Editing is done in ThingsBoard.
        </div>
      </div>
      <v-spacer></v-spacer>
      <v-btn variant="tonal" :loading="loading" prepend-icon="mdi-refresh" @click="fetchData">Refresh</v-btn>
    </div>

    <v-alert
      v-if="error"
      type="warning"
      variant="tonal"
      density="compact"
      class="mb-4"
    >{{ error }}</v-alert>

    <!-- Connector summary -->
    <v-card class="mb-4">
      <v-card-text>
        <div class="summary-grid">
          <div class="cell">
            <div class="lbl">Connector</div>
            <div class="val">{{ connector.name || '—' }}</div>
            <div class="text-caption text-medium-emphasis">{{ connector.type || 'Modbus RTU' }}</div>
          </div>
          <div class="cell">
            <div class="lbl">Gateway</div>
            <v-chip :color="connector.running ? 'success' : 'error'" size="small" variant="tonal">
              <v-icon start size="x-small">{{ connector.running ? 'mdi-play' : 'mdi-stop' }}</v-icon>
              {{ connector.running ? 'Running' : 'Stopped' }}
            </v-chip>
            <div class="text-caption text-medium-emphasis mono">{{ connector.container || 'tb-gateway' }}</div>
          </div>
          <div class="cell">
            <div class="lbl">ThingsBoard</div>
            <v-chip :color="connector.thingsboard_linked ? 'success' : 'error'" size="small" variant="tonal">
              <v-icon start size="x-small">{{ connector.thingsboard_linked ? 'mdi-cloud-check' : 'mdi-cloud-off-outline' }}</v-icon>
              {{ connector.thingsboard_linked ? 'Linked' : 'Offline' }}
            </v-chip>
          </div>
          <div class="cell">
            <div class="lbl">Serial bus</div>
            <div class="val mono">{{ connector.serial_port || '—' }}</div>
            <div class="text-caption text-medium-emphasis" v-if="connector.baudrate">{{ connector.baudrate }} 8N1</div>
          </div>
          <div class="cell">
            <div class="lbl">Reporting</div>
            <div class="val">{{ reportingText }}</div>
          </div>
        </div>
      </v-card-text>
    </v-card>

    <!-- Slaves -->
    <v-card>
      <v-card-title>Configured devices</v-card-title>
      <v-card-text>
        <div class="table-scroll">
          <v-table density="comfortable">
            <thead>
              <tr>
                <th class="text-left">Device</th>
                <th class="text-left">Addr</th>
                <th class="text-left">Model</th>
                <th class="text-left">Last seen</th>
                <th class="text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in devices" :key="d.key || d.name" :class="{ off: d.status === 'no_meter' }">
                <td>
                  <div class="dev-name">{{ d.label || d.key }}</div>
                  <div class="text-caption text-medium-emphasis mono">{{ d.name }}</div>
                </td>
                <td class="mono">{{ d.address ?? '—' }}</td>
                <td class="text-medium-emphasis">{{ d.model || '—' }}</td>
                <td class="text-medium-emphasis">{{ ageText(d) }}</td>
                <td>
                  <v-chip :color="statusColor(d.status)" size="small" variant="tonal">
                    <v-icon start size="x-small">{{ statusIcon(d.status) }}</v-icon>
                    {{ statusLabel(d.status) }}
                  </v-chip>
                </td>
              </tr>
              <tr v-if="!devices.length">
                <td colspan="5" class="text-center text-medium-emphasis py-6">
                  No devices reporting. Check wiring and the connector config in ThingsBoard.
                </td>
              </tr>
            </tbody>
          </v-table>
        </div>
      </v-card-text>
    </v-card>

    <div class="text-caption text-medium-emphasis mt-3">
      To change which meters are polled, edit the connector in ThingsBoard — the gateway pulls the
      new config down automatically. This page only reflects what the gateway is currently doing.
    </div>
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { metersApi } from '../services/api'
import { useSnackbar } from '../composables/useSnackbar'

const { showSnackbar } = useSnackbar()

const connector = ref({})
const devices = ref([])
const loading = ref(false)
const error = ref('')
const now = ref(Date.now())
let clock = null

const reportingText = computed(() => {
  const active = devices.value.filter(d => d.configured !== false && d.status !== 'no_meter')
  const ok = active.filter(d => d.status === 'ok').length
  return `${ok} / ${active.length}`
})

const statusColor = (s) => ({ ok: 'success', stale: 'warning', error: 'error', no_meter: 'grey' }[s] || 'grey')
const statusIcon = (s) => ({ ok: 'mdi-check-circle', stale: 'mdi-clock-alert', error: 'mdi-alert-circle', no_meter: 'mdi-minus-circle-outline' }[s] || 'mdi-help-circle')
const statusLabel = (s) => ({ ok: 'OK', stale: 'Stale', error: 'Error', no_meter: 'No report' }[s] || s)

const secondsAgo = (iso) => (iso ? Math.max(0, Math.round((now.value - new Date(iso).getTime()) / 1000)) : null)
const humanAge = (secs) => {
  if (secs === null) return '—'
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}
const ageText = (d) => (d.status === 'no_meter' ? '—' : humanAge(secondsAgo(d.last_seen)))

const fetchData = async () => {
  try {
    loading.value = true
    error.value = ''
    const res = await metersApi.getLatest()
    connector.value = res.data.connector || {}
    devices.value = res.data.devices || []
    now.value = Date.now()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Could not read connector status from the gateway.'
    if (!devices.value.length) showSnackbar(error.value, 'error')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchData()
  clock = setInterval(() => { now.value = Date.now() }, 1000)
})
onUnmounted(() => { if (clock) clearInterval(clock) })
</script>

<style scoped>
.mono { font-family: ui-monospace, "Cascadia Code", "SF Mono", Menlo, Consolas, monospace; }
.dev-name { font-weight: 600; }
.table-scroll { overflow-x: auto; }
.off { opacity: .55; }

.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; }
.cell .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; opacity: .6; margin-bottom: 4px; }
.cell .val { font-size: 18px; font-weight: 600; }
</style>
