import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { smallUI } from './build-plugins'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue(), smallUI()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false
  }
})
