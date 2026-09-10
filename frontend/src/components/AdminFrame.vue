<template><v-app><v-main>
  <div v-if="failed" class="notice warning" role="alert">
    Unable to read some information. Status below may be unavailable or outdated.
    <button @click="retry">Retry page</button>
  </div>
  <div :key="revision"><slot /></div>
</v-main></v-app></template>
<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { managementFailures } from '../services/managementHealth.js'
import { clearApiCache } from '../services/cache.js'
const route = useRoute()
const revision = ref(0)
const failed = computed(() => [...managementFailures.values()].includes(route.path))
function retry() { clearApiCache(); revision.value++ }
</script>
