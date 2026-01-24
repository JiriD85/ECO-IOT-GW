<template>
  <!-- Create Backup Card -->
  <v-row>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Create Backup</v-card-title>
          <v-card-text>
            Create a full system backup including all configuration files.
            The backup will be downloaded as a tar.gz archive.
          </v-card-text>
          <v-card-actions>
            <v-btn
              color="primary"
              :loading="creating"
              @click="createBackup"
            >
              <v-icon start>mdi-download</v-icon>
              Create & Download Backup
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Restore Backup Card -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Restore Backup</v-card-title>
          <v-card-text>
            <v-file-input
              v-model="selectedFile"
              label="Select backup file"
              accept=".tar.gz,.tgz"
              prepend-icon="mdi-file-restore"
              :disabled="restoring || validating"
              show-size
            />

            <!-- Validation result -->
            <v-alert
              v-if="validationResult"
              :type="validationResult.valid ? 'success' : 'error'"
              class="mt-3"
            >
              <div v-if="validationResult.valid">
                <strong>Valid backup</strong>
                <div>Created: {{ formatDate(validationResult.manifest?.created_at) }}</div>
                <div>Hostname: {{ validationResult.manifest?.hostname }}</div>
                <div>Version: {{ validationResult.manifest?.app_version }}</div>
              </div>
              <div v-else>
                {{ validationResult.error }}
              </div>
            </v-alert>
          </v-card-text>
          <v-card-actions>
            <v-btn
              color="secondary"
              :loading="validating"
              :disabled="!selectedFile || restoring"
              @click="validateBackup"
            >
              <v-icon start>mdi-check-circle</v-icon>
              Validate
            </v-btn>
            <v-btn
              color="warning"
              :loading="restoring"
              :disabled="!selectedFile || !validationResult?.valid"
              @click="confirmRestore"
            >
              <v-icon start>mdi-restore</v-icon>
              Restore
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <!-- Restore Confirmation Dialog -->
    <v-dialog v-model="restoreDialog" max-width="500">
      <v-card>
        <v-card-title class="text-h5">Confirm Restore</v-card-title>
        <v-card-text>
          <v-alert type="warning" class="mb-3">
            This will overwrite current system configuration with the backup.
            This action cannot be undone.
          </v-alert>
          Are you sure you want to restore from this backup?
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn text @click="restoreDialog = false">Cancel</v-btn>
          <v-btn color="warning" @click="restoreBackup">Restore</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

  <!-- Snackbar for notifications -->
  <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="4000">
    {{ snackbar.text }}
  </v-snackbar>
</template>

<script setup>
import { ref } from 'vue'
import { backupApi } from '@/services/api'

// State
const creating = ref(false)
const validating = ref(false)
const restoring = ref(false)
const selectedFile = ref(null)
const validationResult = ref(null)
const restoreDialog = ref(false)

const snackbar = ref({
  show: false,
  text: '',
  color: 'success'
})

// Methods
const showSnackbar = (text, color = 'success') => {
  snackbar.value = { show: true, text, color }
}

const formatDate = (dateStr) => {
  if (!dateStr) return 'N/A'
  return new Date(dateStr).toLocaleString()
}

const createBackup = async () => {
  creating.value = true
  try {
    const response = await backupApi.create()

    // Create download link from blob
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url

    // Extract filename from Content-Disposition or generate
    const contentDisposition = response.headers['content-disposition']
    let filename = 'eco-iot-gw-backup.tar.gz'
    if (contentDisposition) {
      const match = contentDisposition.match(/filename=(.+)/)
      if (match) filename = match[1].replace(/"/g, '')
    }

    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)

    showSnackbar('Backup created and downloaded successfully')
  } catch (error) {
    console.error('Backup creation failed:', error)
    showSnackbar(error.response?.data?.detail || 'Failed to create backup', 'error')
  } finally {
    creating.value = false
  }
}

const validateBackup = async () => {
  if (!selectedFile.value) return

  validating.value = true
  validationResult.value = null

  try {
    const response = await backupApi.validate(selectedFile.value)
    validationResult.value = response.data

    if (response.data.valid) {
      showSnackbar('Backup is valid')
    } else {
      showSnackbar(response.data.error || 'Backup validation failed', 'error')
    }
  } catch (error) {
    console.error('Validation failed:', error)
    validationResult.value = { valid: false, error: error.response?.data?.detail || 'Validation failed' }
    showSnackbar('Validation failed', 'error')
  } finally {
    validating.value = false
  }
}

const confirmRestore = () => {
  restoreDialog.value = true
}

const restoreBackup = async () => {
  restoreDialog.value = false
  restoring.value = true

  try {
    const response = await backupApi.restore(selectedFile.value)

    if (response.data.success) {
      showSnackbar('Backup restored successfully')
      // Reset state
      selectedFile.value = null
      validationResult.value = null
    } else {
      showSnackbar(response.data.message || 'Restore failed', 'error')
    }
  } catch (error) {
    console.error('Restore failed:', error)
    showSnackbar(error.response?.data?.detail || 'Failed to restore backup', 'error')
  } finally {
    restoring.value = false
  }
}
</script>
