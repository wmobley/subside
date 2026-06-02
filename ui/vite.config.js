import fs from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Local HTTPS (needed because Tapis OAuth callbacks must be https). Generated
// with mkcert into .certs/ — see README "Local hostnames". When the cert files
// are absent the dev server falls back to plain HTTP, so this is opt-in.
const KEY = './.certs/subside.local-key.pem'
const CERT = './.certs/subside.local.pem'
const https = fs.existsSync(KEY) && fs.existsSync(CERT)
  ? { key: fs.readFileSync(KEY), cert: fs.readFileSync(CERT) }
  : undefined

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind all IPv4 interfaces (incl. 127.0.0.1). Vite otherwise binds IPv6
    // ::1 only, which the /etc/hosts subside.local -> 127.0.0.1 mapping can't reach.
    host: true,
    port: 5174,
    https,
    // Allow the custom local hostnames (mapped to 127.0.0.1 in /etc/hosts).
    allowedHosts: ['subside.local', 'api.subside.local'],
    proxy: {
      // SUBSIDE FastAPI (auth / runs / forecast / layers / tiles / availability).
      '/api/subside': 'http://127.0.0.1:8000',
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
