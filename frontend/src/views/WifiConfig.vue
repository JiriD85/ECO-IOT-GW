<template>
  <v-row>
      <!-- Status Card -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>AP Status</v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item>
                <template v-slot:prepend>
                  <v-icon :color="status?.active ? 'success' : 'error'">
                    {{ status?.active ? 'mdi-wifi' : 'mdi-wifi-off' }}
                  </v-icon>
                </template>
                <v-list-item-title>Status</v-list-item-title>
                <template v-slot:append>
                  <v-chip
                    :color="status?.active ? 'success' : 'error'"
                    size="small"
                  >
                    {{ status?.active ? 'Active' : 'Inactive' }}
                  </v-chip>
                </template>
              </v-list-item>

              <v-list-item v-if="status?.ssid">
                <template v-slot:prepend>
                  <v-icon>mdi-access-point</v-icon>
                </template>
                <v-list-item-title>SSID</v-list-item-title>
                <template v-slot:append>
                  {{ status.ssid }}
                </template>
              </v-list-item>

              <v-list-item v-if="status?.channel">
                <template v-slot:prepend>
                  <v-icon>mdi-radio-tower</v-icon>
                </template>
                <v-list-item-title>Channel</v-list-item-title>
                <template v-slot:append>
                  {{ status.channel }}
                </template>
              </v-list-item>

              <v-list-item>
                <template v-slot:prepend>
                  <v-icon>mdi-devices</v-icon>
                </template>
                <v-list-item-title>Connected Clients</v-list-item-title>
                <template v-slot:append>
                  <v-chip size="small">{{ status?.clients_connected || 0 }}</v-chip>
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
          <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn
              v-if="status?.active"
              color="error"
              @click="stopAP"
              :loading="actionLoading === 'stop'"
            >
              Stop AP
            </v-btn>
            <v-btn
              v-else
              color="success"
              @click="startAP"
              :loading="actionLoading === 'start'"
            >
              Start AP
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Configuration Card -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>AP Configuration</v-card-title>
          <v-card-text>
            <v-form ref="form">
              <v-text-field
                v-model="config.ssid"
                label="SSID (Network Name)"
                :rules="[v => !!v || 'Required', v => v.length <= 32 || 'Max 32 characters']"
                counter="32"
                required
              ></v-text-field>

              <v-text-field
                v-model="config.password"
                label="Password"
                :type="showPassword ? 'text' : 'password'"
                :append-inner-icon="showPassword ? 'mdi-eye' : 'mdi-eye-off'"
                @click:append-inner="showPassword = !showPassword"
                :rules="[v => !!v || 'Required', v => v.length >= 8 || 'Min 8 characters']"
                counter="63"
                required
              ></v-text-field>

              <v-select
                v-model="config.channel"
                :items="channels"
                label="WiFi Channel"
              ></v-select>

              <v-switch
                v-model="config.hidden"
                label="Hide SSID"
              ></v-switch>
            </v-form>
          </v-card-text>
          <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn
              color="primary"
              @click="saveConfig"
              :loading="actionLoading === 'save'"
            >
              Save Configuration
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <!-- Connected Clients -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>Connected Clients</v-card-title>
          <v-card-text>
            <v-data-table
              :headers="clientHeaders"
              :items="clients"
              :loading="loading"
            >
              <template v-slot:no-data>
                No clients connected
              </template>
            </v-data-table>
          </v-card-text>
          <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn @click="fetchClients" :loading="loading">
              Refresh
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
</template>

<script setup>
import { ref, inject, onMounted, onUnmounted } from 'vue'
import { wifiApi } from '../services/api'

const showSnackbar = inject('showSnackbar')

const loading = ref(false)
const actionLoading = ref(null)
const showPassword = ref(false)

const status = ref(null)
const config = ref({
  ssid: 'ECO-IOT-GW',
  password: '',
  channel: 6,
  hidden: false
})
const clients = ref([])

const channels = Array.from({ length: 13 }, (_, i) => i + 1)

const clientHeaders = [
  { title: 'MAC Address', key: 'mac' },
  { title: 'IP Address', key: 'ip' }
]

let refreshInterval = null

const fetchData = async () => {
  try {
    const [statusRes, configRes] = await Promise.all([
      wifiApi.getStatus(),
      wifiApi.getConfig()
    ])
    status.value = statusRes.data
    if (configRes.data.ssid) {
      config.value = { ...config.value, ...configRes.data }
    }
  } catch (error) {
    console.error('Failed to fetch WiFi data:', error)
  }
}

const fetchClients = async () => {
  try {
    loading.value = true
    const response = await wifiApi.getClients()
    clients.value = response.data.clients || []
  } catch (error) {
    console.error('Failed to fetch clients:', error)
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  try {
    actionLoading.value = 'save'
    await wifiApi.setConfig(config.value)
    showSnackbar('Configuration saved')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to save', 'error')
  } finally {
    actionLoading.value = null
  }
}

const startAP = async () => {
  try {
    actionLoading.value = 'start'
    await wifiApi.start()
    showSnackbar('Access Point started')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to start', 'error')
  } finally {
    actionLoading.value = null
  }
}

const stopAP = async () => {
  try {
    actionLoading.value = 'stop'
    await wifiApi.stop()
    showSnackbar('Access Point stopped')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to stop', 'error')
  } finally {
    actionLoading.value = null
  }
}

onMounted(() => {
  fetchData()
  fetchClients()
  refreshInterval = setInterval(() => {
    fetchData()
    fetchClients()
  }, 10000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>
