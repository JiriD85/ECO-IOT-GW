<template>
  <section class="login-card panel">
    <img :src="logoUrl" class="brand-logo" :class="{ 'company-logo': !hasLogo }" alt="ECO Energy Group / kit logo" />
    <p class="eyebrow">{{ kitName }} / LOCAL ACCESS</p><h1>Kit login</h1><p class="muted">Sign in with the kit’s local account.</p>
    <form @submit.prevent="submit">
      <label>Username<input v-model="username" autocomplete="username" required :disabled="loading" /></label>
      <label>Password<input v-model="password" type="password" autocomplete="current-password" required :disabled="loading" /></label>
      <p v-if="error" role="alert" class="error-text">{{ error }}</p>
      <button class="primary-button" :disabled="loading">{{ loading ? 'Signing in…' : 'Sign in →' }}</button>
    </form>
    <small class="muted">Local access</small>
  </section>
</template>
<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../services/auth'
import { useBranding } from '../composables/useBranding'
const { kitName, hasLogo, logoUrl } = useBranding()
const auth = useAuthStore(), router = useRouter(), route = useRoute()
const username = ref(''), password = ref(''), loading = ref(false), error = ref('')
async function submit() {
  loading.value = true; error.value = ''
  try {
    const result = await auth.login(username.value, password.value)
    if (result.success) {
      const path = route.query.redirect
      router.push(typeof path === 'string' && path.startsWith('/') && !path.startsWith('//') ? path : '/dashboard')
    } else error.value = result.error
  } finally { loading.value = false }
}
</script>
