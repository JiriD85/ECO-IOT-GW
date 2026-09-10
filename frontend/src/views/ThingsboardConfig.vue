<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <h1 class="text-h4 mb-4">ThingsBoard Gateway</h1>
      </v-col>
    </v-row>

    <!-- Gateway Status Card -->
    <v-row>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title class="d-flex align-center">
            Gateway Status
            <v-spacer></v-spacer>
            <v-btn
              icon
              variant="text"
              size="small"
              :loading="statusLoading"
              @click="refreshGatewayStatus"
              title="Refresh status"
            >
              <v-icon>mdi-refresh</v-icon>
            </v-btn>
          </v-card-title>
          <v-card-text>
            <v-list>
              <!-- Container Status -->
              <v-list-item>
                <template v-slot:prepend>
                  <v-icon :color="containerRunning ? 'success' : 'grey'">
                    mdi-docker
                  </v-icon>
                </template>
                <v-list-item-title>Container</v-list-item-title>
                <template v-slot:append>
                  <v-chip
                    :color="containerRunning ? 'success' : 'grey'"
                    size="small"
                  >
                    {{ containerStatus || 'Not deployed' }}
                  </v-chip>
                </template>
              </v-list-item>

              <!-- ThingsBoard Connection State -->
              <v-list-item>
                <template v-slot:prepend>
                  <v-icon :color="stateColor">
                    {{ stateIcon }}
                  </v-icon>
                </template>
                <v-list-item-title>ThingsBoard</v-list-item-title>
                <template v-slot:append>
                  <v-chip
                    :color="stateColor"
                    size="small"
                  >
                    {{ stateLabel }}
                  </v-chip>
                </template>
              </v-list-item>

              <!-- Status Message (if any) -->
              <v-list-item v-if="statusMessage">
                <template v-slot:prepend>
                  <v-icon :color="gatewayState === 'error' ? 'error' : 'grey'">
                    {{ gatewayState === 'error' ? 'mdi-alert-circle' : 'mdi-information-outline' }}
                  </v-icon>
                </template>
                <v-list-item-title class="text-caption" style="white-space: normal;">
                  {{ statusMessage }}
                </v-list-item-title>
              </v-list-item>

              <!-- Server Info -->
              <v-list-item v-if="status?.host">
                <template v-slot:prepend>
                  <v-icon>mdi-server</v-icon>
                </template>
                <v-list-item-title>Server</v-list-item-title>
                <template v-slot:append>
                  {{ status.host }}:{{ status.port }}
                </template>
              </v-list-item>

              <!-- Cache indicator -->
              <v-list-item v-if="isCached" density="compact">
                <template v-slot:prepend>
                  <v-icon size="small" color="grey">mdi-cached</v-icon>
                </template>
                <v-list-item-title class="text-caption text-grey">
                  Cached status
                </v-list-item-title>
              </v-list-item>
            </v-list>
          </v-card-text>
          <v-card-actions>
            <v-btn
              v-if="!containerRunning"
              color="success"
              :loading="actionLoading === 'deploy'"
              :disabled="!configInfo?.configured"
              @click="deployGateway"
            >
              <v-icon start>mdi-play</v-icon>
              Start Gateway
            </v-btn>
            <v-btn
              v-else
              color="error"
              variant="outlined"
              :loading="actionLoading === 'stop'"
              @click="stopGateway"
            >
              <v-icon start>mdi-stop</v-icon>
              Stop
            </v-btn>
            <v-btn
              v-if="containerRunning"
              color="warning"
              variant="outlined"
              :loading="actionLoading === 'restart'"
              @click="restartGateway"
            >
              <v-icon start>mdi-restart</v-icon>
              Restart
            </v-btn>
            <v-spacer></v-spacer>
            <v-btn
              color="primary"
              variant="text"
              :loading="actionLoading === 'test'"
              @click="testConnection"
            >
              Test TCP connection
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

    </v-row>

    <!-- Configuration Form -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>Connection Settings</v-card-title>
          <v-card-text>
            <v-form ref="configForm" @submit.prevent="saveConfig">
              <v-row>
                <v-col cols="12" md="6">
                  <v-text-field
                    v-model="config.host"
                    label="Platform URL"
                    hint="ThingsBoard MQTT broker hostname"
                    persistent-hint
                    :rules="[v => !!v || 'Platform URL is required']"
                  ></v-text-field>
                </v-col>
                <v-col cols="12" md="6">
                  <v-text-field
                    v-model.number="config.port"
                    label="MQTT Port"
                    type="number"
                    hint="1883 for plain MQTT, 8883 for TLS"
                    persistent-hint
                    :rules="[v => (v >= 1 && v <= 65535) || 'Port must be 1-65535']"
                  ></v-text-field>
                </v-col>
              </v-row>

              <v-divider class="my-4"></v-divider>
              <div class="text-subtitle-1 mb-2">Authentication</div>

              <v-radio-group v-model="config.security_type" inline :disabled="configInfo?.use_tls">
                <v-radio label="Access Token" value="access_token"></v-radio>
                <v-radio label="TLS + Access Token" value="tls_access_token" :disabled="configInfo?.security_type !== 'tls_access_token'"></v-radio>
                <v-radio label="Username + Password" value="username_password"></v-radio>
              </v-radio-group>

              <!-- Access Token Mode -->
              <div v-if="config.security_type === 'access_token' || config.security_type === 'tls_access_token'">
                <v-text-field
                  v-model="config.access_token"
                  label="Access Token"
                  hint="Copy from ThingsBoard device credentials"
                  persistent-hint
                  :type="showToken ? 'text' : 'password'"
                  :append-inner-icon="showToken ? 'mdi-eye' : 'mdi-eye-off'"
                  @click:append-inner="showToken = !showToken"
                ></v-text-field>
              </div>

              <p v-if="config.use_tls" class="mt-4">Existing TLS configuration is retained.</p>

              <!-- Username/Password Mode -->
              <div v-if="config.security_type === 'username_password'" class="mt-4">
                <v-row>
                  <v-col cols="12" md="4">
                    <v-text-field
                      v-model="config.client_id"
                      label="Client ID"
                      hint="MQTT client identifier"
                      persistent-hint
                    ></v-text-field>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-text-field
                      v-model="config.username"
                      label="Username"
                      :rules="[v => !!v || configInfo?.has_credentials || 'Username is required']"
                    ></v-text-field>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-text-field
                      v-model="config.password"
                      label="Password"
                      :type="showPassword ? 'text' : 'password'"
                      :append-inner-icon="showPassword ? 'mdi-eye' : 'mdi-eye-off'"
                      @click:append-inner="showPassword = !showPassword"
                      :rules="[v => !!v || configInfo?.has_credentials || 'Password is required']"
                    ></v-text-field>
                  </v-col>
                </v-row>
              </div>
            </v-form>
          </v-card-text>
          <v-card-actions>

            <v-spacer></v-spacer>
            <v-btn
              color="primary"
              :loading="actionLoading === 'save'"
              @click="saveConfig"
            >
              <v-icon start>mdi-content-save</v-icon>
              Save Configuration
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <!-- Logs Section -->
    <v-row class="mt-4" v-if="containerRunning">
      <v-col cols="12">
        <v-card>
          <v-card-title class="d-flex align-center">
            Gateway Logs
            <v-spacer></v-spacer>
            <v-btn variant="text" size="small" @click="fetchLogs">
              <v-icon>mdi-refresh</v-icon>
            </v-btn>
          </v-card-title>
          <v-card-text>
            <pre class="logs-container">{{ logs || 'Load logs with Refresh' }}</pre>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

  </v-container>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import api from '../services/api'
