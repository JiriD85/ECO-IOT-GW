# Phase 5: Menu Restructuring - Research

**Researched:** 2026-01-24
**Domain:** Vue 3 + Vuetify 3 Navigation Restructuring with Tab-based Views
**Confidence:** HIGH

## Summary

This research investigates how to restructure a Vue 3 + Vuetify 3 application's navigation from 15 separate menu items to 8 consolidated items using tab-based grouping. The current application has a v-navigation-drawer with individual routes for each configuration page, and the goal is to combine related pages into tabbed views (e.g., Modem + Serial becomes "Interfaces" with tabs).

The standard approach involves creating new parent view components that contain v-tabs for navigation and either v-window/v-window-item for content display, or nested Vue Router child routes for deeper integration. The existing view components (ModemConfig.vue, SerialConfig.vue, etc.) can be reused as-is within the tabbed structure with minimal modifications.

Vue Router supports this pattern through nested routes with children arrays, where parent routes can act as containers while child routes render in nested router-view components. Vuetify 3 provides v-tabs and v-window components specifically designed for this use case, with built-in state management and Material Design styling.

**Primary recommendation:** Use nested Vue Router child routes combined with v-tabs navigation in new parent container views, reusing existing component files as child route components to minimize code changes and maintain existing logic.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vue 3 | ^3.4.0 | Framework | Current version in project, Composition API used throughout |
| Vue Router | ^4.2.5 | Routing | Already installed, supports nested routes natively |
| Vuetify 3 | ^3.5.0 | UI Components | Project's UI framework, provides v-tabs and v-window components |
| Pinia | ^2.1.7 | State Management | Already in project for auth, can manage tab state if needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| v-tabs | Built-in | Tab navigation UI | For visual tab headers in parent views |
| v-window | Built-in | Tab content container | When not using router-based tabs |
| v-window-item | Built-in | Individual tab panels | Pairs with v-window for content display |
| router-view | Built-in | Nested route outlet | When using router-based tabs (recommended) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Nested routes | v-window only | Simpler but loses deep linking, browser history, route guards |
| v-tabs | Custom tab component | More control but loses Material Design, accessibility features |
| Reusing existing components | Rewriting as tab panels | Complete control but massive code duplication and maintenance burden |

**Installation:**
```bash
# No additional packages needed - all components available in existing stack
# Vue Router, Vuetify 3 already installed per package.json
```

## Architecture Patterns

### Recommended Project Structure
```
frontend/src/views/
├── Login.vue                    # Unchanged
├── Dashboard.vue                # Unchanged
├── DockerManager.vue            # Unchanged
├── Terminal.vue                 # Unchanged
├── ThingsboardConfig.vue        # Unchanged
├── Interfaces.vue               # NEW: Parent view with tabs for Modem + Serial
├── ModemConfig.vue              # Moved to child component (minimal changes)
├── SerialConfig.vue             # Moved to child component (minimal changes)
├── Network.vue                  # NEW: Parent view with tabs for Failover + VPN + WiFi
├── NetworkStatus.vue            # Renamed from old Network, becomes Failover tab
├── VpnConfig.vue                # Moved to child component (minimal changes)
├── WifiConfig.vue               # Moved to child component (minimal changes)
├── System.vue                   # NEW: Parent view with tabs for Settings + NTP + Backup + Admin
├── SystemSettings.vue           # Moved to child component (minimal changes)
├── NtpConfig.vue                # Moved to child component (minimal changes)
├── Backup.vue                   # Moved to child component (minimal changes)
├── AdminConfig.vue              # NEW: Admin panel (if needed)
├── Monitoring.vue               # NEW: Parent view with tabs for Diagnostics + Audit + SMS
├── Diagnostics.vue              # Moved to child component (minimal changes)
├── AuditLog.vue                 # Moved to child component (minimal changes)
└── SmsAlerts.vue                # Moved to child component (minimal changes)
```

### Pattern 1: Nested Routes with v-tabs
**What:** Create parent container views with nested child routes, using v-tabs to control which child route is displayed.

