# SUBSIDE UI — build the Vite app, serve the static bundle via nginx.
#
# nginx serves static files only (no reverse proxy). The browser calls the
# SUBSIDE API and CKAN directly (CORS); the API origin is injected at container
# start into /runtime-config.js by docker-entrypoint.d/40-runtime-config.sh from
# the SUBSIDE_API_BASE env var. (A UI pod can't proxy back through the Tapis
# ingress to the API pod — that egress times out. See ui/nginx.conf.)
#
# Build context is the repo root (subside/): `docker build -f ui/Dockerfile .`
FROM node:20-alpine AS build
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build   # -> /ui/dist

FROM nginx:1.27-alpine
# Static SPA config (serve files + SPA fallback; no reverse proxy).
COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
# Rewrites /runtime-config.js from env vars (SUBSIDE_API_BASE, …) at startup.
# The nginx:alpine entrypoint runs /docker-entrypoint.d/*.sh before nginx boots.
COPY ui/docker-entrypoint.d/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh
COPY --from=build /ui/dist /usr/share/nginx/html
EXPOSE 80