import { useSnackbar } from '../composables/useSnackbar'
import { useGatewayStatus } from '../composables/useGatewayStatus'

const { showSnackbar } = useSnackbar()

// Use the gateway status composable
const {
  status: gatewayStatus,
  loading: statusLoading,
  state: gatewayState,
  stateColor,
  stateIcon,
  stateLabel,
  message: statusMessage,
  containerRunning,
  containerStatus,
  mqttConnected,
  isCached,
  forceRefresh: refreshGatewayStatus,
  fetchStatus: fetchGatewayStatus,
  startPolling,
  stopPolling
} = useGatewayStatus({ autoStart: false })

const status = ref(null)
const configInfo = ref(null)
const actionLoading = ref(null)
const showToken = ref(false)
const showPassword = ref(false)
const caCertUploaded = ref(false)
const configForm = ref(null)
const logs = ref('')


const config = ref({
  host: 'lb-mqtt.pke-iot.expert',
  port: 1883,
  security_type: 'access_token',
  access_token: '',
  use_tls: false,
  ca_cert: null,
  client_id: '',
  username: '',
  password: ''
})

const fetchData = async () => {
  try {
    const [statusRes, configRes] = await Promise.all([
      api.get('/api/thingsboard/status'),
      api.get('/api/thingsboard/config')
    ])

    status.value = statusRes.data
    configInfo.value = configRes.data

    // Fetch gateway status via composable
    await fetchGatewayStatus()

    if (configRes.data.configured) {
      config.value.host = configRes.data.host || config.value.host
      config.value.port = configRes.data.port || config.value.port
      config.value.security_type = configRes.data.security_type || config.value.security_type
      config.value.use_tls = configRes.data.use_tls || false
      caCertUploaded.value = configRes.data.has_ca_cert || false
    }

  } catch (error) {
    console.error('Failed to fetch ThingsBoard data:', error)
  }
}

