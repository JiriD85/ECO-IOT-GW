<template>
  <v-app>
    <v-navigation-drawer
      v-if="isAuthenticated"
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
        <v-img v-if="!rail && hasLogo" :src="logoUrl" height="40" max-width="120" contain class="mx-2" />
        <v-icon v-else-if="!rail" class="mx-2">mdi-access-point-network</v-icon>
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
          :title="item.title"
        ></v-list-item>
      </v-list>

      <template v-slot:append>
        <v-list density="compact" nav>
          <v-list-item
            prepend-icon="mdi-logout"
            title="Logout"
            @click="logout"
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
import { useRouter } from 'vue-router'
import { useAuthStore } from './services/auth'
import { useSnackbar } from './composables/useSnackbar'
import { useBranding } from './composables/useBranding'

const router = useRouter()
const authStore = useAuthStore()
const snackbar = useSnackbar()
const { kitName, logoUrl, hasLogo, loadBranding, toggleTheme, isDark } = useBranding()

const drawer = ref(true)
const rail = ref(false)

const isAuthenticated = computed(() => authStore.isAuthenticated)

onMounted(async () => {
  loadBranding()
  // Load user info if already authenticated (after page refresh)
  if (authStore.isAuthenticated && !authStore.user) {
    await authStore.fetchUser()
  }
})

const menuItems = [
  { title: 'Dashboard', icon: 'mdi-view-dashboard', path: '/dashboard' },
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
