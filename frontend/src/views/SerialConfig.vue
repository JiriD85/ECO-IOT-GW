<template>
  <v-card>
    <v-card-title>Serial ports</v-card-title>
    <v-card-text>
      <v-list v-if="ports.length">
        <v-list-item v-for="port in ports" :key="port.device" :title="port.device" :subtitle="port.description" />
      </v-list>
      <p v-else>No serial ports detected.</p>
      <p class="mt-4">Bus settings are managed by the ThingsBoard connector.</p>
    </v-card-text>
    <v-card-actions>
      <v-btn to="/connector">Connector settings</v-btn>
      <v-spacer />
      <v-btn @click="fetchPorts" :loading="loading">Refresh</v-btn>
    </v-card-actions>
  </v-card>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import api from '../services/api'
import { useSnackbar } from '../composables/useSnackbar'
const { showSnackbar } = useSnackbar()
const ports = ref([])
const loading = ref(false)
async function fetchPorts() {
  loading.value = true
  try {
    ports.value = (await api.get('/api/serial/ports', { params: { force_refresh: true } })).data
  } catch (error) {
    showSnackbar(error.response?.data?.detail || 'Could not read serial ports', 'error')
  } finally { loading.value = false }
}
onMounted(fetchPorts)
</script>
