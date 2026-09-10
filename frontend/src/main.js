import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

import './style.css'
import { setAdminTheme } from './composables/useBranding'
const app = createApp(App)
app.use(createPinia())
let adminReady
router.beforeResolve(async to => {
  if (!['Dashboard', 'Login'].includes(to.name)) {
    adminReady ||= import('./admin-ui').then(module => setAdminTheme(module.install(app)))
    await adminReady
  }
})
app.use(router)
app.mount('#app')
