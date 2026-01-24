<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <h1 class="text-h4 mb-4">Network Status & Failover</h1>
      </v-col>
    </v-row>

    <!-- Current Network Status Section -->
    <v-row>
      <v-col cols="12">
        <v-card>
          <v-card-title>
            Current Network Status
            <v-spacer></v-spacer>
            <v-btn
              color="primary"
              variant="text"
              @click="loadStatus"
              :loading="loading"
              size="small"
            >
              <v-icon>mdi-refresh</v-icon>
              Refresh
            </v-btn>
          </v-card-title>
          <v-card-text>
            <v-row v-if="networkStatus">
              <!-- Active Route Info -->
              <v-col cols="12">
                <v-alert
                  v-if="networkStatus.active_route"
                  type="info"
                  variant="tonal"
                  density="compact"
                >
                  <strong>Active Route:</strong>
                  {{ networkStatus.active_route.interface }} via {{ networkStatus.active_route.gateway }}
                  (metric: {{ networkStatus.active_route.metric }})
                </v-alert>
              </v-col>

              <!-- Interface Cards -->
              <v-col
                v-for="iface in networkStatus.interfaces"
                :key="iface.name"
                cols="12"
                md="6"
              >
                <v-card
                  :color="iface.is_up ? 'success' : 'grey'"
                  variant="outlined"
                  :class="isActiveInterface(iface.name) ? 'border-success' : ''"
                  style="border-width: 2px;"
                >
                  <v-card-title class="d-flex align-center">
                    {{ iface.name }}
                    <v-spacer></v-spacer>
                    <v-chip
                      :color="iface.is_up ? 'success' : 'error'"
                      size="small"
                    >
                      {{ iface.is_up ? 'UP' : 'DOWN' }}
                    </v-chip>
                    <v-chip
                      v-if="isActiveInterface(iface.name)"
                      color="primary"
                      size="small"
                      class="ml-2"
                    >
                      ACTIVE
                    </v-chip>
                  </v-card-title>
                  <v-card-text>
                    <v-list density="compact">
                      <v-list-item v-if="iface.speed_mbps">
                        <v-list-item-title>Speed</v-list-item-title>
                        <template v-slot:append>{{ iface.speed_mbps }} Mbps</template>
                      </v-list-item>
                      <v-list-item>
                        <v-list-item-title>MTU</v-list-item-title>
                        <template v-slot:append>{{ iface.mtu }}</template>
                      </v-list-item>
                      <v-list-item>
                        <v-list-item-title>TX / RX</v-list-item-title>
                        <template v-slot:append>{{ formatBytes(iface.bytes_sent) }} / {{ formatBytes(iface.bytes_recv) }}</template>
                      </v-list-item>
                      <v-list-item v-if="iface.errors_in || iface.errors_out">
                        <v-list-item-title>Errors</v-list-item-title>
                        <template v-slot:append>{{ iface.errors_in }} / {{ iface.errors_out }}</template>
                      </v-list-item>
                    </v-list>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>
            <v-row v-else>
              <v-col cols="12">
                <v-alert type="info">Loading network status...</v-alert>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Failover Configuration Section -->
    <v-row class="mt-4">
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Failover Configuration</v-card-title>
          <v-card-text>
            <v-form>
              <v-select
                v-model="failoverConfig.primary_interface"
                :items="interfaceOptions"
                label="Primary Interface"
                hint="Interface to use as primary connection"
                persistent-hint
                class="mb-3"
              ></v-select>

              <v-select
                v-model="failoverConfig.backup_interface"
                :items="interfaceOptions"
                label="Backup Interface"
                hint="Interface to failover to when primary fails"
                persistent-hint
                class="mb-3"
              ></v-select>

              <v-text-field
                v-model.number="failoverConfig.primary_metric"
                type="number"
                label="Primary Metric"
                hint="Lower metric = higher priority (0-1000)"
                persistent-hint
                min="0"
                max="1000"
                class="mb-3"
              ></v-text-field>

              <v-text-field
                v-model.number="failoverConfig.backup_metric"
                type="number"
                label="Backup Metric"
                hint="Should be higher than primary metric"
                persistent-hint
                min="0"
                max="1000"
                class="mb-3"
              ></v-text-field>

              <v-alert type="info" density="compact" class="mb-3">
                Lower metric values have higher priority. Typical: Primary=100, Backup=200
              </v-alert>
            </v-form>
          </v-card-text>
          <v-card-actions>
            <v-btn
              color="primary"
              @click="saveConfig"
              :loading="saving"
              :disabled="!isAdmin"
            >
              <v-icon start>mdi-content-save</v-icon>
              Save Configuration
            </v-btn>
            <v-chip v-if="!isAdmin" color="warning" size="small">
              Admin only
            </v-chip>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Connectivity Testing Section -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Connectivity Testing</v-card-title>
          <v-card-text>
            <v-form>
              <v-select
                v-model="testInterface"
                :items="interfaceOptions"
                label="Interface to Test"
                class="mb-3"
              ></v-select>

              <v-text-field
                v-model="testTarget"
                label="Ping Target"
                hint="IP address or hostname to ping"
                persistent-hint
                class="mb-3"
              ></v-text-field>
            </v-form>

            <!-- Test Results -->
            <v-alert
              v-if="testResult"
              :type="testResult.success ? 'success' : 'error'"
              class="mt-3"
            >
              <div v-if="testResult.success">
                <strong>Connectivity OK</strong>
                <div v-if="testResult.avg_latency_ms">
                  Average Latency: {{ testResult.avg_latency_ms.toFixed(2) }} ms
                </div>
                <div v-if="testResult.packet_loss !== undefined">
                  Packet Loss: {{ testResult.packet_loss }}%
                </div>
              </div>
              <div v-else>
                <strong>Connectivity Failed</strong>
                <div v-if="testResult.error">{{ testResult.error }}</div>
              </div>
            </v-alert>
          </v-card-text>
          <v-card-actions>
            <v-btn
              color="secondary"
              @click="runConnectivityTest"
              :loading="testLoading"
            >
              <v-icon start>mdi-network</v-icon>
              Run Test
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { networkApi } from '@/services/api'
import { useAuthStore } from '@/services/auth'
import { useSnackbar } from '@/composables/useSnackbar'

