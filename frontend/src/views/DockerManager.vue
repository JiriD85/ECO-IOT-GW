<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <h1 class="text-h4 mb-4">Containers</h1><v-btn variant="tonal" prepend-icon="mdi-refresh" @click="fetchData">Refresh status</v-btn>
      </v-col>
    </v-row>

    <!-- Upload Card -->
    <v-row>
      <v-col cols="12">
        <v-card>
          <v-card-title>Docker Compose Configuration</v-card-title>
          <v-card-text>
            <!-- Drop Zone -->
            <div
              class="drop-zone pa-8 text-center mb-4"
              :class="{ 'drop-zone-active': isDragging }"
              @dragover.prevent="isDragging = true"
              @dragleave="isDragging = false"
              @drop.prevent="handleDrop"
            >
              <v-icon size="48" class="mb-2">mdi-cloud-upload</v-icon>
              <div class="text-h6">Drop docker-compose.yml here</div>
              <div class="text-caption">or click to select file</div>
              <input
                type="file"
                ref="fileInput"
                accept=".yml,.yaml"
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

            <!-- Current Config -->
            <div v-if="composeContent" class="mt-4">
              <div class="d-flex align-center mb-2">
                <span class="text-subtitle-1">Current Configuration</span>
                <v-spacer></v-spacer>
                <v-btn
                  size="small"
                  variant="text"
                  color="error"
                  @click="deleteCompose"
                >
                  Delete
                </v-btn>
              </div>
              <v-textarea
                v-model="composeContent"
                rows="10"
                variant="outlined"
                readonly
                class="compose-editor"
              ></v-textarea>
            </div>
          </v-card-text>
          <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn
              color="error"
              :disabled="!composeRunning"
              :loading="actionLoading === 'down'"
              @click="composeDown"
            >
              <v-icon left>mdi-stop</v-icon>
              Stop
            </v-btn>
            <v-btn
              color="success"
              :disabled="!composeContent"
              :loading="actionLoading === 'up'"
              @click="composeUp"
            >
              <v-icon left>mdi-play</v-icon>
              Start
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <!-- Containers -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>Containers</v-card-title>
          <v-card-text>
            <v-data-table
              :headers="tableHeaders"
              :items="containers"
              :loading="loading"
              class="elevation-1"
            >
              <template v-slot:item.status="{ item }">
                <v-chip
                  :color="item.status === 'running' ? 'success' : 'error'"
                  size="small"
                >
                  {{ item.status }}
                </v-chip>
              </template>
              <template v-slot:item.actions="{ item }">
                <v-btn
                  v-if="item.status !== 'running'"
                  icon="mdi-play"
                  size="small"
                  variant="text"
                  color="success"
                  @click="startContainer(item.name)"
                ></v-btn>
                <v-btn
                  v-else
                  icon="mdi-stop"
                  size="small"
                  variant="text"
                  color="error"
                  @click="stopContainer(item.name)"
                ></v-btn>
                <v-btn
                  icon="mdi-restart"
                  size="small"
                  variant="text"
                  @click="restartContainer(item.name)"
                ></v-btn>
                <v-btn
                  icon="mdi-text-box"
                  size="small"
                  variant="text"
                  @click="showLogs(item.name)"
                ></v-btn>
              </template>
            </v-data-table>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Logs Dialog -->
    <v-dialog v-model="logsDialog" max-width="800">
      <v-card>
        <v-card-title>
          Logs: {{ selectedContainer }}
          <v-spacer></v-spacer>
          <v-btn icon @click="logsDialog = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </v-card-title>
        <v-card-text>
          <pre class="logs-output">{{ containerLogs }}</pre>
        </v-card-text>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup>
import { ref, inject, onMounted, onUnmounted } from 'vue'
import { dockerApi } from '../services/api'

const showSnackbar = inject('showSnackbar')

const loading = ref(false)
const actionLoading = ref(null)
const isDragging = ref(false)
const composeContent = ref('')
const composeRunning = ref(false)
const containers = ref([])
const logsDialog = ref(false)
const selectedContainer = ref('')
const containerLogs = ref('')



const tableHeaders = [
  { title: 'Name', key: 'name' },
  { title: 'Image', key: 'image' },
  { title: 'Status', key: 'status' },
  { title: 'Actions', key: 'actions', sortable: false }
]

const fetchData = async () => {
  try {
    loading.value = true
    const [composeRes, statusRes] = await Promise.all([
      dockerApi.getCompose().catch(() => null),
      dockerApi.getStatus()
    ])

    if (composeRes?.data) {
      composeContent.value = composeRes.data.content
    }

    containers.value = statusRes.data.containers || []
    composeRunning.value = statusRes.data.compose_running
  } catch (error) {
    console.error('Failed to fetch docker data:', error)
  } finally {
    loading.value = false
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
    loading.value = true
    await dockerApi.uploadComposeFile(file)
    showSnackbar('Docker compose uploaded successfully')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Upload failed', 'error')
  } finally {
    loading.value = false
  }
}

const deleteCompose = async () => {
  try {
    await dockerApi.deleteCompose()
    composeContent.value = ''
    showSnackbar('Configuration deleted')
    await fetchData()
  } catch (error) {
    showSnackbar('Failed to delete configuration', 'error')
  }
}

const composeUp = async () => {
  try {
    actionLoading.value = 'up'
    await dockerApi.composeUp()
    showSnackbar('Containers started')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to start', 'error')
  } finally {
    actionLoading.value = null
  }
}

const composeDown = async () => {
  try {
    actionLoading.value = 'down'
    await dockerApi.composeDown()
    showSnackbar('Containers stopped')
    await fetchData()
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to stop', 'error')
  } finally {
    actionLoading.value = null
  }
}

const startContainer = async (name) => {
  try {
    await dockerApi.startContainer(name)
    showSnackbar(`Container ${name} started`)
    await fetchData()
  } catch (error) {
    showSnackbar('Failed to start container', 'error')
  }
}

const stopContainer = async (name) => {
  try {
    await dockerApi.stopContainer(name)
    showSnackbar(`Container ${name} stopped`)
    await fetchData()
  } catch (error) {
    showSnackbar('Failed to stop container', 'error')
  }
}

const restartContainer = async (name) => {
  try {
    await dockerApi.restartContainer(name)
    showSnackbar(`Container ${name} restarted`)
    await fetchData()
  } catch (error) {
    showSnackbar('Failed to restart container', 'error')
  }
}

const showLogs = async (name) => {
  try {
    selectedContainer.value = name
    const response = await dockerApi.getLogs(name)
    containerLogs.value = response.data.logs
    logsDialog.value = true
  } catch (error) {
    showSnackbar('Failed to fetch logs', 'error')
  }
}

onMounted(() => {
  fetchData()

})


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

.compose-editor {
  font-family: monospace;
  font-size: 12px;
}

.logs-output {
  background: #1E1E1E;
  padding: 16px;
  border-radius: 4px;
  overflow-x: auto;
  max-height: 400px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
