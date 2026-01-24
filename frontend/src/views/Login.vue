<template>
  <v-container fluid class="fill-height">
    <v-row align="center" justify="center">
      <v-col cols="12" sm="8" md="4">
        <v-card class="elevation-12">
          <!-- Logo above toolbar if configured -->
          <div v-if="hasLogo" class="d-flex justify-center pa-4" style="background: rgba(255,255,255,0.05);">
            <v-img :src="logoUrl" max-height="60" max-width="180" contain />
          </div>
          <v-toolbar color="primary" dark flat>
            <v-toolbar-title class="d-flex align-center justify-center w-100">
              <v-icon class="mr-2">mdi-access-point-network</v-icon>
              <span v-if="isLoaded">{{ kitName }}</span>
              <v-progress-circular v-else indeterminate size="20" />
            </v-toolbar-title>
          </v-toolbar>
          <v-card-text class="pa-6">
            <v-form @submit.prevent="handleLogin">
              <v-text-field
                v-model="username"
                label="Username"
                prepend-icon="mdi-account"
                type="text"
                density="default"
                variant="underlined"
                :error-messages="error"
                :disabled="loading"
                required
                class="mb-4"
              ></v-text-field>

              <v-text-field
                v-model="password"
                label="Password"
                prepend-icon="mdi-lock"
                :type="showPassword ? 'text' : 'password'"
                :append-inner-icon="showPassword ? 'mdi-eye' : 'mdi-eye-off'"
                @click:append-inner="showPassword = !showPassword"
                density="default"
                variant="underlined"
                :disabled="loading"
                required
              ></v-text-field>
            </v-form>
          </v-card-text>
          <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn
              color="primary"
              :loading="loading"
              @click="handleLogin"
              block
            >
              Login
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../services/auth'
import { useBranding } from '../composables/useBranding'

const router = useRouter()
const authStore = useAuthStore()
const { kitName, logoUrl, hasLogo, loadBranding, isLoaded } = useBranding()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const loading = ref(false)
const error = ref('')

onMounted(() => {
  loadBranding()
})

const handleLogin = async () => {
  if (!username.value || !password.value) {
    error.value = 'Please enter username and password'
    return
  }

  loading.value = true
  error.value = ''

  const result = await authStore.login(username.value, password.value)

  loading.value = false

  if (result.success) {
    router.push('/dashboard')
  } else {
    error.value = result.error
  }
}
</script>
