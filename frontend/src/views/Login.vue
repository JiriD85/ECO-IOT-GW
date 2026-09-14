<template>
  <section class="login-card panel">
    <img :src="logoUrl" class="brand-logo" :class="{ 'company-logo': !hasLogo }" alt="ECO Energy Group / kit logo" />
    <p class="eyebrow">{{ kitName }} / LOCAL ACCESS</p><h1>Kit login</h1><p class="muted">Sign in with the kit’s local account.</p>
    <form class="login-form" method="post" @submit.prevent="submit">
      <label for="login-username">Username</label>
      <input id="login-username" v-model="username" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required :disabled="loading" />
      <label for="login-password">Password</label>
      <div class="password-field">
        <input id="login-password" v-model="password" name="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" required :disabled="loading" />
        <button type="button" class="password-toggle" :aria-label="showPassword ? 'Hide password' : 'Show password'" :aria-pressed="showPassword" @click="showPassword = !showPassword">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.7"/><path v-if="showPassword" d="m4 4 16 16"/></svg>
        </button>
      </div>
      <p v-if="error" role="alert" class="error-text">{{ error }}</p>
      <button type="submit" class="primary-button login-submit" :disabled="loading">{{ loading ? 'Signing in…' : 'Sign in' }}</button>
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
const username = ref('ecoadmin'), password = ref(''), showPassword = ref(false), loading = ref(false), error = ref('')
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
