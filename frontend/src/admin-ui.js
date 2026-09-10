// Vuetify
import 'vuetify/styles'
import { createVuetify } from 'vuetify'

import { Ripple } from 'vuetify/directives'
import { iconSet, aliases } from './icons'
import { components } from 'virtual:eco-components'

const vuetify = createVuetify({
  components,
  directives: { Ripple },
  icons: { defaultSet: 'eco', aliases, sets: { eco: iconSet } },
  defaults: {
    VCard: {
      elevation: 0,
      border: true,
      rounded: 'lg'
    },
    VTextField: {
      density: 'compact',
      variant: 'outlined',
      hideDetails: 'auto'
    },
    VSelect: {
      density: 'compact',
      variant: 'outlined',
      hideDetails: 'auto'
    },
    VSwitch: {
      density: 'compact',
      hideDetails: true,
      color: 'primary'
    },
    VCheckbox: {
      density: 'compact',
      hideDetails: true,
      color: 'primary'
    },
    VBtn: {
      size: 'small'
    },
    VChip: {
      size: 'small'
    },
    VAlert: {
      density: 'compact',
      variant: 'tonal'
    }
  },
  theme: {
    defaultTheme: localStorage.getItem('theme') || 'light',
    themes: {
      dark: {
        dark: true,
        colors: {
          primary: '#2771F6',
          secondary: '#71717A',
          accent: '#82B1FF',
          error: '#FF5252',
          info: '#2196F3',
          success: '#4CAF50',
          warning: '#FFC107',
          background: '#09090B',
          surface: '#18181B',
          'on-surface': '#FAFAFA',
          'on-background': '#FAFAFA',
          'on-primary': '#FFFFFF'
        }
      },
      light: {
        dark: false,
        colors: {
          primary: '#2771F6',
          secondary: '#71717A',
          accent: '#82B1FF',
          error: '#FF5252',
          info: '#2196F3',
          success: '#4CAF50',
          warning: '#FFC107',
          background: '#FFFFFF',
          surface: '#FFFFFF',
          'on-surface': '#18181B',
          'on-background': '#18181B',
          'on-primary': '#FFFFFF'
        }
      }
    }
  }
})


export function install(app) { app.use(vuetify); return vuetify }
