import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Inside Docker the API is reachable at http://api:8008; running locally it's localhost.
const apiTarget = process.env.API_PROXY_TARGET || 'http://localhost:8008';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Needed for hot reload when files are bind-mounted from Windows.
    watch: { usePolling: true },
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
});
