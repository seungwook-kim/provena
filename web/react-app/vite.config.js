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

export function chatProxyBypass(request) {
  return request.method === 'GET' ? '/index.html' : undefined
}

// /recalls and /changes are both SPA page paths and API paths. Browser page loads ask
// for HTML and get the SPA entry; fetch() calls from the app go to the API.
export function pageOrApiProxyBypass(request) {
  const accept = request.headers?.accept ?? ''
  return request.method === 'GET' && accept.includes('text/html') ? '/index.html' : undefined
}

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
      '/threads': proxyTarget,
      '/chat': { target: proxyTarget, bypass: chatProxyBypass },
      '/health': proxyTarget,
      '/recalls': { target: proxyTarget, bypass: pageOrApiProxyBypass },
      '/changes': { target: proxyTarget, bypass: pageOrApiProxyBypass },
      '/approvals': proxyTarget,
      '/decision-tables': proxyTarget,
      '/maintenance-candidates': proxyTarget,
      '/impact-preview': proxyTarget,
    },
  },
})
