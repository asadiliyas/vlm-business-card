import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // In dev, the app talks to the API via relative '/api/...' calls, same
    // as it does in production (single-origin). This proxy forwards those
    // to a locally running backend (`uvicorn app.main:app --port 8000`) so
    // no CORS configuration is needed for local development either.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
