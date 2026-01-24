<template>
  <!-- Error Alert -->
  <v-row v-if="error">
      <v-col cols="12">
        <v-alert type="error" closable @click:close="error = null">
          {{ error }}
        </v-alert>
      </v-col>
    </v-row>

    <v-row>
      <!-- SMS Configuration Card -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>
            SMS Configuration
            <v-spacer></v-spacer>
            <v-chip :color="config.enabled ? 'success' : 'grey'" size="small">
              {{ config.enabled ? 'Enabled' : 'Disabled' }}
            </v-chip>
          </v-card-title>
          <v-card-text>
            <v-switch
              v-model="config.enabled"
              label="Enable SMS Alerts"
              color="primary"
              :disabled="!isAdmin"
              :hint="!isAdmin ? '(Admin only)' : ''"
              persistent-hint
            ></v-switch>

            <v-select
              v-model="config.default_region"
              :items="regionOptions"
              label="Default Region"
              :disabled="!isAdmin"
              class="mt-4"
            ></v-select>
          </v-card-text>
          <v-card-actions>
            <v-btn
              color="primary"
              @click="saveConfig"
              :loading="savingConfig"
              :disabled="!isAdmin || !configChanged"
            >
              <v-icon start>mdi-content-save</v-icon>
              Save Configuration
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Test SMS Card -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Test SMS</v-card-title>
          <v-card-text>
            <v-text-field
              v-model="testPhone"
              label="Phone Number"
              placeholder="+420 777 123 456"
              @blur="validateTestPhone"
              :error-messages="testPhoneError"
            >
              <template v-slot:append>
                <v-chip v-if="testPhoneValid" color="success" size="small">
                  {{ testPhoneE164 }}
                </v-chip>
              </template>
            </v-text-field>

            <v-textarea
              v-model="testMessage"
              label="Message (optional)"
              placeholder="Leave empty for default test message"
              rows="2"
              counter="160"
              :maxlength="160"
              class="mt-2"
            ></v-textarea>

            <div v-if="testResult" class="mt-4">
              <v-alert :type="testResult.success ? 'success' : 'error'" dense>
                {{ testResult.message }}
                <span v-if="testResult.message_reference">
                  (Ref: {{ testResult.message_reference }})
                </span>
              </v-alert>
            </div>
          </v-card-text>
          <v-card-actions>
            <v-btn
              color="primary"
              @click="sendTestSms"
              :loading="sendingTest"
              :disabled="!testPhone || testPhoneError"
            >
              <v-icon start>mdi-send</v-icon>
              Send Test
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <!-- Recipients Card -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>
            SMS Recipients
            <v-spacer></v-spacer>
            <v-btn
              color="primary"
              variant="text"
              @click="showAddDialog = true"
              :disabled="!isAdmin"
            >
              <v-icon start>mdi-plus</v-icon>
              Add Recipient
            </v-btn>
          </v-card-title>
          <v-card-text>
            <v-data-table
              :headers="recipientHeaders"
              :items="config.recipients"
              :loading="loading"
              density="compact"
              class="elevation-1"
            >
              <template v-slot:item.enabled="{ item }">
                <v-chip :color="item.enabled ? 'success' : 'grey'" size="small">
                  {{ item.enabled ? 'Active' : 'Disabled' }}
                </v-chip>
              </template>
              <template v-slot:item.actions="{ item }">
                <v-btn
                  icon="mdi-delete"
                  variant="text"
                  color="error"
                  size="small"
                  @click="confirmDeleteRecipient(item)"
                  :disabled="!isAdmin"
                ></v-btn>
              </template>
              <template v-slot:no-data>
                <div class="text-center py-4 text-grey">
                  No recipients configured. Click "Add Recipient" to add one.
                </div>
              </template>
            </v-data-table>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Triggers Card -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>Alert Triggers</v-card-title>
          <v-card-text>
            <v-row>
              <v-col
                v-for="trigger in availableTriggers"
                :key="trigger.event_type"
                cols="12"
                md="6"
                lg="3"
              >
                <v-card variant="outlined">
                  <v-card-text>
                    <v-switch
                      v-model="triggerStates[trigger.event_type]"
                      :label="trigger.description"
                      color="primary"
                      :disabled="!isAdmin"
                      hide-details
                      @update:model-value="updateTrigger(trigger.event_type, $event)"
                    ></v-switch>
                    <div class="text-caption text-grey mt-1">
                      Cooldown: {{ getCooldown(trigger.event_type) }} min
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Add Recipient Dialog -->
    <v-dialog v-model="showAddDialog" max-width="500">
      <v-card>
        <v-card-title>Add SMS Recipient</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="newRecipient.name"
            label="Name"
            placeholder="John Doe"
            :error-messages="newRecipientErrors.name"
          ></v-text-field>

          <v-text-field
            v-model="newRecipient.phone"
            label="Phone Number"
            placeholder="+420 777 123 456"
            @blur="validateNewPhone"
            :error-messages="newRecipientErrors.phone"
            class="mt-2"
          >
            <template v-slot:append>
              <v-chip v-if="newPhoneValid" color="success" size="small">
                {{ newPhoneE164 }}
              </v-chip>
            </template>
          </v-text-field>

          <v-switch
            v-model="newRecipient.enabled"
            label="Enabled"
            color="primary"
            class="mt-2"
          ></v-switch>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn variant="text" @click="closeAddDialog">Cancel</v-btn>
          <v-btn
            color="primary"
            @click="addRecipient"
            :loading="addingRecipient"
            :disabled="!canAddRecipient"
          >
            Add
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete Confirmation Dialog -->
    <v-dialog v-model="showDeleteDialog" max-width="400">
      <v-card>
        <v-card-title>Delete Recipient</v-card-title>
        <v-card-text>
          Are you sure you want to delete "{{ recipientToDelete?.name }}"?
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn variant="text" @click="showDeleteDialog = false">Cancel</v-btn>
          <v-btn color="error" @click="deleteRecipient" :loading="deletingRecipient">
            Delete
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

  <!-- Snackbar -->
  <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="3000">
    {{ snackbar.text }}
  </v-snackbar>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { smsApi } from '../services/api'