const authStore = useAuthStore()
const { showSnackbar } = useSnackbar()

// Reactive state
const loading = ref(false)
const saving = ref(false)
const testLoading = ref(false)

const networkStatus = ref(null)
const failoverConfig = ref({
  primary_interface: 'eth0',
  backup_interface: 'wwan0',
  primary_metric: 100,
  backup_metric: 200
})

const testInterface = ref('eth0')
const testTarget = ref('8.8.8.8')
const testResult = ref(null)

// Computed
const isAdmin = computed(() => authStore.user?.role === 'admin')

const interfaceOptions = computed(() => {
  if (!networkStatus.value?.interfaces) return ['eth0', 'wwan0', 'usb0']
  return networkStatus.value.interfaces.map(iface => iface.name)
})

const isActiveInterface = (interfaceName) => {
  return networkStatus.value?.active_route?.interface === interfaceName
}

const formatBytes = (bytes) => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

// Methods
const loadStatus = async () => {
  loading.value = true
  try {
    const response = await networkApi.getStatus()
    networkStatus.value = response.data
  } catch (error) {
    showSnackbar('Failed to load network status', 'error')
  } finally {
    loading.value = false
  }
}

const loadFailoverConfig = async () => {
  try {
    const response = await networkApi.getFailoverConfig()
    failoverConfig.value = response.data
  } catch (error) {
    showSnackbar('Failed to load failover config', 'error')
  }
}

const saveConfig = async () => {
  if (!isAdmin.value) {
    showSnackbar('Admin privileges required', 'error')
    return
  }

  // Validate metrics
  if (failoverConfig.value.primary_metric >= failoverConfig.value.backup_metric) {
    showSnackbar('Primary metric should be lower than backup metric', 'warning')
    return
  }

  saving.value = true
  try {
    await networkApi.setFailoverConfig(failoverConfig.value)
    showSnackbar('Failover configuration saved successfully')
    await loadStatus() // Reload to see new metrics applied
  } catch (error) {
    showSnackbar(
      'Failed to save failover config: ' + (error.response?.data?.detail || error.message),
      'error'
    )
  } finally {
    saving.value = false
  }
}

const runConnectivityTest = async () => {
  testLoading.value = true
  testResult.value = null

  try {
    const response = await networkApi.testConnectivity(testInterface.value, testTarget.value)
    testResult.value = response.data

    if (response.data.success) {
      showSnackbar('Connectivity test successful')
    } else {
      showSnackbar('Connectivity test failed', 'warning')
    }
  } catch (error) {
    showSnackbar('Failed to run connectivity test', 'error')
    testResult.value = { success: false, error: error.response?.data?.detail || error.message }
  } finally {
    testLoading.value = false
  }
}

// Lifecycle
onMounted(() => {
  loadStatus()
  loadFailoverConfig()
})
</script>

<style scoped>
.border-success {
  border-color: rgb(var(--v-theme-success)) !important;
}
</style>
