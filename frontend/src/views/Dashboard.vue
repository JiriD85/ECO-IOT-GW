<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <h1 class="text-h4 mb-4">Dashboard</h1>
      </v-col>
    </v-row>

    <!-- System Status Cards -->
    <v-row>
      <v-col cols="12" md="3">
        <v-card>
          <v-card-text class="text-center">
            <v-icon size="48" :color="cpuColor">mdi-cpu-64-bit</v-icon>
            <div class="text-h4 mt-2">{{ systemStatus?.cpu_percent?.toFixed(1) ?? '—' }}%</div>
            <div class="text-caption">CPU Usage</div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="3">
        <v-card>
          <v-card-text class="text-center">
            <v-icon size="48" :color="memoryColor">mdi-memory</v-icon>
            <div class="text-h4 mt-2">{{ systemStatus?.memory_percent?.toFixed(1) ?? '—' }}%</div>
            <div class="text-caption">Memory Usage</div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="3">
        <v-card>
          <v-card-text class="text-center">
            <v-icon size="48" :color="diskColor">mdi-harddisk</v-icon>
            <div class="text-h4 mt-2">{{ systemStatus?.disk_percent?.toFixed(1) ?? '—' }}%</div>
            <div class="text-caption">Disk Usage</div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="3">
        <v-card>
          <v-card-text class="text-center">
            <v-icon size="48" :color="tempColor">mdi-thermometer</v-icon>
            <div class="text-h4 mt-2">{{ systemStatus?.temperature?.toFixed(1) || '--' }}°C</div>
            <div class="text-caption">Temperature</div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Connectivity Status -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>Connectivity Status</v-card-title>
          <v-card-text>
            <v-row>
              <v-col cols="6" md="3" class="text-center">
                <v-icon size="36" :color="connState(connectivity?.vpn).color">mdi-vpn</v-icon>
                <div class="mt-2">VPN</div>
                <v-chip :color="connState(connectivity?.vpn).color" size="small">
                  {{ connState(connectivity?.vpn).label }}
                </v-chip>
              </v-col>

              <v-col cols="6" md="3" class="text-center">
                <v-icon size="36" :color="connState(connectivity?.modem).color">mdi-antenna</v-icon>
                <div class="mt-2">Modem</div>
                <v-chip :color="connState(connectivity?.modem).color" size="small">
                  {{ connState(connectivity?.modem).label }}
                </v-chip>
              </v-col>

              <v-col cols="6" md="3" class="text-center">
                <v-icon size="36" :color="connState(connectivity?.thingsboard).color">mdi-cloud</v-icon>
                <div class="mt-2">ThingsBoard</div>
                <v-chip :color="connState(connectivity?.thingsboard).color" size="small">
                  {{ connState(connectivity?.thingsboard).label }}
                </v-chip>
              </v-col>

              <v-col cols="6" md="3" class="text-center">
                <v-icon size="36" :color="connState(connectivity?.internet).color">mdi-web</v-icon>
                <div class="mt-2">Internet</div>
                <v-chip :color="connState(connectivity?.internet).color" size="small">
                  {{ connState(connectivity?.internet).label }}
                </v-chip>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Container Status -->
    <v-row class="mt-4">
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Docker Containers</v-card-title>
          <v-card-text>
            <v-list v-if="containers.length > 0">
              <v-list-item
                v-for="container in containers"
                :key="container.id"
              >
                <template v-slot:prepend>
                  <v-icon :color="container.status === 'running' ? 'success' : 'error'">
                    mdi-docker
                  </v-icon>
                </template>
                <v-list-item-title>{{ container.name }}</v-list-item-title>
                <v-list-item-subtitle>{{ container.image }}</v-list-item-subtitle>
                <template v-slot:append>
                  <v-chip
                    :color="container.status === 'running' ? 'success' : 'error'"
                    size="small"
                  >
                    {{ container.status }}
                  </v-chip>
                </template>
              </v-list-item>
            </v-list>
            <div v-else class="text-center text-grey">
              No containers running
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <!-- System Info -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>System Information</v-card-title>
          <v-card-text>
            <v-list density="compact">
              <v-list-item>
                <v-list-item-title>Hostname</v-list-item-title>
                <template v-slot:append>
                  <span class="text-grey">{{ systemStatus?.hostname || '--' }}</span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Uptime</v-list-item-title>
                <template v-slot:append>
                  <span class="text-grey">{{ formatUptime(systemStatus?.uptime) }}</span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Load Average</v-list-item-title>
                <template v-slot:append>
                  <span class="text-grey">
                    {{ systemStatus?.load_average?.map(l => l.toFixed(2)).join(' ') || '--' }}
                  </span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Memory</v-list-item-title>
                <template v-slot:append>
                  <span class="text-grey">
                    {{ formatBytes(systemStatus?.memory_used) }} / {{ formatBytes(systemStatus?.memory_total) }}
                  </span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Disk</v-list-item-title>
                <template v-slot:append>
                  <span class="text-grey">
                    {{ formatBytes(systemStatus?.disk_used) }} / {{ formatBytes(systemStatus?.disk_total) }}
                  </span>
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { systemApi, diagnosticsApi, dockerApi } from '../services/api'

const systemStatus = ref(null)
const connectivity = ref(null)
const containers = ref([])
let refreshInterval = null

const cpuColor = computed(() => {
  const cpu = systemStatus.value?.cpu_percent || 0
  if (cpu > 80) return 'error'
  if (cpu > 60) return 'warning'
  return 'success'
})

const memoryColor = computed(() => {
  const mem = systemStatus.value?.memory_percent || 0
  if (mem > 80) return 'error'
  if (mem > 60) return 'warning'
  return 'success'
})

const diskColor = computed(() => {
  const disk = systemStatus.value?.disk_percent || 0
  if (disk > 90) return 'error'
  if (disk > 80) return 'warning'
  return 'success'
})

const tempColor = computed(() => {
  const temp = systemStatus.value?.temperature || 0
  if (temp > 80) return 'error'
  if (temp > 70) return 'warning'
  return 'success'
})

const formatUptime = (seconds) => {
  if (!seconds) return '--'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${days}d ${hours}h ${mins}m`
}

const formatBytes = (bytes) => {
  if (!bytes) return '--'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return `${bytes.toFixed(1)} ${units[i]}`
}

// Tri-state so a tile reads "Checking…" (grey) while loading instead of a
// misleading red "Disconnected" before the first response arrives.
const connState = (value) => {
  if (value === undefined || value === null) return { color: 'grey', label: 'Checking…' }
  return value
    ? { color: 'success', label: 'Connected' }
    : { color: 'error', label: 'Disconnected' }
}

// Fetch each card independently so a slow check never holds up the others
// (previously one Promise.all meant every card waited on the slowest call).
const fetchSystem = async () => {
  try { systemStatus.value = (await systemApi.getStatus()).data } catch (e) { /* keep last */ }
}
const fetchConnectivity = async () => {
  try { connectivity.value = (await diagnosticsApi.getConnectivity()).data } catch (e) { /* keep last */ }
}
const fetchDocker = async () => {
  try { containers.value = (await dockerApi.getStatus()).data.containers || [] } catch (e) { /* keep last */ }
}

const fetchData = () => {
  fetchSystem()
  fetchConnectivity()
  fetchDocker()
}

onMounted(() => {
  fetchData()
  refreshInterval = setInterval(fetchData, 5000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>
