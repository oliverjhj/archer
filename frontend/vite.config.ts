import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Backend target for the local development proxy.
// The FastAPI app runs on port 8080 (see repository README).
const BACKEND_TARGET = 'http://localhost:8080';

// Paths proxied to the backend during local development so the frontend can be
// developed same-origin.
const PROXIED_PATHS = [
  '/api',
  '/ask',
  '/login',
  '/landing',
  '/chat',
  '/static',
  '/favicon.ico',
];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      PROXIED_PATHS.map((path) => [
        path,
        { target: BACKEND_TARGET, changeOrigin: true },
      ]),
    ),
  },
  css: {
    preprocessorOptions: {
      scss: {
        // Carbon emits Sass deprecation warnings from its own modules; keep the
        // local build output readable.
        quietDeps: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
