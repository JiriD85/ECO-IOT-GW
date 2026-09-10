<template>
  <v-row>
      <!-- System Info -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>System Information</v-card-title>
          <v-card-text>
            <v-list density="compact">
              <v-list-item>
                <v-list-item-title>Hostname</v-list-item-title>
                <template v-slot:append>{{ systemStatus?.hostname || '--' }}</template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Uptime</v-list-item-title>
                <template v-slot:append>{{ formatUptime(systemStatus?.uptime) }}</template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>CPU Usage</v-list-item-title>
                <template v-slot:append>{{ systemStatus?.cpu_percent?.toFixed(1) || '--' }}%</template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Memory Usage</v-list-item-title>
                <template v-slot:append>{{ systemStatus?.memory_percent?.toFixed(1) || '--' }}%</template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Disk Usage</v-list-item-title>
                <template v-slot:append>{{ systemStatus?.disk_percent?.toFixed(1) || '--' }}%</template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Temperature</v-list-item-title>
                <template v-slot:append>{{ systemStatus?.temperature?.toFixed(1) || '--' }}°C</template>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>
      </v-col>

      <!-- Watchdog -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Watchdog Status</v-card-title>
          <v-card-text>
            <v-switch
              v-model="watchdogEnabled"
              label="Watchdog Enabled"
              @update:model-value="toggleWatchdog"
            ></v-switch>

            <v-list v-if="watchdogStatus?.services" density="compact">
              <v-list-item
                v-for="service in watchdogStatus.services"
                :key="service.name"
              >
                <template v-slot:prepend>
                  <v-icon :color="service.running ? 'success' : 'error'">
                    {{ service.running ? 'mdi-check-circle' : 'mdi-alert-circle' }}
                  </v-icon>
                </template>
                <v-list-item-title>{{ service.name }}</v-list-item-title>
                <template v-slot:append>
                  <v-chip
                    v-if="service.failures > 0"
                    color="warning"
                    size="x-small"
                    class="mr-2"
                  >
                    {{ service.failures }} failures
                  </v-chip>
                  <v-chip
                    :color="service.running ? 'success' : 'error'"
                    size="small"
                  >
                    {{ service.running ? 'Running' : 'Stopped' }}
                  </v-chip>
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- System Actions -->
    <v-row class="mt-4">
      <!-- System Actions -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>System Actions</v-card-title>
          <v-card-text>
            <v-alert type="warning" variant="tonal" class="mb-4">
              These actions will affect system availability.
            </v-alert>
          </v-card-text>
          <v-card-actions>
            <v-btn
              color="warning"
              @click="confirmReboot"
            >
              <v-icon left>mdi-restart</v-icon>
              Reboot
            </v-btn>
            <v-spacer></v-spacer>
            <v-btn
              color="error"
              @click="confirmShutdown"
            >
              <v-icon left>mdi-power</v-icon>
              Shutdown
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <!-- Confirm Dialog -->
    <v-dialog v-model="confirmDialog" max-width="400">
      <v-card>
        <v-card-title>{{ confirmTitle }}</v-card-title>
        <v-card-text>{{ confirmMessage }}</v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn @click="confirmDialog = false">Cancel</v-btn>
          <v-btn
            :color="confirmColor"
            @click="executeConfirmedAction"
            :loading="actionLoading === 'confirm'"
          >
            Confirm
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
</template>

<script setup>
import { ref, inject, onMounted } from 'vue'
import { systemApi, watchdogApi } from '../services/api'

const showSnackbar = inject('showSnackbar')

const systemStatus = ref(null)
const watchdogStatus = ref(null)
const watchdogEnabled = ref(false)
const actionLoading = ref(null)

const confirmDialog = ref(false)
const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmColor = ref('primary')
const confirmAction = ref(null)

const formatUptime = (seconds) => {
  if (!seconds) return '--'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${days}d ${hours}h ${mins}m`
}

const fetchData = async () => {
  try {
    const [sysRes, wdRes] = await Promise.all([
      systemApi.getStatus(),
      watchdogApi.getStatus()
    ])
    systemStatus.value = sysRes.data
    watchdogStatus.value = wdRes.data
    watchdogEnabled.value = wdRes.data.enabled
  } catch (error) {
    console.error('Failed to fetch system data:', error)
  }
}

const toggleWatchdog = async (enabled) => {
  try {
    if (enabled) {
      await watchdogApi.enable()
    } else {
      await watchdogApi.disable()
    }
    showSnackbar(`Watchdog ${enabled ? 'enabled' : 'disabled'}`)
  } catch (error) {
    showSnackbar('Failed to update watchdog', 'error')
    watchdogEnabled.value = !enabled
  }
}

const confirmReboot = () => {
  confirmTitle.value = 'Confirm Reboot'
  confirmMessage.value = 'Are you sure you want to reboot the system?'
  confirmColor.value = 'warning'
  confirmAction.value = 'reboot'
  confirmDialog.value = true
}

const confirmShutdown = () => {
  confirmTitle.value = 'Confirm Shutdown'
  confirmMessage.value = 'Are you sure you want to shutdown the system? Physical access will be required to restart.'
  confirmColor.value = 'error'
  confirmAction.value = 'shutdown'
  confirmDialog.value = true
}

const executeConfirmedAction = async () => {
  try {
    actionLoading.value = 'confirm'

    if (confirmAction.value === 'reboot') {
      await systemApi.reboot()
      showSnackbar('System is rebooting...')
    } else if (confirmAction.value === 'shutdown') {
      await systemApi.shutdown()
      showSnackbar('System is shutting down...')
    }

    confirmDialog.value = false
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Action failed', 'error')
  } finally {
    actionLoading.value = null
  }
}

onMounted(fetchData)
</script>