**When to use:** When you want deep linking (e.g., /interfaces/modem), browser history support, and to leverage route guards/metadata.

**Example:**
```javascript
// router/index.js - Nested route configuration
// Source: Vue Router Official Docs - https://router.vuejs.org/guide/essentials/nested-routes.html
const routes = [
  {
    path: '/interfaces',
    name: 'Interfaces',
    component: () => import('../views/Interfaces.vue'),
    redirect: '/interfaces/modem', // Default to first tab
    children: [
      {
        path: 'modem',
        name: 'Modem',
        component: () => import('../views/ModemConfig.vue'),
        meta: { tabLabel: 'Modem', tabIcon: 'mdi-antenna' }
      },
      {
        path: 'serial',
        name: 'Serial',
        component: () => import('../views/SerialConfig.vue'),
        meta: { tabLabel: 'Serial', tabIcon: 'mdi-serial-port' }
      }
    ]
  }
]
```

```vue
<!-- views/Interfaces.vue - Parent container view -->
<!-- Source: Bytewax Tutorial - https://bytewax.io/blog/child-routes-tabs-vue-3 -->
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
          <v-tabs v-model="currentTab" bg-color="primary">
            <v-tab
              v-for="route in childRoutes"
              :key="route.name"
              :value="route.path"
              :to="route.path"
            >
              <v-icon v-if="route.meta?.tabIcon" start>
                {{ route.meta.tabIcon }}
              </v-icon>
              {{ route.meta?.tabLabel || route.name }}
            </v-tab>
          </v-tabs>

          <v-card-text>
            <!-- Child route components render here -->
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

// Compute child routes from router configuration
const childRoutes = computed(() => {
  const currentRoute = router.getRoutes().find(r => r.name === 'Interfaces')
  return currentRoute?.children || []
})

// Track current tab based on route
const currentTab = ref(route.path)

// Watch route changes to update tab
watch(() => route.path, (newPath) => {
  currentTab.value = newPath
})
</script>
```

### Pattern 2: v-window Approach (Without Router)
**What:** Use v-tabs with v-window/v-window-item for content switching without changing routes.

**When to use:** When deep linking isn't needed and you want simpler state management (less common for navigation restructuring).

**Example:**
```vue
<!-- Simpler but loses browser history and deep linking -->
<template>
  <v-container fluid>
    <v-tabs v-model="tab">
      <v-tab value="modem">Modem</v-tab>
      <v-tab value="serial">Serial</v-tab>
    </v-tabs>

    <v-window v-model="tab">
      <v-window-item value="modem">
        <ModemConfig />
      </v-window-item>
      <v-window-item value="serial">
        <SerialConfig />
      </v-window-item>
    </v-window>
  </v-container>
</template>

<script setup>
import { ref } from 'vue'
import ModemConfig from './ModemConfig.vue'
import SerialConfig from './SerialConfig.vue'

const tab = ref('modem')
</script>
```

### Pattern 3: Child Component Adaptation
**What:** Minimal changes to existing child components - remove outer container, keep business logic intact.

**When to use:** For all existing view components being moved into tabbed parents.

**Example:**
```vue
<!-- ModemConfig.vue - BEFORE (standalone view) -->
<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <h1 class="text-h4 mb-4">Modem Configuration</h1>
      </v-col>
    </v-row>
    <!-- ... rest of component -->
  </v-container>
</template>

<!-- ModemConfig.vue - AFTER (tab child component) -->
<template>
  <!-- Remove v-container, remove h1 title -->
  <!-- Parent view provides container and title -->
  <v-row>
    <!-- ... existing component content -->
  </v-row>
</template>
```

