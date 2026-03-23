import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(() => {
  const frontendPort = Number(process.env.KODA_VITE_PORT ?? '5173')
  const backendTarget =
    process.env.KODA_VITE_BACKEND_TARGET ?? 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      port: frontendPort,
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
        },
        '/media': {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
    },
  }
})
