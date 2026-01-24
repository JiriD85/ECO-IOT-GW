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
        <v-icon v-if="!rail" class="mx-2">mdi-access-point-network</v-icon>
        <span v-if="!rail" class="text-subtitle-1 font-weight-bold flex-grow-1">ECO-IOT-GW</span>
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

    <v-main>
      <router-view />
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
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from './services/auth'
import { useSnackbar } from './composables/useSnackbar'

const router = useRouter()
const authStore = useAuthStore()
const snackbar = useSnackbar()

const drawer = ref(true)
const rail = ref(false)

const isAuthenticated = computed(() => authStore.isAuthenticated)

const menuItems = [
  { title: 'Dashboard', icon: 'mdi-view-dashboard', path: '/dashboard' },
  { title: 'Docker', icon: 'mdi-docker', path: '/docker' },
  { title: 'ThingsBoard', icon: 'mdi-cloud-sync', path: '/thingsboard' },
  { title: 'Terminal', icon: 'mdi-console', path: '/terminal' },
  { title: 'VPN', icon: 'mdi-vpn', path: '/vpn' },
  { title: 'Diagnostics', icon: 'mdi-chart-line', path: '/diagnostics' },
  { title: 'Modem', icon: 'mdi-antenna', path: '/modem' },
  { title: 'Serial', icon: 'mdi-serial-port', path: '/serial' },
  { title: 'WiFi AP', icon: 'mdi-wifi', path: '/wifi' },
  { title: 'System', icon: 'mdi-cog', path: '/system' },
  { title: 'NTP', icon: 'mdi-clock-outline', path: '/ntp' },
  { title: 'Audit Log', icon: 'mdi-clipboard-text', path: '/audit' }
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

.cursor-pointer {
  cursor: pointer;
}
</style>
