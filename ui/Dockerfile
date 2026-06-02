# SUBSIDE UI — build the Vite app, serve the static bundle via nginx.
#
# nginx reverse-proxies /api/subside/ to the API and /ckan/ to the TACC catalog,
# so the browser stays same-origin (no CORS) — the production equivalent of the
# Vite dev proxy. Point it at your API pod by setting API_UPSTREAM at deploy.
#
# Build context is the repo root (subside/): `docker build -f ui/Dockerfile .`
FROM node:20-alpine AS build
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build   # -> /ui/dist

FROM nginx:1.27-alpine
# The nginx:alpine entrypoint runs envsubst on /etc/nginx/templates/*.template
# at startup, substituting ${API_UPSTREAM} into the proxy config.
COPY ui/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /ui/dist /usr/share/nginx/html

# Default API target (override per deployment, e.g. http://subside-api:8000).
ENV API_UPSTREAM=http://subside-api:8000
EXPOSE 80
