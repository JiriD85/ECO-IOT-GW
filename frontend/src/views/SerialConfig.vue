<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <h1 class="text-h4 mb-4">RS485 Serial Configuration</h1>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Serial Port Settings</v-card-title>
          <v-card-text>
            <v-form ref="form">
              <v-select
                v-model="config.port"
                :items="ports"
                item-title="label"
                item-value="device"
                label="Serial Port"
                required
              ></v-select>

              <v-select
                v-model="config.baudrate"
                :items="baudrates"
                label="Baud Rate"
                required
              ></v-select>

              <v-select
                v-model="config.bytesize"
                :items="[5, 6, 7, 8]"
                label="Data Bits"
              ></v-select>

              <v-select
                v-model="config.parity"
                :items="parityOptions"
                item-title="label"
                item-value="value"
                label="Parity"
              ></v-select>

              <v-select
                v-model="config.stopbits"
                :items="[1, 1.5, 2]"
                label="Stop Bits"
              ></v-select>

              <v-text-field
                v-model.number="config.timeout"
                label="Timeout (seconds)"
                type="number"
                min="0"
                step="0.1"
              ></v-text-field>
            </v-form>
          </v-card-text>
          <v-card-actions>
            <v-btn
              color="secondary"
              @click="testPort"
              :loading="testing"
            >
              Test Connection
            </v-btn>
            <v-spacer></v-spacer>
            <v-btn
              color="primary"
              @click="saveConfig"
              :loading="saving"
            >
              Save Configuration
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Available Ports</v-card-title>
          <v-card-text>
            <v-list v-if="ports.length > 0">
              <v-list-item
                v-for="port in ports"
                :key="port.device"
              >
                <template v-slot:prepend>
                  <v-icon>mdi-serial-port</v-icon>
                </template>
                <v-list-item-title>{{ port.device }}</v-list-item-title>
                <v-list-item-subtitle>{{ port.description || 'No description' }}</v-list-item-subtitle>
              </v-list-item>
            </v-list>
            <div v-else class="text-center text-grey pa-4">
              No serial ports detected
            </div>
          </v-card-text>
          <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn @click="fetchPorts" :loading="loading">
              Refresh
            </v-btn>
          </v-card-actions>
        </v-card>

        <v-card class="mt-4">
          <v-card-title>RS485 Info</v-card-title>
          <v-card-text>
            <v-alert type="info" variant="tonal">
              This configuration is used by the ThingsBoard Gateway Modbus connector.
              Changes will be applied to the gateway configuration.
            </v-alert>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, computed, inject, onMounted } from 'vue'
import { serialApi } from '../services/api'

const showSnackbar = inject('showSnackbar')

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

const ports = ref([])
const config = ref({
  port: '/dev/ttyAMA0',
  baudrate: 9600,
  bytesize: 8,
  parity: 'N',
  stopbits: 1,
  timeout: 1.0
})

const baudrates = [300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200, 230400]

const parityOptions = [
  { label: 'None', value: 'N' },
  { label: 'Even', value: 'E' },
  { label: 'Odd', value: 'O' },
  { label: 'Mark', value: 'M' },
  { label: 'Space', value: 'S' }
]

const fetchPorts = async () => {
  try {
    loading.value = true
    const response = await serialApi.getPorts()
    ports.value = response.data.map(p => ({
      ...p,
      label: `${p.device} - ${p.description || 'Unknown'}`
    }))
  } catch (error) {
    showSnackbar('Failed to fetch ports', 'error')
  } finally {
    loading.value = false
  }
}

const fetchConfig = async () => {
  try {
    const response = await serialApi.getConfig()
    config.value = response.data
  } catch (error) {
    console.error('Failed to fetch config:', error)
  }
}

const saveConfig = async () => {
  try {
    saving.value = true
    await serialApi.setConfig(config.value)
    showSnackbar('Configuration saved')
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Failed to save', 'error')
  } finally {
    saving.value = false
  }
}

const testPort = async () => {
  try {
    testing.value = true
    await serialApi.testPort()
    showSnackbar('Port test successful', 'success')
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Port test failed', 'error')
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  fetchPorts()
  fetchConfig()
})
</script>
