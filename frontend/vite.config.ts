import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// The dashboard talks to the API on the same origin. In development Vite forwards /api to the backend
// (uvicorn app.main:app --app-dir backend, port 8000); in production FastAPI serves frontend/dist itself.
const API_TARGET = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000';

// The API contract version the generated types (src/api/schema.d.ts) were made from; the Settings page compares it with the server's.
const CONTRACT_VERSION = (JSON.parse(readFileSync(fileURLToPath(new URL('./openapi.json', import.meta.url)), 'utf8')) as { info: { version: string } }).info.version;

export default defineConfig({
  plugins: [react()],
  define: { __CONTRACT_VERSION__: JSON.stringify(CONTRACT_VERSION) },
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { '/api': { target: API_TARGET, changeOrigin: true } },
  },
  preview: { port: 4173, proxy: { '/api': { target: API_TARGET, changeOrigin: true } } },
  build: { target: 'es2022', sourcemap: false, chunkSizeWarningLimit: 600 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    css: false,
    include: ['tests/**/*.test.{ts,tsx}'],
  },
});
