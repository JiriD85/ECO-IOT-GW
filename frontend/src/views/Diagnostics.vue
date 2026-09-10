<template>
  <v-tabs v-model="tab" class="mb-4">
      <v-tab value="connectivity">Connectivity</v-tab>
      <v-tab value="logs">Gateway Logs</v-tab>
    </v-tabs>

    <v-window v-model="tab">
      <!-- Connectivity Tab -->
      <v-window-item value="connectivity">
        <v-row>
          <v-col cols="12" md="6">
            <v-card>
              <v-card-title>Connectivity Status</v-card-title>
              <v-card-text>
                <v-list>
                  <v-list-item v-for="item in connectivityItems" :key="item.name">
                    <template v-slot:prepend>
                      <v-icon :color="item.status ? 'success' : 'error'">
                        {{ item.status ? 'mdi-check-circle' : 'mdi-close-circle' }}
                      </v-icon>
                    </template>
                    <v-list-item-title>{{ item.label }}</v-list-item-title>
                    <template v-slot:append>
                      <v-chip
                        :color="item.status ? 'success' : 'error'"
                        size="small"
                      >
                        {{ item.status ? 'OK' : 'FAIL' }}
                      </v-chip>
                    </template>
                  </v-list-item>
                </v-list>

                <div class="text-caption mt-4">
                  Last check: {{ connectivity?.last_check ? new Date(connectivity.last_check).toLocaleString() : '--' }}
                </div>
              </v-card-text>
              <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="primary" @click="fetchConnectivity" :loading="loading">
                  Refresh
                </v-btn>
              </v-card-actions>
            </v-card>
          </v-col>

          <v-col cols="12" md="6">
            <v-card>
              <v-card-title>Gateway Container</v-card-title>
              <v-card-text>
                <v-list>
                  <v-list-item>
                    <template v-slot:prepend>
                      <v-icon :color="gatewayStatus?.running ? 'success' : 'error'">
                        mdi-docker
                      </v-icon>
                    </template>
                    <v-list-item-title>Status</v-list-item-title>
                    <template v-slot:append>
                      <v-chip
                        :color="gatewayStatus?.running ? 'success' : 'error'"
                        size="small"
                      >
                        {{ gatewayStatus?.running ? 'Running' : 'Stopped' }}
                      </v-chip>
                    </template>
                  </v-list-item>
                  <v-list-item v-if="gatewayStatus?.container_name">
                    <v-list-item-title>Container</v-list-item-title>
                    <template v-slot:append>
                      {{ gatewayStatus.container_name }}
                    </template>
                  </v-list-item>
                </v-list>
              </v-card-text>
            </v-card>
          </v-col>
        </v-row>
      </v-window-item>

      <!-- Gateway Logs Tab -->
      <v-window-item value="logs">
        <v-card>
          <v-card-title>
            ThingsBoard Gateway Logs
            <v-spacer></v-spacer>
            <v-select
              v-model="logLevel"
              :items="['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR']"
              label="Level"
              density="compact"
              style="max-width: 150px"
              hide-details
            ></v-select>
          </v-card-title>
          <v-card-text>
            <v-virtual-scroll
              :items="gatewayLogs"
              height="400"
              item-height="48"
            >
              <template v-slot:default="{ item }">
                <v-list-item density="compact">
                  <template v-slot:prepend>
                    <v-chip
                      :color="getLogColor(item.level)"
                      size="x-small"
                      class="mr-2"
                    >
                      {{ item.level }}
                    </v-chip>
                  </template>
                  <v-list-item-title class="text-body-2">
                    {{ item.message }}
                  </v-list-item-title>
                  <v-list-item-subtitle>
                    {{ new Date(item.timestamp).toLocaleString() }}
                    <span v-if="item.connector" class="ml-2">[{{ item.connector }}]</span>
                  </v-list-item-subtitle>
                </v-list-item>
              </template>
            </v-virtual-scroll>
          </v-card-text>
          <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn color="primary" @click="fetchGatewayLogs" :loading="loading">
              Refresh
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-window-item>
    </v-window>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { diagnosticsApi } from '../services/api'

const tab = ref('connectivity')
const loading = ref(false)
const connectivity = ref(null)
const gatewayStatus = ref(null)
const gatewayLogs = ref([])
const logLevel = ref('ALL')

const connectivityItems = computed(() => [
  { name: 'vpn', label: 'VPN Connection', status: connectivity.value?.vpn },
  { name: 'modem', label: 'Modem Connection', status: connectivity.value?.modem },
  { name: 'thingsboard', label: 'ThingsBoard', status: connectivity.value?.thingsboard },
  { name: 'internet', label: 'Internet', status: connectivity.value?.internet }
])

const getLogColor = (level) => {
  const colors = {
    DEBUG: 'grey',
    INFO: 'info',
    WARNING: 'warning',
    ERROR: 'error'
  }
  return colors[level] || 'grey'
}

const fetchConnectivity = async () => {
  try {
    loading.value = true
    const [connRes, gwRes] = await Promise.all([
      diagnosticsApi.getConnectivity(),
      diagnosticsApi.getGatewayStatus()
    ])
    connectivity.value = connRes.data
    gatewayStatus.value = gwRes.data
  } catch (error) {
    console.error('Failed to fetch connectivity:', error)
  } finally {
    loading.value = false
  }
}

const fetchGatewayLogs = async () => {
  try {
    loading.value = true
    const level = logLevel.value === 'ALL' ? null : logLevel.value
    const response = await diagnosticsApi.getGatewayLogs(level)
    gatewayLogs.value = response.data
  } catch (error) {
    console.error('Failed to fetch gateway logs:', error)
  } finally {
    loading.value = false
  }
}

watch(logLevel, () => {
  fetchGatewayLogs()
})

watch(tab, (newTab) => {
  if (newTab === 'connectivity') fetchConnectivity()
  else if (newTab === 'logs') fetchGatewayLogs()
})

onMounted(fetchConnectivity)
</script>
