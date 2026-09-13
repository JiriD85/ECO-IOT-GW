<template>
  <div class="console" :class="{ 'login-shell': route.name === 'Login' }">
    <a class="skip-link" href="#content">Skip to content</a>
    <aside v-if="route.name !== 'Login'" class="sidebar">
      <RouterLink class="brand" to="/dashboard"><img :src="logoUrl" class="brand-logo" :class="{ 'company-logo': !hasLogo }" alt="ECO Energy Group / kit logo" /><span>{{ kitName }}<small>KIT CONTROL</small></span></RouterLink>
      <nav aria-label="Main navigation">
        <span class="nav-caption">KIT</span>
        <RouterLink to="/dashboard"><svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z" /></svg> Dashboard</RouterLink>
        <RouterLink to="/network"><svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7h18m-4-4 4 4-4 4M21 17H3m4-4-4 4 4 4" /></svg> Network</RouterLink>
        <RouterLink to="/interfaces"><svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3v5m8-5v5M6 8h12v4a6 6 0 0 1-12 0zM12 18v3" /></svg> Interfaces</RouterLink>
        <RouterLink to="/thingsboard"><svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 18a4 4 0 0 1-1-8 7 7 0 0 1 13-1 4.5 4.5 0 0 1 0 9Z" /></svg> ThingsBoard</RouterLink>
        <span class="nav-caption">MANAGEMENT</span>
        <RouterLink to="/system"><svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6m-6 0v6" /></svg> System</RouterLink>
        <RouterLink to="/monitoring"><svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v18h18M7 16v-4m5 4V7m5 9v-6" /></svg> Monitoring</RouterLink>
        <details :open="['Docker','Terminal','Connector'].includes(route.name)"><summary>Advanced tools</summary><RouterLink to="/connector">Modbus configuration</RouterLink><RouterLink to="/docker">Containers</RouterLink><RouterLink to="/terminal">Terminal</RouterLink></details>
      </nav>
      <footer class="sidebar-footer"><span class="identity">{{ auth.identity || 'Signed in' }}</span><small>{{ auth.authMethod === 'tailscale' ? 'Tailscale session' : 'Local session' }}</small><div class="footer-actions"><button @click="toggleTheme" :aria-label="isDark() ? 'Use light theme' : 'Use dark theme'">{{ isDark() ? 'Light' : 'Dark' }} theme</button><button v-if="auth.authMethod === 'password'" @click="logout">Sign out</button></div></footer>
    </aside>
    <main id="content" tabindex="-1" class="workspace"><RouterView v-slot="{ Component }"><component :is="Component" v-if="['Login','Dashboard'].includes(route.name)" /><AdminFrame v-else-if="route.name"><component :is="Component" /></AdminFrame></RouterView></main>
    <div v-if="show" class="toast" :class="color" role="status">{{ text }}<button aria-label="Dismiss notification" @click="show = false">×</button></div>
  </div>
</template>
<script setup>
import { defineAsyncComponent, onMounted, watch, provide } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './services/auth'
import { useBranding } from './composables/useBranding'
import { useSnackbar } from './composables/useSnackbar'
const AdminFrame = defineAsyncComponent(() => import('./components/AdminFrame.vue'))
const route = useRoute(), router = useRouter(), auth = useAuthStore()
const { kitName, hasLogo, logoUrl, loadBranding, toggleTheme, isDark } = useBranding()
const { show, text, color, showSnackbar } = useSnackbar()
provide('showSnackbar', showSnackbar)
let toastTimer
watch([show, text], () => { clearTimeout(toastTimer); if (show.value) toastTimer = setTimeout(() => { show.value = false }, 5000) })
watch(() => route.path, () => { window.scrollTo(0, 0) })
onMounted(async () => {
  loadBranding()
  await auth.ensureSession()
  if (auth.isAuthenticated && !auth.user) await auth.fetchUser()
})
async function logout() { await auth.logout(); router.push('/login') }
</script>