### Anti-Patterns to Avoid
- **Duplicating component logic:** Don't copy-paste existing component code into tab panels. Reuse the existing .vue files as child components.
- **Hard-coding tab lists:** Use route meta or computed properties to generate tab lists dynamically from router configuration.
- **Breaking responsive layouts:** Existing components use v-row/v-col grids. Ensure parent containers maintain fluid layout.
- **Losing v-model sync:** When using v-tabs with router, watch for route changes to keep tab state synchronized.
- **Ignoring default tabs:** Always provide a redirect or default child route for parent routes to avoid empty views.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tab state management | Custom tab switching logic | Vue Router children + v-tabs :value binding | Router handles history, guards, lazy loading automatically |
| Tab navigation UI | Custom tab header component | Vuetify v-tabs | Material Design, accessibility (keyboard nav, ARIA), responsive behavior built-in |
| Deep linking to tabs | Manual URL parsing | Vue Router nested routes with child paths | Browser history, bookmarkable URLs, route guards work automatically |
| Tab content transitions | Custom CSS animations | RouterView built-in transitions or v-window | Smooth transitions with minimal code, tested across browsers |
| Active tab styling | Manual CSS classes | v-tabs automatic active state | Vuetify handles active states, indicators, colors automatically |
| Route-based tab generation | Hard-coded tab arrays | Computed from router.getRoutes() | Single source of truth, automatically synced with route config |

**Key insight:** Vue Router nested routes combined with Vuetify v-tabs provides battle-tested solutions for navigation restructuring. The framework handles edge cases like simultaneous navigation, route guards on tabs, lazy loading, and browser history that custom solutions often get wrong.

## Common Pitfalls

### Pitfall 1: Not Using Redirect for Default Tab
**What goes wrong:** When navigating to parent route (e.g., /interfaces), no tab is selected and content area is empty.

**Why it happens:** Parent routes with children need explicit redirect to show default content. Without it, router-view renders nothing.

**How to avoid:** Add `redirect` property to parent route configuration pointing to default child.

**Warning signs:**
- Blank screen when navigating to parent route
- Tabs visible but no content rendered
- Console error about unmatched route

```javascript
// WRONG - no redirect
{
  path: '/interfaces',
  component: Interfaces,
  children: [...]
}

// RIGHT - redirects to default child
{
  path: '/interfaces',
  component: Interfaces,
  redirect: '/interfaces/modem', // or { name: 'Modem' }
  children: [...]
}
```

### Pitfall 2: Container/Layout Conflicts
**What goes wrong:** Nested v-container elements cause excessive padding/margin. Grid layouts break when child components expect to be in container context.

**Why it happens:** Existing standalone views have `<v-container fluid>` as root element. Parent tabbed views also add v-container, creating double wrapping.

**How to avoid:**
- Remove v-container from child components when embedding in tabs
- OR use v-card-text in parent which provides padding without container
- Keep v-row/v-col grid structure in children, provide container context in parent

**Warning signs:**
- Excessive whitespace around tab content
- Responsive breakpoints not working as expected
- Grid columns not aligning properly

### Pitfall 3: Tab v-model Not Syncing with Route
**What goes wrong:** Tab indicator doesn't highlight correct tab after browser back/forward navigation or direct URL access.

**Why it happens:** v-tabs v-model holds local state, route.path changes independently. Without watching route changes, they desync.

**How to avoid:**
```javascript
// Use computed or watcher to sync tab state with route
const currentTab = ref(route.path)
watch(() => route.path, (newPath) => {
  currentTab.value = newPath
})
```

**Warning signs:**
- Tab highlight doesn't match displayed content after back button
- Direct URL access shows correct content but wrong active tab
- Tab state resets on page refresh

### Pitfall 4: Menu Item Path Mismatch
**What goes wrong:** Navigation drawer menu items still point to old routes (e.g., /modem) instead of new nested routes (/interfaces/modem).

**Why it happens:** App.vue menuItems array has hardcoded paths that need updating when routes change.

**How to avoid:** Update menuItems array in App.vue to point to new parent routes, not old individual routes. Menu should navigate to `/interfaces` not `/modem`.

**Warning signs:**
- Clicking menu items shows 404 or route not found
- Menu items visible but non-functional
- Active menu item doesn't match current view

### Pitfall 5: Breaking Existing Route Guards and Meta
**What goes wrong:** Route guards stop working, requiresAuth meta not enforced on tabs.

**Why it happens:** Moving from top-level routes to children changes route matching. Guards on old routes need to be moved or adjusted.