const fetchLogs = async () => {
  try {
    const res = await api.get('/api/thingsboard/logs?lines=50')
    if (res.data.success) {
      logs.value = res.data.logs
    }
  } catch (error) {
    console.error('Failed to fetch logs:', error)
  }
}

const saveConfig = async () => {
  const { valid } = await configForm.value.validate()
  if (!valid) return

  try {
    actionLoading.value = 'save'
    await api.put('/api/thingsboard/config', config.value)
    showSnackbar('Connection saved. Restart the gateway to apply it.')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to save configuration', 'error')
  } finally {
    actionLoading.value = null
  }
}

const deployGateway = async () => {
  try {
    actionLoading.value = 'deploy'
    const res = await api.post('/api/thingsboard/deploy')
    if (res.data.success) {
      showSnackbar(res.data.message, 'success')
      // Wait for container to start, then force refresh status
      setTimeout(async () => {
        await refreshGatewayStatus()
        fetchLogs()
      }, 3000)
    } else {
      showSnackbar(res.data.error, 'error')
    }
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to deploy gateway', 'error')
  } finally {
    actionLoading.value = null
  }
}

const stopGateway = async () => {
  try {
    actionLoading.value = 'stop'
    const res = await api.post('/api/thingsboard/stop')
    if (res.data.success) {
      showSnackbar(res.data.message)
      await refreshGatewayStatus()
    } else {
      showSnackbar(res.data.error, 'error')
    }
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to stop gateway', 'error')
  } finally {
    actionLoading.value = null
  }
}

const restartGateway = async () => {
  try {
    actionLoading.value = 'restart'
    await api.post('/api/thingsboard/restart')
    showSnackbar('Gateway restarting...')
    // Wait for restart, then force refresh status
    setTimeout(async () => {
      await refreshGatewayStatus()
      fetchLogs()
    }, 5000)
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to restart gateway', 'error')
  } finally {
    actionLoading.value = null
  }
}

const testConnection = async () => {
  try {
    actionLoading.value = 'test'
    const response = await api.post('/api/thingsboard/test')
    if (response.data.success) {
      showSnackbar(response.data.message, 'success')
    } else {
      showSnackbar(response.data.error, 'error')
    }
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Connection test failed', 'error')
  } finally {
    actionLoading.value = null
  }
}

const downloadCertFromPlatform = async () => {
  try {
    actionLoading.value = 'downloadCert'
    const response = await api.post('/api/thingsboard/download-cert', null, {
      params: { host: config.value.host }
    })
    if (response.data.success) {
      caCertUploaded.value = true
      showSnackbar(response.data.message, 'success')
    } else {
      showSnackbar(response.data.error, 'error')
    }
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to download certificate', 'error')
  } finally {
    actionLoading.value = null
  }
}

onMounted(() => {
  fetchData()
})

onUnmounted(stopPolling)
</script>

<style scoped>
.logs-container {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 4px;
  max-height: 300px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.compose-preview {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 4px;
  max-height: 500px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;
  white-space: pre;
}
</style>
