<template>
  <!-- Kit Identification Section -->
  <v-row>
    <v-col cols="12">
      <v-card>
        <v-card-title>Kit Identification</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="kitName"
            label="Kit Name"
            hint="Used in header, login page, and WiFi SSID (max 32 characters)"
            persistent-hint
            :maxlength="32"
            :disabled="loading || saving"
            counter
          />

          <v-checkbox
            v-model="updateWifiSsid"
            label="Also update WiFi Access Point SSID"
            hint="When checked, WiFi SSID will be updated to match kit name"
            persistent-hint
            :disabled="loading || saving"
            class="mt-4"
          />
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>

  <!-- Branding Assets Section -->
  <v-row>
    <v-col cols="12" md="6">
      <v-card>
        <v-card-title>Logo</v-card-title>
        <v-card-text>
          <!-- Logo preview -->
          <div v-if="hasLogo || logoPreview" class="mb-4 text-center">
            <v-img
              :src="logoPreview || logoUrl"
              max-height="200"
              contain
              class="mb-2"
            />
            <v-btn
              v-if="hasLogo && !logoFile"
              color="error"
              size="small"
              @click="confirmDeleteLogo"
              :disabled="loading || saving"
            >
              <v-icon start>mdi-delete</v-icon>
              Delete Logo
            </v-btn>
          </div>

          <!-- Logo upload -->
          <v-file-input
            v-model="logoFile"
            label="Upload Logo"
            accept="image/png,image/jpeg,image/svg+xml"
            prepend-icon="mdi-image"
            :disabled="loading || saving"
            show-size
            @change="onLogoFileChange"
          />

          <v-alert v-if="logoError" type="error" class="mt-2">
            {{ logoError }}
          </v-alert>

          <div class="text-caption text-grey mt-2">
            Accepted formats: PNG, JPG, SVG. Max size: 1MB
          </div>
        </v-card-text>
      </v-card>
    </v-col>

    <v-col cols="12" md="6">
      <v-card>
        <v-card-title>Favicon</v-card-title>
        <v-card-text>
          <!-- Favicon preview -->
          <div v-if="hasFavicon || faviconPreview" class="mb-4 text-center">
            <v-img
              :src="faviconPreview || faviconUrl"
              max-height="64"
              max-width="64"
              contain
              class="mb-2 mx-auto"
            />
            <v-btn
              v-if="hasFavicon && !faviconFile"
              color="error"
              size="small"
              @click="confirmDeleteFavicon"
              :disabled="loading || saving"
            >
              <v-icon start>mdi-delete</v-icon>
              Delete Favicon
            </v-btn>
          </div>

          <!-- Favicon upload -->
          <v-file-input
            v-model="faviconFile"
            label="Upload Favicon"
            accept="image/x-icon,image/png"
            prepend-icon="mdi-web"
            :disabled="loading || saving"
            show-size
            @change="onFaviconFileChange"
          />

          <v-alert v-if="faviconError" type="error" class="mt-2">
            {{ faviconError }}
          </v-alert>

          <div class="text-caption text-grey mt-2">
            Accepted formats: ICO, PNG. Max size: 100KB
          </div>
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>

  <!-- Save Button -->
  <v-row>
    <v-col cols="12">
      <v-btn
        color="primary"
        size="large"
        :loading="saving"
        :disabled="loading || !hasChanges || !isAdmin"
        @click="saveConfig"
      >
        <v-icon start>mdi-content-save</v-icon>
        Save Configuration
      </v-btn>
      <span v-if="!isAdmin" class="ml-4 text-caption text-grey">
        Admin role required to save changes
      </span>
    </v-col>
  </v-row>

  <!-- Delete Confirmation Dialog -->
  <v-dialog v-model="deleteDialog.show" max-width="400">
    <v-card>
      <v-card-title class="text-h5">Confirm Delete</v-card-title>
      <v-card-text>
        Are you sure you want to delete the {{ deleteDialog.type }}?
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn text @click="deleteDialog.show = false">Cancel</v-btn>
        <v-btn color="error" @click="executeDelete">Delete</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- Snackbar for notifications -->
  <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="4000">
    {{ snackbar.text }}
  </v-snackbar>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { brandingApi } from '@/services/api'
import { useAuthStore } from '@/services/auth'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

// State
const loading = ref(false)
const saving = ref(false)
const kitName = ref('ECO-IOT-GW')
const updateWifiSsid = ref(false)
const originalKitName = ref('ECO-IOT-GW')
const hasLogo = ref(false)
const hasFavicon = ref(false)
const logoFile = ref(null)
const faviconFile = ref(null)
const logoPreview = ref(null)
const faviconPreview = ref(null)
const logoError = ref(null)
const faviconError = ref(null)

const deleteDialog = ref({
  show: false,
  type: null
})

const snackbar = ref({
  show: false,
  text: '',
  color: 'success'
})

