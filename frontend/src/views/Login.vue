<template>
  <v-container fluid class="fill-height">
    <v-row align="center" justify="center">
      <v-col cols="12" sm="8" md="4">
        <v-card class="elevation-12">
          <v-toolbar color="primary" dark flat>
            <v-img v-if="hasLogo" :src="logoUrl" height="32" width="32" class="ml-2 mr-2" />
            <v-toolbar-title v-if="isLoaded">{{ kitName }}</v-toolbar-title>
            <v-progress-circular v-else indeterminate size="20" />
          </v-toolbar>
          <v-card-text>
            <v-form @submit.prevent="handleLogin">
              <v-text-field
                v-model="username"
                label="Username"
                prepend-icon="mdi-account"
                type="text"
                :error-messages="error"
                :disabled="loading"
                required
              ></v-text-field>

              <v-text-field
                v-model="password"
                label="Password"
                prepend-icon="mdi-lock"
                :type="showPassword ? 'text' : 'password'"
                :append-inner-icon="showPassword ? 'mdi-eye' : 'mdi-eye-off'"
                @click:append-inner="showPassword = !showPassword"
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