import { useAuthStore } from '../services/auth'

const authStore = useAuthStore()

// State
const loading = ref(false)
const error = ref(null)
const config = reactive({
  enabled: false,
  recipients: [],
  triggers: [],
  default_region: 'CZ'
})
const originalConfig = ref(null)
const availableTriggers = ref([])
const triggerStates = reactive({})

// Test SMS state
const testPhone = ref('')
const testMessage = ref('')
const testPhoneValid = ref(false)
const testPhoneE164 = ref('')
const testPhoneError = ref('')
const testResult = ref(null)
const sendingTest = ref(false)

// Add recipient state
const showAddDialog = ref(false)
const newRecipient = reactive({
  name: '',
  phone: '',
  enabled: true
})
const newRecipientErrors = reactive({
  name: '',
  phone: ''
})
const newPhoneValid = ref(false)
const newPhoneE164 = ref('')
const addingRecipient = ref(false)

// Delete recipient state
const showDeleteDialog = ref(false)
const recipientToDelete = ref(null)
const deletingRecipient = ref(false)

// Config save state
const savingConfig = ref(false)

// Snackbar
const snackbar = reactive({
  show: false,
  text: '',
  color: 'success'
})

// Region options
const regionOptions = [
  { title: 'Czech Republic (+420)', value: 'CZ' },
  { title: 'Germany (+49)', value: 'DE' },
  { title: 'Austria (+43)', value: 'AT' },
  { title: 'Slovakia (+421)', value: 'SK' },
  { title: 'Poland (+48)', value: 'PL' },
  { title: 'United States (+1)', value: 'US' },
  { title: 'United Kingdom (+44)', value: 'GB' }
]

// Table headers
const recipientHeaders = [
  { title: 'Name', key: 'name' },
  { title: 'Phone', key: 'phone' },
  { title: 'Status', key: 'enabled' },
  { title: 'Actions', key: 'actions', sortable: false, align: 'end' }
]

// Computed
const isAdmin = computed(() => authStore.user?.role === 'admin')

const configChanged = computed(() => {
  if (!originalConfig.value) return false
  return JSON.stringify({
    enabled: config.enabled,
    default_region: config.default_region,
    triggers: config.triggers
  }) !== JSON.stringify({
    enabled: originalConfig.value.enabled,
    default_region: originalConfig.value.default_region,
    triggers: originalConfig.value.triggers
  })
})

const canAddRecipient = computed(() => {
  return newRecipient.name.trim() && newPhoneValid.value && !newRecipientErrors.name
})

// Methods
const showMessage = (text, color = 'success') => {
  snackbar.text = text
  snackbar.color = color
  snackbar.show = true
}

const loadConfig = async () => {
  loading.value = true
  error.value = null
  try {
    const res = await smsApi.getConfig()
    Object.assign(config, res.data)
    originalConfig.value = JSON.parse(JSON.stringify(res.data))

    // Initialize trigger states
    availableTriggers.value.forEach(t => {
      const existing = config.triggers.find(ct => ct.event_type === t.event_type)
      triggerStates[t.event_type] = existing?.enabled ?? false
    })
  } catch (err) {
    error.value = 'Failed to load SMS configuration'
    console.error(err)
  } finally {
    loading.value = false
  }
}