**How to avoid:**
- Move meta properties to child routes (they inherit to matched array)
- Review beforeEach guards to ensure they work with nested route structure
- Test authentication flows after restructuring

**Warning signs:**
- Unauthenticated users accessing protected tabs
- Route guards not triggering on tab navigation
- Meta properties undefined in components

### Pitfall 6: Component Instance Lifecycle Issues
**What goes wrong:** Component onMounted hooks fire multiple times, or data fetching happens unnecessarily when switching tabs.

**Why it happens:** Vue Router may destroy/recreate components on route changes depending on keep-alive settings.

**How to avoid:**
- Use keep-alive wrapper around router-view to preserve component instances
- Or accept that tabs reload data on switch (simpler, more predictable)
- Use Pinia stores for shared data between tabs if needed

**Warning signs:**
- Flickering when switching tabs
- Unnecessary API calls on every tab switch
- Lost form state when returning to tab

## Code Examples

Verified patterns from official sources:

### Complete Router Configuration Example
```javascript
// frontend/src/router/index.js
// Source: Vue Router Nested Routes Documentation
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../services/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { public: true }
  },
  {
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue')
  },
  {
    path: '/docker',
    name: 'Docker',
    component: () => import('../views/DockerManager.vue')
  },
  {
    path: '/thingsboard',
    name: 'ThingsBoard',
    component: () => import('../views/ThingsboardConfig.vue')
  },
  {
    path: '/terminal',
    name: 'Terminal',
    component: () => import('../views/Terminal.vue')
  },
  // NEW: Interfaces (Modem + Serial)
  {
    path: '/interfaces',
    name: 'Interfaces',
    component: () => import('../views/Interfaces.vue'),
    redirect: '/interfaces/modem',
    children: [
      {
        path: 'modem',
        name: 'Modem',
        component: () => import('../views/ModemConfig.vue'),
        meta: { tabLabel: 'Modem', tabIcon: 'mdi-antenna' }
      },
      {
        path: 'serial',
        name: 'Serial',
        component: () => import('../views/SerialConfig.vue'),
        meta: { tabLabel: 'Serial', tabIcon: 'mdi-serial-port' }
      }
    ]
  },
  // NEW: Network (Failover + VPN + WiFi)
  {
    path: '/network',
    name: 'Network',
    component: () => import('../views/Network.vue'),
    redirect: '/network/failover',
    children: [
      {
        path: 'failover',
        name: 'Failover',
        component: () => import('../views/NetworkStatus.vue'),
        meta: { tabLabel: 'Failover', tabIcon: 'mdi-swap-horizontal' }
      },
      {
        path: 'vpn',
        name: 'VPN',
        component: () => import('../views/VpnConfig.vue'),
        meta: { tabLabel: 'VPN', tabIcon: 'mdi-vpn' }
      },
      {
        path: 'wifi',
        name: 'WiFi',
        component: () => import('../views/WifiConfig.vue'),
        meta: { tabLabel: 'WiFi AP', tabIcon: 'mdi-wifi' }
      }
    ]
  },
  // NEW: System (Settings + NTP + Backup + Admin)
  {
    path: '/system',
    name: 'System',
    component: () => import('../views/System.vue'),
    redirect: '/system/settings',
    children: [
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('../views/SystemSettings.vue'),
        meta: { tabLabel: 'Settings', tabIcon: 'mdi-cog' }
      },
      {
        path: 'ntp',
        name: 'NtpConfig',
        component: () => import('../views/NtpConfig.vue'),
        meta: { tabLabel: 'NTP', tabIcon: 'mdi-clock-outline', requiresAuth: true }
      },
      {
        path: 'backup',
        name: 'Backup',
        component: () => import('../views/Backup.vue'),
        meta: { tabLabel: 'Backup', tabIcon: 'mdi-backup-restore', requiresAuth: true }
      }
      // Admin tab can be added later if needed
    ]
  },
  // NEW: Monitoring (Diagnostics + Audit + SMS Alerts)
  {
    path: '/monitoring',
    name: 'Monitoring',
    component: () => import('../views/Monitoring.vue'),
    redirect: '/monitoring/diagnostics',
    children: [
      {
        path: 'diagnostics',
        name: 'Diagnostics',
        component: () => import('../views/Diagnostics.vue'),
        meta: { tabLabel: 'Diagnostics', tabIcon: 'mdi-chart-line' }
      },
      {
        path: 'audit',
        name: 'Audit',
        component: () => import('../views/AuditLog.vue'),
        meta: { tabLabel: 'Audit Log', tabIcon: 'mdi-clipboard-text' }
      },
      {
        path: 'sms-alerts',
        name: 'SmsAlerts',
        component: () => import('../views/SmsAlerts.vue'),
        meta: { tabLabel: 'SMS Alerts', tabIcon: 'mdi-message-text', requiresAuth: true }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Navigation guard - unchanged
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (!to.meta.public && !authStore.isAuthenticated) {
    next('/login')
  } else if (to.path === '/login' && authStore.isAuthenticated) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router
```

