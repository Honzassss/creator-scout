import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev proxy: the FastAPI backend runs on 127.0.0.1:8000 (see docs/architecture.md section 7).
// Override with API_TARGET=http://127.0.0.1:8765 npm run dev.
// SSE responses must not be buffered, so we keep the proxy plain (no compression changes).
const target = process.env.API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target,
        changeOrigin: true,
      },
    },
  },
})
