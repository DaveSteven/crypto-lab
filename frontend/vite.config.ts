/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
import { defineConfig, loadEnv } from 'vite'

const apiOrigin = (mode = 'development'): string => {
  const env = loadEnv(mode, process.cwd(), '')
  return env.VITE_API_ORIGIN ?? 'http://127.0.0.1:8642'
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Bind the loopback interface deterministically (IPv6-only binding made
    // 127.0.0.1 probes fail during E2E).
    host: '127.0.0.1',
    // Local-only backend (docs/09 §7): proxy avoids any CORS exposure.
    // Override with VITE_API_ORIGIN if the API runs on another port.
    proxy: {
      // ws:true lets the crypto-lab.v1 WebSocket ride the same proxy.
      '/api': { target: apiOrigin(), changeOrigin: false, ws: true },
      '/health': { target: apiOrigin(), changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
