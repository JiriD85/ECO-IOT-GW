<template>
  <!-- Filters -->
  <v-row>
      <v-col cols="12">
        <v-card>
          <v-card-text>
            <v-row>
              <v-col cols="12" md="3">
                <v-text-field
                  v-model="filters.username"
                  label="Username"
                  clearable
                  hide-details
                ></v-text-field>
              </v-col>
              <v-col cols="12" md="3">
                <v-select
                  v-model="filters.action"
                  :items="actionTypes"
                  label="Action"
                  clearable
                  hide-details
                ></v-select>
              </v-col>
              <v-col cols="12" md="3">
                <v-select
                  v-model="filters.resource"
                  :items="resourceTypes"
                  label="Resource"
                  clearable
                  hide-details
                ></v-select>
              </v-col>
              <v-col cols="12" md="3">
                <v-btn
                  color="primary"
                  @click="fetchLogs"
                  :loading="loading"
                  block
                >
                  Search
                </v-btn>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Stats -->
    <v-row class="mt-4">
      <v-col cols="12" md="3">
        <v-card>
          <v-card-text class="text-center">
            <div class="text-h4">{{ stats?.total_events || 0 }}</div>
            <div class="text-caption">Total Events (7 days)</div>
          </v-card-text>
        </v-card>
      </v-col>
      <v-col cols="12" md="3">
        <v-card>
          <v-card-text class="text-center">
            <div class="text-h4 text-error">{{ stats?.failed_events || 0 }}</div>
            <div class="text-caption">Failed Events</div>
          </v-card-text>
        </v-card>
      </v-col>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-text>
            <div class="text-caption mb-2">Top Actions</div>
            <v-chip
              v-for="(count, action) in topActions"
              :key="action"
              class="ma-1"
              size="small"
            >
              {{ action }}: {{ count }}
            </v-chip>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Logs Table -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>Audit Entries</v-card-title>
          <v-card-text>
            <v-data-table
              :headers="tableHeaders"
              :items="logs"
              :loading="loading"
              :items-per-page="25"
            >
              <template v-slot:item.timestamp="{ item }">
                {{ formatDate(item.timestamp) }}
              </template>
              <template v-slot:item.success="{ item }">
                <v-icon :color="item.success ? 'success' : 'error'" size="small">
                  {{ item.success ? 'mdi-check' : 'mdi-close' }}
                </v-icon>
              </template>
              <template v-slot:item.details="{ item }">
                <v-btn
                  v-if="item.details"
                  icon="mdi-information"
                  size="x-small"
                  variant="text"
                  @click="showDetails(item)"
                ></v-btn>
              </template>
            </v-data-table>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Details Dialog -->
    <v-dialog v-model="detailsDialog" max-width="500">
      <v-card>
        <v-card-title>Event Details</v-card-title>
        <v-card-text>
          <pre class="details-content">{{ JSON.stringify(selectedDetails, null, 2) }}</pre>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn @click="detailsDialog = false">Close</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { auditApi } from '../services/api'

const loading = ref(false)
const logs = ref([])
const stats = ref(null)

const filters = ref({
  username: null,
  action: null,
  resource: null
})

const detailsDialog = ref(false)
const selectedDetails = ref(null)

const actionTypes = [
  'login', 'logout', 'change_password',
  'upload_compose', 'compose_up', 'compose_down',
  'vpn_connect', 'vpn_disconnect', 'upload_vpn_config',
  'modem_connect', 'modem_disconnect', 'modem_reset',
  'set_serial_config',
  'system_reboot', 'system_shutdown', 'system_update'
]

const resourceTypes = [
  'auth', 'docker', 'vpn', 'modem', 'serial', 'system', 'watchdog'
]

const tableHeaders = [
  { title: 'Timestamp', key: 'timestamp', width: '180px' },
  { title: 'User', key: 'username', width: '100px' },
  { title: 'Action', key: 'action', width: '150px' },
  { title: 'Resource', key: 'resource', width: '100px' },
  { title: 'IP Address', key: 'ip_address', width: '130px' },
  { title: 'Status', key: 'success', width: '80px' },
  { title: '', key: 'details', width: '50px', sortable: false }
]

const topActions = computed(() => {
  const actions = stats.value?.by_action || {}
  return Object.fromEntries(
    Object.entries(actions).slice(0, 5)
  )
})

const formatDate = (dateStr) => {
  return new Date(dateStr).toLocaleString()
}

const fetchLogs = async () => {
  try {
    loading.value = true
    const params = {}
    if (filters.value.username) params.username = filters.value.username
    if (filters.value.action) params.action = filters.value.action
    if (filters.value.resource) params.resource = filters.value.resource

    const response = await auditApi.getLogs(params)
    logs.value = response.data
  } catch (error) {
    console.error('Failed to fetch audit logs:', error)
  } finally {
    loading.value = false
  }
}

const fetchStats = async () => {
  try {
    const response = await auditApi.getStats()
    stats.value = response.data
  } catch (error) {
    console.error('Failed to fetch audit stats:', error)
  }
}

const showDetails = (item) => {
  selectedDetails.value = item.details
  detailsDialog.value = true
}

onMounted(() => {
  fetchLogs()
  fetchStats()
})
</script>

<style scoped>
.details-content {
  background: #1E1E1E;
  padding: 16px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 12px;
}
</style>
