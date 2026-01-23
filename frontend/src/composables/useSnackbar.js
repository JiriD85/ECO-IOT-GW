import { ref } from 'vue'

// Global snackbar state
const show = ref(false)
const text = ref('')
const color = ref('success')

export function useSnackbar() {
  const showSnackbar = (message, snackbarColor = 'success') => {
    text.value = message
    color.value = snackbarColor
    show.value = true
  }

  return {
    show,
    text,
    color,
    showSnackbar
  }
}
