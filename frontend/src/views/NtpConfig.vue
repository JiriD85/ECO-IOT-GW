<template>
  <v-row>
      <!-- NTP Status Card -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>
            Synchronization Status
            <v-spacer></v-spacer>
            <v-chip :color="status?.synchronized ? 'success' : 'warning'" size="small">
              {{ status?.synchronized ? 'Synchronized' : 'Not Synchronized' }}
            </v-chip>
          </v-card-title>
          <v-card-text>
            <v-list density="compact">
              <v-list-item>
                <v-list-item-title>Reference</v-list-item-title>
                <template v-slot:append>{{ status?.reference_id || '--' }}</template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Stratum</v-list-item-title>
                <template v-slot:append>{{ status?.stratum || '--' }}</template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Last Offset</v-list-item-title>
                <template v-slot:append>{{ formatOffset(status?.last_offset) }}</template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>RMS Offset (Jitter)</v-list-item-title>
                <template v-slot:append>{{ formatOffset(status?.rms_offset) }}</template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Last Sync</v-list-item-title>
                <template v-slot:append>{{ formatDate(status?.ref_time) }}</template>
              </v-list-item>
            </v-list>
          </v-card-text>
          <v-card-actions>
            <v-btn color="primary" variant="text" @click="refreshStatus" :loading="statusLoading">
              <v-icon left>mdi-refresh</v-icon>
              Refresh
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Timezone Card -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Timezone</v-card-title>
          <v-card-text>
            <v-autocomplete
              v-model="selectedTimezone"
              :items="timezones"
              label="System Timezone"
              :loading="timezoneLoading"
              @update:model-value="setTimezone"
            ></v-autocomplete>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- NTP Sources -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>NTP Sources</v-card-title>
          <v-card-text>
            <v-table density="compact">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Name</th>
                  <th>Stratum</th>
                  <th>Poll</th>
                  <th>Reach</th>
                  <th>Last RX</th>
                  <th>Offset</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="source in sources" :key="source.name">
                  <td>
                    <v-icon :color="getSourceColor(source.state)" size="small">
                      {{ getSourceIcon(source.state) }}
                    </v-icon>
                    {{ source.state }}
                  </td>
                  <td>{{ source.name }}</td>
                  <td>{{ source.stratum }}</td>
                  <td>{{ source.poll }}s</td>
                  <td>{{ source.reach }}</td>
                  <td>{{ source.last_rx || '--' }}</td>
                  <td>{{ source.last_sample || '--' }}</td>
                </tr>
              </tbody>
            </v-table>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- NTP Servers Configuration -->
    <v-row class="mt-4">
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>NTP Servers</v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item v-for="(server, index) in config.servers" :key="'server-' + index">
                <v-text-field
                  v-model="config.servers[index]"
                  density="compact"
                  hide-details
                  placeholder="ntp.example.com"
                ></v-text-field>
                <template v-slot:append>
                  <v-btn icon="mdi-delete" variant="text" color="error" @click="removeServer(index)"></v-btn>
                </template>
              </v-list-item>
            </v-list>
            <v-btn color="primary" variant="text" @click="addServer" class="mt-2">
              <v-icon left>mdi-plus</v-icon>
              Add Server
            </v-btn>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>NTP Pools</v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item v-for="(pool, index) in config.pools" :key="'pool-' + index">
                <v-text-field
                  v-model="config.pools[index]"
                  density="compact"
                  hide-details
                  placeholder="pool.ntp.org"
                ></v-text-field>
                <template v-slot:append>
                  <v-btn icon="mdi-delete" variant="text" color="error" @click="removePool(index)"></v-btn>
                </template>
              </v-list-item>
            </v-list>
            <v-btn color="primary" variant="text" @click="addPool" class="mt-2">
              <v-icon left>mdi-plus</v-icon>
              Add Pool
            </v-btn>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Save Button -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-btn
          color="primary"
          size="large"
          @click="saveConfig"
          :loading="saving"
          :disabled="!hasChanges"
        >
          <v-icon left>mdi-content-save</v-icon>
          Save Configuration
        </v-btn>
      </v-col>
    </v-row>
