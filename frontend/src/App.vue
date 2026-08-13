<template>
  <v-app>
    <v-navigation-drawer
      v-if="showChrome"
      v-model="drawer"
      v-model:rail="rail"
      permanent
    >
      <!-- Header with toggle button -->
      <div class="d-flex align-center pa-2">
        <!-- Toggle button - always visible at left edge -->
        <v-btn
          variant="text"
          :icon="rail ? 'mdi-menu' : 'mdi-chevron-left'"
          size="small"
          @click="rail = !rail"
        ></v-btn>
        <v-icon v-if="!rail" class="mx-2">mdi-access-point-network</v-icon>
        <span v-if="!rail" class="text-subtitle-1 font-weight-bold flex-grow-1">{{ kitName }}</span>
        <v-btn
          v-if="!rail"
          variant="text"
          :icon="isDark() ? 'mdi-weather-sunny' : 'mdi-weather-night'"
          size="small"
          @click="toggleTheme"
        ></v-btn>
      </div>

      <v-divider></v-divider>

      <v-list density="compact" nav>
        <v-list-item
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          :prepend-icon="item.icon"
          :title="rail ? '' : item.title"
        ></v-list-item>
      </v-list>

      <template v-slot:append>
        <v-divider></v-divider>
        <v-list density="compact" nav>
          <v-list-item
            v-if="identity"
            :prepend-icon="authMethod === 'tailscale' ? 'mdi-shield-account' : 'mdi-account'"
            :title="rail ? '' : identity"
            :subtitle="rail ? '' : (authMethod === 'tailscale' ? 'via Tailscale' : 'signed in')"
          ></v-list-item>
          <v-list-item
            v-if="authMethod === 'password'"
            prepend-icon="mdi-logout"
            :title="rail ? '' : 'Logout'"
            @click="logout"
          ></v-list-item>
          <v-list-item
            v-else-if="!isAuthenticated"
            prepend-icon="mdi-login"
            :title="rail ? '' : 'Log in'"
            @click="goLogin"
          ></v-list-item>
        </v-list>
      </template>
    </v-navigation-drawer>

    <v-main class="main-content">
      <div class="main-scroll-container">
        <router-view />
      </div>
    </v-main>

    <v-snackbar
      v-model="snackbar.show"
      :color="snackbar.color"
      :timeout="3000"
    >
      {{ snackbar.text }}
    </v-snackbar>
  </v-app>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from './services/auth'
import { useSnackbar } from './composables/useSnackbar'
import { useBranding } from './composables/useBranding'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const snackbar = useSnackbar()
const { kitName, logoUrl, hasLogo, loadBranding, toggleTheme, isDark } = useBranding()

const drawer = ref(true)
const rail = ref(false)

const isAuthenticated = computed(() => authStore.isAuthenticated)
const identity = computed(() => authStore.identity)
const authMethod = computed(() => authStore.authMethod)
// Show the nav chrome everywhere except the dedicated login page.
const showChrome = computed(() => route.name !== 'Login')

const goLogin = () => {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

onMounted(async () => {
  loadBranding()
  // Resolve session identity (Tailscale login or existing token).
  await authStore.ensureSession()
  if (authStore.accessToken && !authStore.user) {
    await authStore.fetchUser()
  }
})

const menuItems = [
  { title: 'Dashboard', icon: 'mdi-view-dashboard', path: '/dashboard' },
  { title: 'Meters', icon: 'mdi-flash', path: '/meters' },
  { title: 'Connector', icon: 'mdi-transit-connection-variant', path: '/connector' },
  { title: 'Docker', icon: 'mdi-docker', path: '/docker' },
  { title: 'ThingsBoard', icon: 'mdi-cloud-sync', path: '/thingsboard' },
  { title: 'Terminal', icon: 'mdi-console', path: '/terminal' },
  { title: 'Interfaces', icon: 'mdi-ethernet', path: '/interfaces' },
  { title: 'Network', icon: 'mdi-network', path: '/network' },
  { title: 'System', icon: 'mdi-cog-outline', path: '/system' },
  { title: 'Monitoring', icon: 'mdi-monitor-dashboard', path: '/monitoring' }
]

const logout = async () => {
  await authStore.logout()
  router.push('/login')
}
</script>

<style>
html, body, #app {
  height: 100%;
  overflow: hidden;
}

.v-application {
  height: 100%;
}

.main-content {
  height: 100%;
  overflow: hidden;
}

.main-scroll-container {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
}

.cursor-pointer {
  cursor: pointer;
}
</style>
