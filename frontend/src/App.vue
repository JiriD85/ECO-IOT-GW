<template>
  <v-app>
    <v-navigation-drawer
      v-if="isAuthenticated"
      v-model="drawer"
      :rail="rail"
      permanent
    >
      <v-list-item
        prepend-icon="mdi-access-point-network"
        title="ECO-IOT-GW"
        nav
      >
        <template v-slot:append>
          <v-btn
            variant="text"
            :icon="rail ? 'mdi-chevron-right' : 'mdi-chevron-left'"
            @click="rail = !rail"
          ></v-btn>
        </template>
      </v-list-item>

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
import { ref, computed, provide } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from './services/auth'

const router = useRouter()
const authStore = useAuthStore()

const drawer = ref(true)
const rail = ref(false)

const snackbar = ref({
  show: false,
  text: '',
  color: 'success'
})

const isAuthenticated = computed(() => authStore.isAuthenticated)

const menuItems = [
  { title: 'Dashboard', icon: 'mdi-view-dashboard', path: '/dashboard' },
  { title: 'Docker', icon: 'mdi-docker', path: '/docker' },
  { title: 'Terminal', icon: 'mdi-console', path: '/terminal' },
  { title: 'VPN', icon: 'mdi-vpn', path: '/vpn' },
  { title: 'Diagnostics', icon: 'mdi-chart-line', path: '/diagnostics' },
  { title: 'Modem', icon: 'mdi-antenna', path: '/modem' },
  { title: 'Serial', icon: 'mdi-serial-port', path: '/serial' },
  { title: 'WiFi AP', icon: 'mdi-wifi', path: '/wifi' },
  { title: 'System', icon: 'mdi-cog', path: '/system' },
  { title: 'Audit Log', icon: 'mdi-clipboard-text', path: '/audit' }
]

const showSnackbar = (text, color = 'success') => {
  snackbar.value = { show: true, text, color }
}

provide('showSnackbar', showSnackbar)

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
</style>
