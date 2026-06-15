# SUBSIDE STAC / CKAN registration specs

This folder is the **source of truth** for the SUBSIDE-specific datasets and map
layers that live in the catalog. The catalog *engine* is the separate,
project-agnostic [`stac-platform`](https://github.com/wmobley/stac-platform) repo;
the **SUBSIDE-specific content** lives here, in the application repo, so it isn't
tangled into the generic platform.

| File | What it declares | Registered into | Via |
|------|------------------|-----------------|-----|
| `context_layers.json` | Map **overlays** the SUBSIDE map discovers and renders (the `subside-context` STAC collection): MVT county tiles, ArcGIS aquifers (GeoJSON), TWDB well reports + NGS stable GNSS marks (viewport-driven FeatureServers). | **STAC** (PgSTAC, via the Transactions API) | `python -m stacmap.register_context --specs context_layers.json` |
| `external_datasets.json` | Standalone **CKAN catalog** entries for third-party reference services (TWDB Well Reports, NGS Datasheets) — discoverable, but *not* SUBSIDE run products. | **CKAN** only | `python -m stacmap.register_external --specs external_datasets.json` |

## How to register / update

These are **declarative**: edit the JSON, re-run the matching `stacmap` command,
and the catalog converges to match — no frontend or pod redeploy. `register.sh`
wraps both commands.

```bash
# from subside/ , with stac-platform installed (pip install git+…/stac-platform)
# and STAC_URL/STAC_TOKEN + CKAN_URL/CKAN_TOKEN (or TAPIS_* for a minted JWT) set:
./stac/register.sh
# or individually:
python -m stacmap.register_context  --specs stac/context_layers.json
python -m stacmap.register_external --specs stac/external_datasets.json
```

## Persistence model (why these survive)

Context-layer Items are written to **PgSTAC via the STAC Transactions API** and
**persist there** — the reconcile bridge only ever reconciles run-product
collections (`bridge.cli --collection subsidence-rates`) and prunes *within that
collection*, so it never touches `subside-context`. `register_context` itself is
the only thing that prunes `subside-context`, and only to make it match this
spec (declarative). External datasets are CKAN-only standalone packages, so no
STAC reconcile can affect them. In short: **edit JSON → re-register → it stays**.

See `stac-platform/ARCHITECTURE.md` for the CKAN↔STAC data model and the
dual-write / reconcile paths for per-run products.
