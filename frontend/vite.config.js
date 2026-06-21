import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// https://vitejs.dev/config/
export default defineConfig({
  // Load .env from this folder even if Vite is started from the monorepo root.
  envDir: __dirname,
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Fail fast if 5173 is busy so API proxy always matches README / VS Code (no silent 5174+ drift).
    strictPort: true,
    open: false,
    // Browser calls /api/* → stripped to /* → forwarded to FastAPI (must match uvicorn port; default 8000).
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '') || '/',
      },
    },
  },
  // `npm run preview` with VITE_API_URL=/api — otherwise /api/* returns 404 HTML and APIs show "Not Found".
  preview: {
    port: 4173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '') || '/',
      },
    },
  },
})
