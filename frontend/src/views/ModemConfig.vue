<template>
  <v-row>
      <!-- Status Card -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Connection Status <v-btn variant="text" size="small" @click="fetchData">Refresh status</v-btn></v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item>
                <template v-slot:prepend>
                  <v-icon :color="status?.connected ? 'success' : 'error'">
                    {{ status?.connected ? 'mdi-signal-cellular-3' : 'mdi-signal-cellular-outline' }}
                  </v-icon>
                </template>
                <v-list-item-title>Status</v-list-item-title>
                <template v-slot:append>
                  <v-chip
                    :color="status?.connected ? 'success' : 'error'"
                    size="small"
                  >
                    {{ status?.connected ? 'Connected' : 'Disconnected' }}
                  </v-chip>
                </template>
              </v-list-item>

              <v-list-item v-if="status && status.signal_quality != null">
                <template v-slot:prepend>
                  <v-icon>mdi-signal</v-icon>
                </template>
                <v-list-item-title>Signal Quality</v-list-item-title>
                <template v-slot:append>
                  <v-progress-linear
                    :model-value="status.signal_quality"
                    :color="signalColor"
                    height="20"
                    style="width: 100px"
                  >
                    {{ status.signal_quality }}%
                  </v-progress-linear>
                </template>
              </v-list-item>

              <v-list-item v-if="status?.signal_strength">
                <template v-slot:prepend>
                  <v-icon>mdi-access-point</v-icon>
                </template>
                <v-list-item-title>Signal Strength</v-list-item-title>
                <template v-slot:append>
                  {{ status.signal_strength }} dBm
                </template>
              </v-list-item>

              <v-list-item v-if="status?.network_type">
                <template v-slot:prepend>
                  <v-icon>mdi-network</v-icon>
                </template>
                <v-list-item-title>Network Type</v-list-item-title>
                <template v-slot:append>
                  <v-chip size="small">{{ status.network_type }}</v-chip>
                </template>
              </v-list-item>

              <v-list-item v-if="status?.carrier">
                <template v-slot:prepend>
                  <v-icon>mdi-sim</v-icon>
                </template>
                <v-list-item-title>Carrier</v-list-item-title>
                <template v-slot:append>
                  {{ status.carrier }}
                </template>
              </v-list-item>

              <v-list-item v-if="status?.ip_address">
                <template v-slot:prepend>
                  <v-icon>mdi-ip-network</v-icon>
                </template>
                <v-list-item-title>IP Address</v-list-item-title>
                <template v-slot:append>
                  {{ status.ip_address }}
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
          <v-card-actions>
            <v-btn color="warning" @click="resetModem" :loading="actionLoading === 'reset'">
              Reset Modem
            </v-btn>
            <v-spacer></v-spacer>
            <v-btn
              v-if="status?.connected"
              color="error"
              @click="disconnect"
              :loading="actionLoading === 'disconnect'"
            >
              Disconnect
            </v-btn>
            <v-btn
              v-else
              color="success"
              @click="connect"
              :loading="actionLoading === 'connect'"
            >
              Connect
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Configuration Card -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>APN Configuration</v-card-title>
          <v-card-text>
            <v-form ref="form">
              <v-text-field
                v-model="config.apn"
                label="APN"
                required
              ></v-text-field>

              <v-text-field
                v-model="config.username"
                label="Username (optional)"
              ></v-text-field>

              <v-text-field
                v-model="config.password"
                label="Password (optional)"
                :type="showPassword ? 'text' : 'password'"
                :append-inner-icon="showPassword ? 'mdi-eye' : 'mdi-eye-off'"
                @click:append-inner="showPassword = !showPassword"
              ></v-text-field>

              <v-text-field
                v-model="config.pin"
                label="SIM PIN (optional)"
                :type="showPin ? 'text' : 'password'"
                :append-inner-icon="showPin ? 'mdi-eye' : 'mdi-eye-off'"
                @click:append-inner="showPin = !showPin"
              ></v-text-field>

              <v-switch
                v-model="config.auto_connect"
                label="Auto-connect on boot"
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

    <!-- Device Info -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>Device Information</v-card-title>
          <v-card-text>
            <v-row>
              <v-col cols="12" md="4">
                <div class="text-caption">IMEI</div>
                <div>{{ status?.imei || '--' }}</div>
              </v-col>
              <v-col cols="12" md="4">
                <div class="text-caption">IMSI</div>
                <div>{{ status?.imsi || '--' }}</div>
              </v-col>
              <v-col cols="12" md="4">
                <div class="text-caption">ICCID</div>
                <div>{{ status?.iccid || '--' }}</div>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
</template>

<script setup>
import { ref, computed, inject, onMounted, onUnmounted } from 'vue'
import { modemApi } from '../services/api'

const showSnackbar = inject('showSnackbar')

const status = ref(null)
const config = ref({
  apn: '',
  username: '',
  password: '',
  pin: '',
  auto_connect: true
})
const showPassword = ref(false)
const showPin = ref(false)
const actionLoading = ref(null)



const signalColor = computed(() => {
  const quality = status.value?.signal_quality || 0
  if (quality > 60) return 'success'
  if (quality > 30) return 'warning'
  return 'error'
})

const fetchData = async () => {
  try {
    const [statusRes, configRes] = await Promise.all([
      modemApi.getStatus(),
      modemApi.getConfig()
    ])
    status.value = statusRes.data
    if (configRes.data.apn) {
      config.value = { ...config.value, ...configRes.data }
    }
  } catch (error) {
    console.error('Failed to fetch modem data:', error)
  }
}

const saveConfig = async () => {
  try {
    actionLoading.value = 'save'
    await modemApi.setConfig(config.value)
    showSnackbar('Configuration saved')
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to save', 'error')
  } finally {
    actionLoading.value = null
  }
}

const connect = async () => {
  try {
    actionLoading.value = 'connect'
    await modemApi.connect()
    showSnackbar('Connecting...')
    setTimeout(fetchData, 5000)
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to connect', 'error')
  } finally {
    actionLoading.value = null
  }
}

const disconnect = async () => {
  try {
    actionLoading.value = 'disconnect'
    await modemApi.disconnect()
    showSnackbar('Disconnected')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to disconnect', 'error')
  } finally {
    actionLoading.value = null
  }
}

const resetModem = async () => {
  try {
    actionLoading.value = 'reset'
    await modemApi.reset()
    showSnackbar('Modem reset initiated')
    setTimeout(fetchData, 10000)
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Reset failed', 'error')
  } finally {
    actionLoading.value = null
  }
}

onMounted(() => {
  fetchData()

})


</script>
