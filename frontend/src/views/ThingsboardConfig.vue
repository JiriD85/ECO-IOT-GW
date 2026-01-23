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
          <v-card-title>Gateway Status</v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item>
                <template v-slot:prepend>
                  <v-icon :color="gatewayStatus?.running ? 'success' : 'error'">
                    {{ gatewayStatus?.running ? 'mdi-docker' : 'mdi-docker' }}
                  </v-icon>
                </template>
                <v-list-item-title>Container</v-list-item-title>
                <template v-slot:append>
                  <v-chip
                    :color="gatewayStatus?.running ? 'success' : 'grey'"
                    size="small"
                  >
                    {{ gatewayStatus?.status || 'Not deployed' }}
                  </v-chip>
                </template>
              </v-list-item>
              <v-list-item>
                <template v-slot:prepend>
                  <v-icon :color="status?.connected ? 'success' : 'warning'">
                    {{ status?.connected ? 'mdi-cloud-check' : 'mdi-cloud-off-outline' }}
                  </v-icon>
                </template>
                <v-list-item-title>ThingsBoard</v-list-item-title>
                <template v-slot:append>
                  <v-chip
                    :color="status?.connected ? 'success' : 'warning'"
                    size="small"
                  >
                    {{ status?.connected ? 'Connected' : 'Disconnected' }}
                  </v-chip>
                </template>
              </v-list-item>
              <v-list-item v-if="status?.host">
                <template v-slot:prepend>
                  <v-icon>mdi-server</v-icon>
                </template>
                <v-list-item-title>Server</v-list-item-title>
                <template v-slot:append>
                  {{ status.host }}:{{ status.port }}
                </template>
              </v-list-item>
              <v-list-item v-if="status?.error">
                <template v-slot:prepend>
                  <v-icon color="error">mdi-alert-circle</v-icon>
                </template>
                <v-list-item-title>Error</v-list-item-title>
                <template v-slot:append>
                  <span class="text-error text-caption">{{ status.error }}</span>
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
          <v-card-actions>
            <v-btn
              v-if="!gatewayStatus?.running"
              color="success"
              :loading="actionLoading === 'deploy'"
              :disabled="!configInfo?.configured"
              @click="deployGateway"
            >
              <v-icon start>mdi-play</v-icon>
              Deploy Gateway
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
              v-if="gatewayStatus?.running"
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
              Test Connection
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Available Devices -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Serial Devices</v-card-title>
          <v-card-text>
            <v-list v-if="devices?.devices?.length > 0" density="compact">
              <v-list-item v-for="dev in devices.devices" :key="dev.path">
                <template v-slot:prepend>
                  <v-icon>mdi-serial-port</v-icon>
                </template>
                <v-list-item-title>{{ dev.path }}</v-list-item-title>
                <template v-slot:append>
                  <v-chip size="x-small" variant="outlined">{{ dev.type }}</v-chip>
                </template>
              </v-list-item>
            </v-list>
            <v-alert v-else type="info" variant="tonal" density="compact">
              No serial devices detected. Connect RS485/Modbus adapters to see them here.
            </v-alert>
          </v-card-text>
          <v-card-actions>
            <v-btn variant="text" size="small" @click="fetchDevices">
              <v-icon start>mdi-refresh</v-icon>
              Refresh
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

              <v-radio-group v-model="config.security_type" inline>
                <v-radio label="Access Token" value="access_token"></v-radio>
                <v-radio label="TLS + Access Token" value="tls_access_token"></v-radio>
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

              <!-- TLS Settings -->
              <div v-if="config.security_type === 'tls_access_token'" class="mt-4">
                <v-switch
                  v-model="config.use_tls"
                  label="Enable TLS (Port 8883)"
                  color="primary"
                ></v-switch>

                <div v-if="config.use_tls" class="mt-4">
                  <div class="d-flex align-center mb-3">
                    <v-btn
                      color="secondary"
                      variant="outlined"
                      size="small"
                      :loading="actionLoading === 'downloadCert'"
                      @click="downloadCertFromPlatform"
                    >
                      <v-icon start>mdi-download</v-icon>
                      Download CA from Platform
                    </v-btn>
                    <v-chip v-if="caCertUploaded || configInfo?.has_ca_cert" color="success" class="ml-3" size="small">
                      <v-icon start size="small">mdi-certificate</v-icon>
                      Certificate ready
                    </v-chip>
                  </div>
                </div>
              </div>

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
                      :rules="[v => !!v || 'Username is required']"
                    ></v-text-field>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-text-field
                      v-model="config.password"
                      label="Password"
                      :type="showPassword ? 'text' : 'password'"
                      :append-inner-icon="showPassword ? 'mdi-eye' : 'mdi-eye-off'"
                      @click:append-inner="showPassword = !showPassword"
                      :rules="[v => !!v || 'Password is required']"
                    ></v-text-field>
                  </v-col>
                </v-row>
              </div>
            </v-form>
          </v-card-text>
          <v-card-actions>
            <v-btn
              color="secondary"
              variant="text"
              @click="loadComposePreview"
            >
              <v-icon start>mdi-file-code</v-icon>
              Preview docker-compose
            </v-btn>
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
    <v-row class="mt-4" v-if="gatewayStatus?.running">
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
            <pre class="logs-container">{{ logs || 'Loading logs...' }}</pre>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Docker Compose Preview Dialog -->
    <v-dialog v-model="showComposePreview" max-width="800">
      <v-card>
        <v-card-title>docker-compose.yml Preview</v-card-title>
        <v-card-text>
          <pre class="compose-preview">{{ composePreview }}</pre>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn @click="showComposePreview = false">Close</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import api from '../services/api'