// Computed
const logoUrl = computed(() => {
  return hasLogo.value ? `${brandingApi.getLogoUrl()}?t=${Date.now()}` : null
})

const faviconUrl = computed(() => {
  return hasFavicon.value ? `${brandingApi.getFaviconUrl()}?t=${Date.now()}` : null
})

const hasChanges = computed(() => {
  return kitName.value !== originalKitName.value ||
         logoFile.value !== null ||
         faviconFile.value !== null
})

// Methods
const showSnackbar = (text, color = 'success') => {
  snackbar.value = { show: true, text, color }
}

const validateLogoFile = (file) => {
  logoError.value = null

  if (!file) return true

  // Check file size (1MB max)
  if (file.size > 1024 * 1024) {
    logoError.value = 'File size exceeds 1MB'
    return false
  }

  // Check file type
  const validTypes = ['image/png', 'image/jpeg', 'image/svg+xml']
  if (!validTypes.includes(file.type)) {
    logoError.value = 'Invalid file type. Use PNG, JPG, or SVG'
    return false
  }

  return true
}

const validateFaviconFile = (file) => {
  faviconError.value = null

  if (!file) return true

  // Check file size (100KB max)
  if (file.size > 100 * 1024) {
    faviconError.value = 'File size exceeds 100KB'
    return false
  }

  // Check file type
  const validTypes = ['image/x-icon', 'image/png']
  if (!validTypes.includes(file.type)) {
    faviconError.value = 'Invalid file type. Use ICO or PNG'
    return false
  }

  return true
}

const onLogoFileChange = () => {
  if (logoFile.value && validateLogoFile(logoFile.value)) {
    // Create preview
    const reader = new FileReader()
    reader.onload = (e) => {
      logoPreview.value = e.target.result
    }
    reader.readAsDataURL(logoFile.value)
  } else {
    logoPreview.value = null
  }
}

const onFaviconFileChange = () => {
  if (faviconFile.value && validateFaviconFile(faviconFile.value)) {
    // Create preview
    const reader = new FileReader()
    reader.onload = (e) => {
      faviconPreview.value = e.target.result
    }
    reader.readAsDataURL(faviconFile.value)
  } else {
    faviconPreview.value = null
  }
}

const loadConfig = async () => {
  loading.value = true
  try {
    const response = await brandingApi.getConfig()
    kitName.value = response.data.kit_name || 'ECO-IOT-GW'
    originalKitName.value = kitName.value
    hasLogo.value = response.data.has_logo || false
    hasFavicon.value = response.data.has_favicon || false
  } catch (error) {
    console.error('Failed to load branding config:', error)
    showSnackbar('Failed to load configuration', 'error')
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  if (!isAdmin.value) {
    showSnackbar('Admin role required', 'error')
    return
  }

  saving.value = true
  try {
    // Update kit name if changed
    if (kitName.value !== originalKitName.value) {
      await brandingApi.updateConfig({
        kit_name: kitName.value,
        update_wifi_ssid: updateWifiSsid.value
      })
      originalKitName.value = kitName.value
    }

    // Upload logo if selected
    if (logoFile.value) {
      if (!validateLogoFile(logoFile.value)) {
        saving.value = false
        return
      }
      await brandingApi.uploadLogo(logoFile.value)
      hasLogo.value = true
      logoFile.value = null
      logoPreview.value = null
    }

    // Upload favicon if selected
    if (faviconFile.value) {
      if (!validateFaviconFile(faviconFile.value)) {
        saving.value = false
        return
      }
      await brandingApi.uploadFavicon(faviconFile.value)
      hasFavicon.value = true
      faviconFile.value = null
      faviconPreview.value = null
    }

    showSnackbar('Configuration saved successfully')

    // Reload config to get updated state
    await loadConfig()
  } catch (error) {
    console.error('Failed to save configuration:', error)
    showSnackbar(error.response?.data?.detail || 'Failed to save configuration', 'error')
  } finally {
    saving.value = false
  }
}

const confirmDeleteLogo = () => {
  deleteDialog.value = {
    show: true,
    type: 'logo'
  }
}

const confirmDeleteFavicon = () => {
  deleteDialog.value = {
    show: true,
    type: 'favicon'
  }
}

const executeDelete = async () => {
  const type = deleteDialog.value.type
  deleteDialog.value.show = false

  saving.value = true
  try {
    if (type === 'logo') {
      await brandingApi.deleteLogo()
      hasLogo.value = false
      logoPreview.value = null
      showSnackbar('Logo deleted successfully')
    } else if (type === 'favicon') {
      await brandingApi.deleteFavicon()
      hasFavicon.value = false
      faviconPreview.value = null
      showSnackbar('Favicon deleted successfully')
    }
  } catch (error) {
    console.error(`Failed to delete ${type}:`, error)
    showSnackbar(error.response?.data?.detail || `Failed to delete ${type}`, 'error')
  } finally {
    saving.value = false
  }
}

// Lifecycle
onMounted(() => {
  loadConfig()
})
</script>
