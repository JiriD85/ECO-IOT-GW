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
            hint="Used in header and login page (max 32 characters)"
            persistent-hint
            :maxlength="32"
            :disabled="loading || saving"
            counter
          />
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>

  <!-- Branding Assets Section -->
  <v-row>
    <v-col cols="12" md="6">
      <v-card class="h-100">
        <v-card-title>Logo</v-card-title>
        <v-card-text>
          <!-- Logo preview or placeholder -->
          <div class="mb-4 text-center asset-preview">
            <template v-if="hasLogo || logoPreview">
              <v-img
                :src="logoPreview || logoUrl"
                height="64"
                width="64"
                contain
                class="mb-2 mx-auto"
              />
              <v-btn
                v-if="hasLogo && !logoFile"
                color="error"
                size="small"
                @click="confirmDeleteLogo"
                :disabled="loading || saving"
              >
                <v-icon start>mdi-delete</v-icon>
                Delete
              </v-btn>
            </template>
            <template v-else>
              <div class="placeholder-box mx-auto mb-2">
                <v-icon size="32" color="grey-lighten-1">mdi-image-off</v-icon>
              </div>
              <div class="text-caption text-grey">No logo</div>
            </template>
          </div>

          <!-- Logo upload -->
          <v-file-input
            v-model="logoFile"
            label="Upload Logo"
            accept="image/png,image/jpeg,image/svg+xml"
            prepend-icon="mdi-image"
            :disabled="loading || saving"
            show-size
            density="compact"
            @change="onLogoFileChange"
          />

          <v-alert v-if="logoError" type="error" density="compact" class="mt-2">
            {{ logoError }}
          </v-alert>

          <div class="text-caption text-grey">
            PNG, JPG, SVG. Max 1MB
          </div>
        </v-card-text>
      </v-card>
    </v-col>

    <v-col cols="12" md="6">
      <v-card class="h-100">
        <v-card-title>Favicon</v-card-title>
        <v-card-text>
          <!-- Favicon preview or placeholder -->
          <div class="mb-4 text-center asset-preview">
            <template v-if="hasFavicon || faviconPreview">
              <v-img
                :src="faviconPreview || faviconUrl"
                height="64"
                width="64"
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
                Delete
              </v-btn>
            </template>
            <template v-else>
              <div class="placeholder-box mx-auto mb-2">
                <v-icon size="32" color="grey-lighten-1">mdi-web-off</v-icon>
              </div>
              <div class="text-caption text-grey">No favicon</div>
            </template>
          </div>

          <!-- Favicon upload -->
          <v-file-input
            v-model="faviconFile"
            label="Upload Favicon"
            accept="image/x-icon,image/png"
            prepend-icon="mdi-web"
            :disabled="loading || saving"
            show-size
            density="compact"
            @change="onFaviconFileChange"
          />

          <v-alert v-if="faviconError" type="error" density="compact" class="mt-2">
            {{ faviconError }}
          </v-alert>

          <div class="text-caption text-grey">
            ICO, PNG. Max 100KB
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

  <!-- Password Change Section -->
  <v-row class="mt-4">
    <v-col cols="12" md="6">
      <v-card>
        <v-card-title>
          <v-icon start>mdi-lock-reset</v-icon>
          Change Password
        </v-card-title>
        <v-card-text>
          <v-form ref="passwordForm" @submit.prevent="changePassword">
            <v-text-field
              v-model="passwordData.current"
              label="Current Password"
              :type="showCurrentPassword ? 'text' : 'password'"
              :append-inner-icon="showCurrentPassword ? 'mdi-eye' : 'mdi-eye-off'"
              @click:append-inner="showCurrentPassword = !showCurrentPassword"
              :disabled="changingPassword"
              :rules="[v => !!v || 'Required']"
              class="mb-2"
            />
            <v-text-field
              v-model="passwordData.new"
              label="New Password"
              :type="showNewPassword ? 'text' : 'password'"
              :append-inner-icon="showNewPassword ? 'mdi-eye' : 'mdi-eye-off'"
              @click:append-inner="showNewPassword = !showNewPassword"
              :disabled="changingPassword"
              :rules="passwordRules"
              class="mb-2"
            />
            <v-text-field
              v-model="passwordData.confirm"
              label="Confirm New Password"
              :type="showNewPassword ? 'text' : 'password'"
              :disabled="changingPassword"
              :rules="[v => v === passwordData.new || 'Passwords do not match']"
            />
          </v-form>
        </v-card-text>
        <v-card-actions>
          <v-btn
            color="primary"
            :loading="changingPassword"
            :disabled="!canChangePassword"
            @click="changePassword"
          >
            <v-icon start>mdi-lock-check</v-icon>
            Change Password
          </v-btn>
        </v-card-actions>
      </v-card>
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
import { brandingApi, authApi } from '@/services/api'
import { useAuthStore } from '@/services/auth'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

// State
const loading = ref(false)
const saving = ref(false)
const changingPassword = ref(false)

// Password change state
const passwordForm = ref(null)
const passwordData = ref({
  current: '',
  new: '',
  confirm: ''
})
const showCurrentPassword = ref(false)
const showNewPassword = ref(false)

const passwordRules = [
  v => !!v || 'Required',
  v => v.length >= 8 || 'Minimum 8 characters'
]

const canChangePassword = computed(() => {
  return passwordData.value.current &&
         passwordData.value.new &&
         passwordData.value.new.length >= 8 &&
         passwordData.value.new === passwordData.value.confirm
})
const kitName = ref('ECO-IOT-GW')
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
        kit_name: kitName.value
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

const changePassword = async () => {
  if (!canChangePassword.value) return

  changingPassword.value = true
  try {
    await authApi.changePassword(passwordData.value.current, passwordData.value.new)
    showSnackbar('Password changed successfully')
    // Clear form
    passwordData.value = { current: '', new: '', confirm: '' }
  } catch (error) {
    console.error('Failed to change password:', error)
    showSnackbar(error.response?.data?.detail || 'Failed to change password', 'error')
  } finally {
    changingPassword.value = false
  }
}

// Lifecycle
onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.placeholder-box {
  width: 64px;
  height: 64px;
  border: 2px dashed #e0e0e0;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #fafafa;
}

.asset-preview {
  min-height: 100px;
}

.h-100 {
  height: 100%;
}
</style>