</template>

<script setup>
import { ref, reactive, computed, inject, onMounted } from 'vue'
import { ntpApi } from '../services/api'

const showSnackbar = inject('showSnackbar')

// State
const status = ref(null)
const sources = ref([])
const timezones = ref([])
const selectedTimezone = ref('')
const config = reactive({
  servers: [],
  pools: []
})
const originalConfig = ref(null)

// Loading states
const statusLoading = ref(false)
const timezoneLoading = ref(false)
const saving = ref(false)

// Computed
const hasChanges = computed(() => {
  if (!originalConfig.value) return false
  return JSON.stringify(config) !== JSON.stringify(originalConfig.value)
})

// Methods
const formatOffset = (offset) => {
  if (offset === null || offset === undefined) return '--'
  if (Math.abs(offset) < 0.001) return `${(offset * 1000000).toFixed(1)} us`
  if (Math.abs(offset) < 1) return `${(offset * 1000).toFixed(2)} ms`
  return `${offset.toFixed(3)} s`
}

const formatDate = (dateStr) => {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleString()
}

const getSourceColor = (state) => {
  if (state === '*') return 'success'
  if (state === '+') return 'info'
  if (state === '-') return 'warning'
  return 'error'
}

const getSourceIcon = (state) => {
  if (state === '*') return 'mdi-check-circle'
  if (state === '+') return 'mdi-plus-circle'
  if (state === '-') return 'mdi-minus-circle'
  return 'mdi-alert-circle'
}

const refreshStatus = async () => {
  statusLoading.value = true
  try {
    const [statusRes, sourcesRes] = await Promise.all([
      ntpApi.getStatus(),
      ntpApi.getSources()
    ])
    status.value = statusRes.data
    sources.value = sourcesRes.data
  } catch (error) {
    showSnackbar('Failed to refresh NTP status', 'error')
  } finally {
    statusLoading.value = false
  }
}

const loadConfig = async () => {
  try {
    const res = await ntpApi.getConfig()
    config.servers = res.data.servers || []
    config.pools = res.data.pools || []
    originalConfig.value = JSON.parse(JSON.stringify(config))
  } catch (error) {
    showSnackbar('Failed to load NTP config', 'error')
  }
}

const loadTimezones = async () => {
  timezoneLoading.value = true
  try {
    const [tzRes, currentRes] = await Promise.all([
      ntpApi.getTimezones(),
      ntpApi.getTimezone()
    ])
    timezones.value = tzRes.data.available || []
    selectedTimezone.value = currentRes.data.timezone || tzRes.data.current
  } catch (error) {
    showSnackbar('Failed to load timezones', 'error')
  } finally {
    timezoneLoading.value = false
  }
}

const setTimezone = async (tz) => {
  if (!tz) return
  try {
    await ntpApi.setTimezone(tz)
    showSnackbar(`Timezone set to ${tz}`)
  } catch (error) {
    showSnackbar('Failed to set timezone', 'error')
  }
}

const addServer = () => {
  config.servers.push('')
}

const removeServer = (index) => {
  config.servers.splice(index, 1)
}

const addPool = () => {
  config.pools.push('')
}

const removePool = (index) => {
  config.pools.splice(index, 1)
}

const saveConfig = async () => {
  // Filter empty entries
  const servers = config.servers.filter(s => s.trim())
  const pools = config.pools.filter(p => p.trim())

  if (servers.length === 0 && pools.length === 0) {
    showSnackbar('At least one NTP server or pool is required', 'warning')
    return
  }

  saving.value = true
  try {
    await ntpApi.setConfig({ servers, pools })
    showSnackbar('NTP configuration saved')
    originalConfig.value = JSON.parse(JSON.stringify(config))
    // Refresh status after config change
    await refreshStatus()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to save config', 'error')
  } finally {
    saving.value = false
  }
}

// Lifecycle
onMounted(async () => {
  await Promise.all([
    refreshStatus(),
    loadConfig(),
    loadTimezones()
  ])
})
</script>
