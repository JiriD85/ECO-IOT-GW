<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <h1 class="text-h4 mb-4">VPN Configuration</h1>
      </v-col>
    </v-row>

    <!-- Status Card -->
    <v-row>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Connection Status</v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item>
                <template v-slot:prepend>
                  <v-icon :color="status?.connected ? 'success' : 'error'">
                    {{ status?.connected ? 'mdi-check-circle' : 'mdi-close-circle' }}
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
              <v-list-item v-if="status?.vpn_type">
                <template v-slot:prepend>
                  <v-icon>mdi-vpn</v-icon>
                </template>
                <v-list-item-title>Type</v-list-item-title>
                <template v-slot:append>
                  {{ status.vpn_type }}
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
            <v-spacer></v-spacer>
            <v-btn
              v-if="status?.connected"
              color="error"
              :loading="actionLoading === 'disconnect'"
              @click="vpnDisconnect"
            >
              Disconnect
            </v-btn>
            <v-btn
              v-else
              color="success"
              :loading="actionLoading === 'connect'"
              :disabled="!configInfo?.configured"
              @click="vpnConnect"
            >
              Connect
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Type Selection -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>VPN Type</v-card-title>
          <v-card-text>
            <v-radio-group v-model="selectedType" @update:model-value="changeType">
              <v-radio label="OpenVPN" value="openvpn"></v-radio>
              <v-radio label="WireGuard" value="wireguard"></v-radio>
              <v-radio label="Tailscale" value="tailscale"></v-radio>
            </v-radio-group>

            <v-divider class="my-4"></v-divider>

            <v-switch
              v-model="autostart"
              label="Autostart on boot"
              @update:model-value="toggleAutostart"
            ></v-switch>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Configuration Upload -->
    <v-row class="mt-4" v-if="selectedType !== 'tailscale'">
      <v-col cols="12">
        <v-card>
          <v-card-title>
            {{ selectedType === 'openvpn' ? 'OpenVPN Configuration' : 'WireGuard Configuration' }}
          </v-card-title>
          <v-card-text>
            <div
              class="drop-zone pa-8 text-center"
              :class="{ 'drop-zone-active': isDragging }"
              @dragover.prevent="isDragging = true"
              @dragleave="isDragging = false"
              @drop.prevent="handleDrop"
            >
              <v-icon size="48" class="mb-2">mdi-cloud-upload</v-icon>
              <div class="text-h6">
                Drop {{ selectedType === 'openvpn' ? '.ovpn' : '.conf' }} file here
              </div>
              <div class="text-caption">or click to select file</div>
              <input
                type="file"
                ref="fileInput"
                :accept="selectedType === 'openvpn' ? '.ovpn' : '.conf'"
                style="display: none"
                @change="handleFileSelect"
              >
              <v-btn
                color="primary"
                variant="outlined"
                class="mt-4"
                @click="$refs.fileInput.click()"
              >
                Select File
              </v-btn>
            </div>

            <v-alert
              v-if="configInfo?.configured"
              type="success"
              class="mt-4"
              variant="tonal"
            >
              Configuration file uploaded
            </v-alert>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Tailscale Auth -->
    <v-row class="mt-4" v-if="selectedType === 'tailscale'">
      <v-col cols="12">
        <v-card>
          <v-card-title>Tailscale Authentication</v-card-title>
          <v-card-text>
            <v-text-field
              v-model="tailscaleKey"
              label="Auth Key"
              hint="Get from https://login.tailscale.com/admin/settings/keys"
              persistent-hint
              :type="showKey ? 'text' : 'password'"
              :append-inner-icon="showKey ? 'mdi-eye' : 'mdi-eye-off'"
              @click:append-inner="showKey = !showKey"
            ></v-text-field>
          </v-card-text>
          <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn
              color="primary"
              :loading="actionLoading === 'auth'"
              :disabled="!tailscaleKey"
              @click="tailscaleAuth"
            >
              Authenticate
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, inject, onMounted } from 'vue'
import { vpnApi } from '../services/api'
import api from '../services/api'

const showSnackbar = inject('showSnackbar')

const status = ref(null)
const configInfo = ref(null)
const selectedType = ref('openvpn')
const autostart = ref(false)
const isDragging = ref(false)
const tailscaleKey = ref('')
const showKey = ref(false)
const actionLoading = ref(null)

const fetchData = async () => {
  try {
    const [statusRes, typeRes, autostartRes] = await Promise.all([
      vpnApi.getStatus(),
      vpnApi.getType(),
      vpnApi.getAutostart()
    ])

    status.value = statusRes.data
    if (typeRes.data.vpn_type) {
      selectedType.value = typeRes.data.vpn_type
    }
    autostart.value = autostartRes.data.enabled

    // Get config info
    const configRes = await api.get('/api/vpn/config')
    configInfo.value = configRes.data
  } catch (error) {
    console.error('Failed to fetch VPN data:', error)
  }
}

const changeType = async (type) => {
  try {
    await vpnApi.setType(type)
    showSnackbar(`VPN type set to ${type}`)
    await fetchData()
  } catch (error) {
    showSnackbar('Failed to change VPN type', 'error')
  }
}

const toggleAutostart = async (enabled) => {
  try {
    await vpnApi.setAutostart(enabled)
    showSnackbar(`Autostart ${enabled ? 'enabled' : 'disabled'}`)
  } catch (error) {
    showSnackbar('Failed to update autostart', 'error')
    autostart.value = !enabled
  }
}

const handleDrop = async (event) => {
  isDragging.value = false
  const files = event.dataTransfer.files
  if (files.length > 0) {
    await uploadFile(files[0])
  }
}

const handleFileSelect = async (event) => {
  const files = event.target.files
  if (files.length > 0) {
    await uploadFile(files[0])
  }
}

const uploadFile = async (file) => {
  try {
    await vpnApi.uploadConfig(file, selectedType.value)
    showSnackbar('Configuration uploaded successfully')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Upload failed', 'error')
  }
}

const vpnConnect = async () => {
  try {
    actionLoading.value = 'connect'
    await vpnApi.connect()
    showSnackbar('VPN connecting...')
    setTimeout(fetchData, 3000)
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to connect', 'error')
  } finally {
    actionLoading.value = null
  }
}

const vpnDisconnect = async () => {
  try {
    actionLoading.value = 'disconnect'
    await vpnApi.disconnect()
    showSnackbar('VPN disconnected')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to disconnect', 'error')
  } finally {
    actionLoading.value = null
  }
}

const tailscaleAuth = async () => {
  try {
    actionLoading.value = 'auth'
    await api.post('/api/vpn/tailscale/auth', { auth_key: tailscaleKey.value })
    showSnackbar('Tailscale authentication initiated')
    tailscaleKey.value = ''
    setTimeout(fetchData, 5000)
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Authentication failed', 'error')
  } finally {
    actionLoading.value = null
  }
}

onMounted(fetchData)
</script>

<style scoped>
.drop-zone {
  border: 2px dashed #666;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
}

.drop-zone:hover,
.drop-zone-active {
  border-color: #1976D2;
  background: rgba(25, 118, 210, 0.1);
}
</style>
