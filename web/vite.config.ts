/// <reference types="vitest" />
import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// The backend (app/api/main.py) serves /runs*, with no /api prefix, so the dev proxy strips it.
// Override the base for other deployments with VITE_API_BASE (see web/README.md).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Overridable so the E2E honesty project can point a second dev server at the no-provider
        // backend (:8010). The backend ships no CORS middleware, so the proxy is the only way across.
        target: process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Playwright specs live in e2e/; without this vitest collects them and every file fails on
    // "Playwright Test did not expect test() to be called here".
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
});