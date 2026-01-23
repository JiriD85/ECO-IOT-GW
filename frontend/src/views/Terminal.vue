<template>
  <v-container fluid class="fill-height pa-0">
    <v-card class="fill-height" style="width: 100%">
      <v-card-title class="d-flex align-center">
        <v-icon class="mr-2">mdi-console</v-icon>
        Terminal
        <v-spacer></v-spacer>
        <v-chip
          :color="connected ? 'success' : 'error'"
          size="small"
        >
          {{ connected ? 'Connected' : 'Disconnected' }}
        </v-chip>
        <v-btn
          v-if="!connected"
          class="ml-2"
          color="primary"
          size="small"
          @click="connect"
        >
          Connect
        </v-btn>
        <v-btn
          v-else
          class="ml-2"
          color="error"
          size="small"
          @click="disconnect"
        >
          Disconnect
        </v-btn>
      </v-card-title>
      <v-divider></v-divider>
      <div ref="terminalContainer" class="terminal-container"></div>
    </v-card>
  </v-container>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import { WebLinksAddon } from 'xterm-addon-web-links'
import 'xterm/css/xterm.css'
import { useAuthStore } from '../services/auth'

const authStore = useAuthStore()

const terminalContainer = ref(null)
const connected = ref(false)

let terminal = null
let fitAddon = null
let socket = null

const connect = () => {
  if (socket) {
    socket.close()
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/api/terminal/ws?token=${authStore.accessToken}`

  socket = new WebSocket(wsUrl)
  socket.binaryType = 'arraybuffer'

  socket.onopen = () => {
    connected.value = true
    terminal.clear()
    terminal.writeln('Connected to terminal...\r\n')

    // Send initial resize
    sendResize()
  }

  socket.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      terminal.write(new Uint8Array(event.data))
    } else {
      terminal.write(event.data)
    }
  }

  socket.onclose = () => {
    connected.value = false
    terminal.writeln('\r\nConnection closed.')
  }

  socket.onerror = (error) => {
    console.error('WebSocket error:', error)
    connected.value = false
    terminal.writeln('\r\nConnection error.')
  }
}

const disconnect = () => {
  if (socket) {
    socket.close()
    socket = null
  }
  connected.value = false
}

const sendResize = () => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({
      type: 'resize',
      rows: terminal.rows,
      cols: terminal.cols
    }))
  }
}

const initTerminal = () => {
  terminal = new Terminal({
    cursorBlink: true,
    fontSize: 14,
    fontFamily: 'Menlo, Monaco, "Courier New", monospace',
    theme: {
      background: '#1E1E1E',
      foreground: '#CCCCCC',
      cursor: '#FFFFFF',
      selection: 'rgba(255, 255, 255, 0.3)'
    }
  })

  fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  terminal.loadAddon(new WebLinksAddon())

  terminal.open(terminalContainer.value)
  fitAddon.fit()

  // Handle input
  terminal.onData((data) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const encoder = new TextEncoder()
      socket.send(encoder.encode(data))
    }
  })

  // Handle resize
  window.addEventListener('resize', handleResize)

  terminal.writeln('Terminal ready. Click "Connect" to start.')
}

const handleResize = () => {
  if (fitAddon) {
    fitAddon.fit()
    sendResize()
  }
}

onMounted(async () => {
  await nextTick()
  initTerminal()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  disconnect()
  if (terminal) {
    terminal.dispose()
  }
})
</script>

<style scoped>
.terminal-container {
  height: calc(100% - 64px);
  background: #1E1E1E;
  padding: 8px;
}
</style>