const loadTriggers = async () => {
  try {
    const res = await smsApi.getTriggers()
    availableTriggers.value = res.data
  } catch (err) {
    console.error('Failed to load triggers:', err)
  }
}

const saveConfig = async () => {
  savingConfig.value = true
  try {
    // Build triggers array from states
    const triggers = Object.entries(triggerStates)
      .filter(([, enabled]) => enabled)
      .map(([event_type]) => {
        const existing = config.triggers.find(t => t.event_type === event_type)
        return {
          event_type,
          enabled: true,
          cooldown_minutes: existing?.cooldown_minutes ?? 30
        }
      })

    await smsApi.setConfig({
      enabled: config.enabled,
      recipients: config.recipients,
      triggers,
      default_region: config.default_region
    })

    showMessage('SMS configuration saved')
    await loadConfig()
  } catch (err) {
    showMessage(err.response?.data?.detail || 'Failed to save configuration', 'error')
  } finally {
    savingConfig.value = false
  }
}

const validateTestPhone = async () => {
  if (!testPhone.value) {
    testPhoneValid.value = false
    testPhoneE164.value = ''
    testPhoneError.value = ''
    return
  }

  try {
    const res = await smsApi.validateNumber(testPhone.value, config.default_region)
    if (res.data.valid) {
      testPhoneValid.value = true
      testPhoneE164.value = res.data.e164
      testPhoneError.value = ''
    } else {
      testPhoneValid.value = false
      testPhoneE164.value = ''
      testPhoneError.value = res.data.error || 'Invalid phone number'
    }
  } catch (err) {
    testPhoneError.value = 'Failed to validate phone number'
  }
}

const sendTestSms = async () => {
  sendingTest.value = true
  testResult.value = null
  try {
    const res = await smsApi.testSms(testPhone.value, testMessage.value || null)
    testResult.value = res.data
  } catch (err) {
    testResult.value = {
      success: false,
      message: err.response?.data?.detail || 'Failed to send test SMS'
    }
  } finally {
    sendingTest.value = false
  }
}

const validateNewPhone = async () => {
  if (!newRecipient.phone) {
    newPhoneValid.value = false
    newPhoneE164.value = ''
    newRecipientErrors.phone = ''
    return
  }

  try {
    const res = await smsApi.validateNumber(newRecipient.phone, config.default_region)
    if (res.data.valid) {
      newPhoneValid.value = true
      newPhoneE164.value = res.data.e164
      newRecipientErrors.phone = ''
    } else {
      newPhoneValid.value = false
      newPhoneE164.value = ''
      newRecipientErrors.phone = res.data.error || 'Invalid phone number'
    }
  } catch (err) {
    newRecipientErrors.phone = 'Failed to validate phone number'
  }
}

const closeAddDialog = () => {
  showAddDialog.value = false
  newRecipient.name = ''
  newRecipient.phone = ''
  newRecipient.enabled = true
  newRecipientErrors.name = ''
  newRecipientErrors.phone = ''
  newPhoneValid.value = false
  newPhoneE164.value = ''
}

const addRecipient = async () => {
  addingRecipient.value = true
  try {
    await smsApi.addRecipient({
      name: newRecipient.name.trim(),
      phone: newRecipient.phone,
      enabled: newRecipient.enabled
    })
    showMessage(`Recipient "${newRecipient.name}" added`)
    closeAddDialog()
    await loadConfig()
  } catch (err) {
    const detail = err.response?.data?.detail
    if (detail?.includes('already exists')) {
      newRecipientErrors.name = detail
    } else {
      showMessage(detail || 'Failed to add recipient', 'error')
    }
  } finally {
    addingRecipient.value = false
  }
}

const confirmDeleteRecipient = (recipient) => {
  recipientToDelete.value = recipient
  showDeleteDialog.value = true
}

const deleteRecipient = async () => {
  deletingRecipient.value = true
  try {
    await smsApi.removeRecipient(recipientToDelete.value.name)
    showMessage(`Recipient "${recipientToDelete.value.name}" deleted`)
    showDeleteDialog.value = false
    recipientToDelete.value = null
    await loadConfig()
  } catch (err) {
    showMessage(err.response?.data?.detail || 'Failed to delete recipient', 'error')
  } finally {
    deletingRecipient.value = false
  }
}

const updateTrigger = (eventType, enabled) => {
  triggerStates[eventType] = enabled
}

const getCooldown = (eventType) => {
  const trigger = config.triggers.find(t => t.event_type === eventType)
  return trigger?.cooldown_minutes ?? 30
}

// Lifecycle
onMounted(async () => {
  await loadTriggers()
  await loadConfig()
})
</script>
