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
    // The development server is for this computer only. Vite already refuses requests addressed to any other
    // host name, which keeps it unusable through a public reverse proxy; keep it that way (don't add
    // allowedHosts). Use the built version (docker-compose.prod.yml) for anything reachable from outside.
    headers: {
      'X-Frame-Options': 'DENY',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
    },
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
});
