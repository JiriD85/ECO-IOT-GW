<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <h1 class="text-h4 mb-4">Interfaces</h1>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12">
        <v-card>
          <!-- Tabs navigation -->
          <v-tabs
            v-model="currentTab"
            bg-color="primary"
            show-arrows
          >
            <v-tab
              v-for="route in childRoutes"
              :key="route.name"
              :value="`/interfaces/${route.path}`"
              :to="`/interfaces/${route.path}`"
            >
              <v-icon v-if="route.meta?.tabIcon" start>
                {{ route.meta.tabIcon }}
              </v-icon>
              {{ route.meta?.tabLabel || route.name }}
            </v-tab>
          </v-tabs>

          <v-divider />

          <!-- Tab content area -->
          <v-card-text class="pa-4">
            <router-view />
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

// Get child routes from router configuration
const childRoutes = computed(() => {
  const interfacesRoute = router.getRoutes().find(r => r.name === 'Interfaces')
  return interfacesRoute?.children || []
})

// Sync tab state with current route
const currentTab = ref(route.path)

watch(() => route.path, (newPath) => {
  currentTab.value = newPath
})
</script>