import { useSnackbar } from '../composables/useSnackbar'

const { showSnackbar } = useSnackbar()

const status = ref(null)
const gatewayStatus = ref(null)
const configInfo = ref(null)
const devices = ref(null)
const actionLoading = ref(null)
const showToken = ref(false)
const showPassword = ref(false)
const caCertUploaded = ref(false)
const configForm = ref(null)
const logs = ref('')
const showComposePreview = ref(false)
const composePreview = ref('')
let refreshInterval = null

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
    const [statusRes, configRes, gatewayRes] = await Promise.all([
      api.get('/api/thingsboard/status'),
      api.get('/api/thingsboard/config'),
      api.get('/api/thingsboard/gateway-status')
    ])

    status.value = statusRes.data
    configInfo.value = configRes.data
    gatewayStatus.value = gatewayRes.data

    if (configRes.data.configured) {
      config.value.host = configRes.data.host || config.value.host
      config.value.port = configRes.data.port || config.value.port
      config.value.security_type = configRes.data.security_type || config.value.security_type
      config.value.use_tls = configRes.data.use_tls || false
      caCertUploaded.value = configRes.data.has_ca_cert || false
    }

    if (gatewayRes.data.running) {
      fetchLogs()
    }
  } catch (error) {
    console.error('Failed to fetch ThingsBoard data:', error)
  }
}

const fetchDevices = async () => {
  try {
    const res = await api.get('/api/thingsboard/devices')
    devices.value = res.data
  } catch (error) {
    console.error('Failed to fetch devices:', error)
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
    showSnackbar('Configuration saved successfully')
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
      setTimeout(fetchData, 3000)
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
      await fetchData()
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
    setTimeout(fetchData, 5000)
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

const loadComposePreview = async () => {
  try {
    const res = await api.get('/api/thingsboard/compose-preview')
    if (res.data.success) {
      composePreview.value = res.data.content
    } else {
      composePreview.value = `Error: ${res.data.error}`
    }
  } catch (error) {
    composePreview.value = 'Failed to load preview'
  }
  showComposePreview.value = true
}

// Watch for compose preview dialog
const openPreview = () => {
  loadComposePreview()
}

onMounted(() => {
  fetchData()
  fetchDevices()
  refreshInterval = setInterval(fetchData, 10000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
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
