import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://127.0.0.1:5050',
      '/ckan': {
        target: 'https://ckan.tacc.utexas.edu',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/ckan/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