### Updated App.vue Navigation Menu
```vue
<!-- frontend/src/App.vue - Updated menuItems -->
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

// UPDATED: Consolidated from 15 items to 8
const menuItems = [
  { title: 'Dashboard', icon: 'mdi-view-dashboard', path: '/dashboard' },
  { title: 'Docker', icon: 'mdi-docker', path: '/docker' },
  { title: 'ThingsBoard', icon: 'mdi-cloud-sync', path: '/thingsboard' },
  { title: 'Terminal', icon: 'mdi-console', path: '/terminal' },
  { title: 'Interfaces', icon: 'mdi-ethernet', path: '/interfaces' }, // NEW: Modem + Serial
  { title: 'Network', icon: 'mdi-network', path: '/network' }, // NEW: Failover + VPN + WiFi
  { title: 'System', icon: 'mdi-cog-outline', path: '/system' }, // NEW: Settings + NTP + Backup
  { title: 'Monitoring', icon: 'mdi-monitor-dashboard', path: '/monitoring' } // NEW: Diagnostics + Audit + SMS
]

const logout = async () => {
  await authStore.logout()
  router.push('/login')
}
</script>
```

### Parent Container View Template (Reusable Pattern)
```vue
<!-- views/Interfaces.vue -->
<!-- Pattern can be copied for Network.vue, System.vue, Monitoring.vue -->
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
```

