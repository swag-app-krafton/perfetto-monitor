/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Python server (`swagperf dashboard`) serves the built app from web/dist
// and owns the /api routes. In development, Vite proxies /api to it, so run
// the dashboard on 8787 alongside `npm run dev`.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: { outDir: '../web/dist', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8787' } },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
})
