# SUBSIDE

**Subsidence System for Insight and Data Exploration** — a statewide portal that
helps Texans understand their risk of land subsidence. SUBSIDE pairs **observed**
ground movement (measured from NASA OPERA DISP-S1 satellite radar) with a
**forecast** screening model, over context layers from the TWDB data catalog.

Led by the Texas Water Development Board (TWDB) with UT Austin and TACC,
supported by the USGS, with research collaborators WERC and the H2I Lab
(UT Arlington). See the in-app **About** page (content in [`ui/content/`](ui/content/)).

---

## What's in here

This repo is four cooperating pieces — a React frontend, a FastAPI gateway, a
reusable Python analysis package, and containerized Tapis batch apps:

```
subside/
├── ui/         React/Vite frontend (src, index.html, vite.config, package.json, content/)
├── api/        FastAPI gateway in front of Tapis + PostGIS + the forecast model
├── analysis/   Reusable Python analysis (OPERA pipelines + the forecast model)
├── tapis/      Tapis batch apps + pipelines (tapis/workflow_apps, tapis/workflows)
├── examples/   Source notebooks, static wireframe, and sample data
├── ARCHITECTURE.md          full system overview: the three engines, data flow, every subsystem
└── TAPIS_WORKFLOW_TODO.md   Tapis Workflows design notes + status
```

`ui/content/` holds the editable Markdown site copy (About page); `examples/`
holds the notebooks the OPERA pipelines were extracted from plus the original
static wireframe.

**Read [ARCHITECTURE.md](ARCHITECTURE.md) for the full picture.** The short version:
the portal answers "how much is the ground at my location sinking?" three ways —
**observed** (OPERA DISP-S1 InSAR, run as Tapis batch jobs), **forecast**
(an in-process aquifer screening model → a 0–10 risk score), and **context**
(spatial layers served from PostGIS as vector tiles).

## The three engines at a glance

| Engine | What it answers | Where it runs |
|---|---|---|
| **Observed** (OPERA DISP-S1) | How much / how fast has the land moved? | Tapis batch jobs — pipelines `h2i` (displacement) and `werc` (velocity) |
| **Forecast** (subsidence screening) | Projected subsidence + a 0–10 risk score | In-process in the API (`POST /api/subside/forecast`) — sub-second, no job |
| **Context** (spatial layers) | Aquifers, wells, frame availability, … | PostGIS → MVT vector tiles (`/api/subside/tiles/...`) |

## Quick start

### Frontend (React + Vite)

```bash
cd ui
npm install
npm run dev          # http://127.0.0.1:5174
```

The Vite dev proxy forwards `/api/subside/*` → the SUBSIDE API on `:8000`,
`/api/*` → a legacy backend on `:5050`, and `/ckan/*` → the TACC CKAN catalog.
Stack: React 19, react-leaflet + leaflet.vectorgrid (vector tiles) +
georaster-layer-for-leaflet (COG rasters), react-markdown.

### API (FastAPI)

```bash
cp .env.sample .env     # fill in Earthdata + allocation; PostGIS URL optional
# Run inside the conda env that has the geo + pandas stack:
conda activate subside-h2i-opera
uvicorn api.main:app --reload --port 8000
```

The API degrades gracefully: the core (login + runs) works with the minimal
[`api/requirements.txt`](api/requirements.txt); the PostGIS layer endpoints
return 503 without `SUBSIDE_DATABASE_URL`, the discovery endpoints need the geo
stack, and the forecast endpoint needs `numpy`+`pandas`. See
[ARCHITECTURE.md](ARCHITECTURE.md#api-api) for the endpoint map.

### Local hostnames + HTTPS (for OAuth login)

To use `subside.local` (frontend) and `api.subside.local` (API), map them to
loopback (one time, needs sudo):

```bash
sudo sh -c 'printf "\n# SUBSIDE local dev\n127.0.0.1 subside.local\n127.0.0.1 api.subside.local\n" >> /etc/hosts'
```

Vite is configured with `server.host: true` so it binds IPv4 (`127.0.0.1`) — the
custom names map there. (Without it Vite binds IPv6 `::1` only and `subside.local`
times out.) **Restart `npm run dev` after pulling these config changes.**

**HTTPS** — Tapis OAuth callbacks must be `https://`, so the dev frontend needs a
local cert. Use [mkcert](https://github.com/FiloSottile/mkcert):

```bash
brew install mkcert nss          # nss = Firefox trust (optional)
mkcert -install                  # trust the local CA (one time)
mkdir -p ui/.certs && cd ui/.certs
mkcert -cert-file subside.local.pem -key-file subside.local-key.pem \
       subside.local api.subside.local localhost 127.0.0.1 ::1
```

With those files present, Vite serves **https://subside.local:5174** (it falls
back to HTTP if they're absent). `.certs/` is gitignored.

Then register the OAuth client with the **https** callback and point the API at it:

```bash
python tapis/workflows/register_oauth_client.py --callback-url https://subside.local:5174/
# paste the printed client id/key into subside/.env, with:
#   TAPIS_OAUTH_CALLBACK_URL=https://subside.local:5174/
```

> macOS note: `.local` is also mDNS/Bonjour, but `/etc/hosts` takes precedence
> (verified: `subside.local` resolves to `127.0.0.1`). The connection issue is the
> IPv4/IPv6 bind above, not name resolution.

### Build

```bash
cd ui
npm run build        # → ui/dist/
```

## Editing site content (no code)

The About page text and partner/goal cards are Markdown files in
[`ui/content/`](ui/content/) loaded at build time. Edit those (e.g. via the GitHub web
UI) without touching React — see [ui/content/README.md](ui/content/README.md).

## Deeper docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — system overview, data flow, every subsystem, deployment, known constraints
- [TAPIS_WORKFLOW_TODO.md](TAPIS_WORKFLOW_TODO.md) — Tapis Workflows design + status
- [tapis/workflow_apps/opera-disp-s1.model-catalog.yaml](tapis/workflow_apps/opera-disp-s1.model-catalog.yaml) — MINT model-catalog registration for the OPERA apps
- [analysis/subsidence/README.md](analysis/subsidence/README.md) — the forecast model adapter