### Adapted Child Component Example
```vue
<!-- views/ModemConfig.vue - Adapted for tab context -->
<!-- CHANGES: Remove v-container wrapper, remove top-level h1 title -->
<!-- Parent view (Interfaces.vue) provides container and "Interfaces" title -->
<!-- Tabs provide context for which interface (Modem/Serial) -->
<template>
  <!-- REMOVED: <v-container fluid> wrapper -->
  <!-- REMOVED: h1 title row -->

  <!-- Keep existing content structure -->
  <v-row>
    <!-- Status Card -->
    <v-col cols="12" md="6">
      <v-card>
        <v-card-title>Connection Status</v-card-title>
        <v-card-text>
          <!-- ... existing content unchanged ... -->
        </v-card-text>
      </v-card>
    </v-col>

    <!-- Configuration Card -->
    <v-col cols="12" md="6">
      <v-card>
        <v-card-title>APN Configuration</v-card-title>
        <!-- ... existing content unchanged ... -->
      </v-card>
    </v-col>
  </v-row>

  <!-- Device Info -->
  <v-row class="mt-4">
    <v-col cols="12">
      <v-card>
        <v-card-title>Device Information</v-card-title>
        <!-- ... existing content unchanged ... -->
      </v-card>
    </v-col>
  </v-row>

  <!-- REMOVED: </v-container> closing tag -->
</template>

<script setup>
// Script section completely unchanged - all business logic stays the same
import { ref, computed, inject, onMounted, onUnmounted } from 'vue'
import { modemApi } from '../services/api'

const showSnackbar = inject('showSnackbar')
// ... rest of script unchanged
</script>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat route structure | Nested routes with children | Vue Router 3 → 4 (2020) | Better organization, route grouping, lazy loading granularity |
| v-tabs-items / v-tab-item | v-window / v-window-item | Vuetify 2 → 3 (2022) | Component name consistency, improved API |
| Options API | Composition API (script setup) | Vue 2 → 3 (2020) | Better code organization, TypeScript support, reusability |
| Hard-coded tab arrays | Route meta-based generation | Best practice evolution (2023+) | Single source of truth, automatic sync |
| router.currentRoute | useRoute() composable | Vue Router 3 → 4 (2020) | Composition API compatibility, better reactivity |

**Deprecated/outdated:**
- `v-tabs-items`: Renamed to `v-window` in Vuetify 3 (v-tabs-items no longer exists)
- `v-tab-item`: Renamed to `v-window-item` in Vuetify 3 (v-tab-item no longer exists)
- `new Router()`: Use `createRouter()` in Vue Router 4
- `$listeners`: Merged into `$attrs` in Vue 3 (not separate anymore)

## Open Questions

Things that couldn't be fully resolved:

1. **Admin Tab Content for System View**
   - What we know: Requirements mention "Admin" as part of System view tabs (MENU-03)
   - What's unclear: No AdminConfig.vue exists in current codebase, unclear what admin features should be included
   - Recommendation: Start with 3 tabs (Settings, NTP, Backup), add Admin tab in follow-up if needed. Verify requirements with user.

2. **Network View Naming (Failover vs NetworkStatus)**
   - What we know: Current NetworkStatus.vue exists, requirements say Network view should have Failover tab
   - What's unclear: Is NetworkStatus the same as Failover monitoring, or separate feature?
   - Recommendation: Treat NetworkStatus.vue as the Failover tab component, may need tab label update

3. **Keep-Alive for Tab Content**
   - What we know: Tabs could use keep-alive to preserve component state when switching
   - What's unclear: Whether preserving state across tab switches is desired or if fresh reload is better
   - Recommendation: Start without keep-alive (simpler, predictable). Add if user requests state preservation.

4. **Tab Order and Default Tab Selection**
   - What we know: Each parent view needs a default redirect to a child tab
   - What's unclear: Preferred tab order and which tab should be default for each group
   - Recommendation: Use alphabetical or most-used-first ordering. Document in PLAN.md for user review.

## Sources

### Primary (HIGH confidence)
- Vue Router Official Documentation - Nested Routes: https://router.vuejs.org/guide/essentials/nested-routes.html
- Vuetify 3 Components - Tabs: https://vuetifyjs.com/en/components/tabs/
- Vuetify 3 Components - Windows: https://vuetifyjs.com/en/components/windows/
- Vuetify 3 Navigation Drawer: https://vuetifyjs.com/en/components/navigation-drawers/
- Current codebase analysis (router/index.js, App.vue, existing view components)

### Secondary (MEDIUM confidence)
- [Bytewax Tutorial: Easy yet flexible way to display child routes in tabs with Vue 3](https://bytewax.io/blog/child-routes-tabs-vue-3) - Verified nested route + tabs pattern
- [Vue Router Architecture and Nested Routes - DEV Community](https://dev.to/berniwittmann/my-approach-on-vue-router-architecture-and-nested-routes-2kmo)
- [Vue Router Best Practices - Dev Academy](https://dev-academy.com/vue-router-best-practices/)
- [MoldStud: Common Mistakes with Vuetify Layout Components](https://moldstud.com/articles/p-avoid-these-common-pitfalls-when-using-vuetify-layout-components)
- [MoldStud: Best Practices for Customizing Vuetify Tabs](https://moldstud.com/articles/p-best-practices-for-customizing-vuetify-tabs-in-your-development-projects)

### Tertiary (LOW confidence)
- Various Stack Overflow discussions about v-tabs with router (historical issues, mostly resolved in Vuetify 3)
- GitHub issues about v-window/v-tabs bugs in specific versions (fixed in current versions)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in use, versions verified from package.json
- Architecture: HIGH - Nested routes + v-tabs is documented, proven pattern in Vue Router and Vuetify official docs
- Pitfalls: HIGH - Based on official documentation warnings, community best practices, and current codebase analysis

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - stable technologies, minor updates unlikely to change patterns)
