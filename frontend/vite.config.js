import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/static/agents-ui/',
  build: {
    outDir: '../static/agents-ui',
    emptyOutDir: true,
    rollupOptions: {
      input: fileURLToPath(new URL('./src/main.jsx', import.meta.url)),
      output: {
        entryFileNames: 'main.js',
        chunkFileNames: 'main-[name].js',
        assetFileNames: (assetInfo) =>
          assetInfo.names?.[0]?.endsWith('.css') ? 'main.css' : 'assets/[name][extname]',
      },
    },
  },
})
