import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The build lands in the backend's static dir, which is what the FastAPI app
// serves in the single-image deployment.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    // Dev only: the API runs separately on 8000 until the image is built.
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
