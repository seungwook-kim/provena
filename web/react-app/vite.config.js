import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'

// The browser reaches Vite on the host, but Vite itself may run inside the
// local web container. In that case 127.0.0.1 points back to the web
// container, not to FastAPI on the host.
const runningInDocker = fs.existsSync('/.dockerenv')
const proxyTarget = process.env.VITE_API_PROXY_TARGET
  ?? (runningInDocker ? 'http://host.docker.internal:8000' : 'http://127.0.0.1:8000')

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Keep browser cookies same-origin in local development. Production uses
  // VITE_API_BASE_URL (or the deployed application's own origin) instead.
  server: {
    port: 5180,
    strictPort: false,
    hmr: true,
    proxy: {
      '/auth': proxyTarget,
      '/me': proxyTarget,
      '/admin': proxyTarget,
    },
  },
})
