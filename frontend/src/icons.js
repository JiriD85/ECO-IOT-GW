import { h } from 'vue'
import { aliases } from 'vuetify/iconsets/mdi'
import paths from 'virtual:eco-icons'
export { aliases }
export const iconSet = {
  component: props => h(props.tag || 'span', { class: 'v-icon', 'aria-hidden': 'true' }, [
    h('svg', { viewBox: '0 0 24 24', width: '1em', height: '1em', fill: 'currentColor' }, [
      h('path', { d: paths[props.icon] || paths['mdi-help-circle'] })
    ])
  ])
}
