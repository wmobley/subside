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
const ckanTarget = process.env.VITE_CKAN_BASE || 'https://ckan.tacc.utexas.edu'
const stacTarget = process.env.SUBSIDE_STAC_PROXY_TARGET || 'https://stacapi.pods.portals.tapis.io/api/v1'

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
        target: ckanTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/ckan/, ''),
      },
      // STAC API (results + context layers). The hosted STAC only allows the
      // deployed UI origins, so local dev reaches it same-origin via this proxy;
      // set VITE_STAC_API_BASE=/stac in .env.local to use it.
      '/stac': {
        target: stacTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/stac/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.{js,jsx}'],
    // Tests assume the shipped defaults; a developer's .env.local (dynamo mode,
    // proxied STAC) must not leak into them.
    env: { VITE_RUN_BACKEND: 'legacy', VITE_DYNAMO_API_BASE: '', VITE_STAC_API_BASE: '', VITE_STAC_COLLECTION: '' },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
