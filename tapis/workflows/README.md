# SUBSIDE Tapis Workflows

Pipeline definitions + registration tooling for SUBSIDE's OPERA DISP-S1 analysis. The heavy work runs as Tapis apps (containers) on TACC compute; the light orchestration runs as Tapis Workflows function and `tapis_job` tasks.

See [DESIGN.md](DESIGN.md) for the design log — every decision we've made about pipeline shape, task taxonomy, data passing, and the image/app strategy.

## Layout

```
subside/
├── analysis/                    # Python code packed into the Tapis images
│   ├── etl/                             # shared, dataset-agnostic primitives
│   │   ├── auth.py                      # EarthdataSession + cred resolution
│   │   ├── aoi.py                       # GeoJSON + bbox helpers
│   │   ├── manifest.py                  # write_json
│   │   ├── stack.py                     # save/load NetCDF stack, EPSG
│   │   └── archive.py                   # zip helper
│   ├── h2i_lab/                         # OPERA H2I download/preview composition
│   └── werc/                            # OPERA WERC stack/ref/velocity composition
├── workflow_apps/
│   ├── h2i_lab/
│   │   ├── app-cpu.json                 # subside-h2i-opera-analysis  (used by discover + download-opera tasks)
│   │   ├── Dockerfile
│   │   ├── run.sh                       # dispatches CLI subcommand by STAGE env var
│   │   └── environment.yaml
│   └── werc/
│       ├── app-cpu.json                 # subside-werc-opera-analysis (used by all 4 WERC stage tasks)
│       ├── Dockerfile
│       ├── run.sh                       # dispatches CLI subcommand by STAGE env var; per-stage paths come from env vars
│       └── environment.yaml
└── workflows/
    ├── DESIGN.md                        # design log (decisions, why, open questions)
    ├── README.md                        # this file
    ├── register.py                      # tapipy-based registration script
    └── pipelines/
        ├── h2i-opera.yaml               # Pipeline A
        └── werc-opera.yaml              # Pipeline B
```

The Tapis Dockerfiles `COPY analysis /opt/subside/analysis`, so anything under `etl/` is automatically available to every Tapis app — no per-image change needed when we move code between `etl/` and the package modules.

## Pipelines

### A. `subside-h2i-opera`
```
discover ──▶ download-opera ──▶ publish
```
Discovery + Earthdata download + preview + zip archive. Ends with a unified `subside-run-manifest.json`.

### B. `subside-werc-opera`
```
discover ──▶ download-opera ──▶ build-stack ──▶ compute-reference ──▶ estimate-velocity ──▶ export-geotiffs ──▶ publish
```
Adds the WERC stack/reference/velocity/export stages on top of Pipeline A's first two steps. Each WERC stage is its own `tapis_job` task; the displacement stack is spilled to NetCDF on the archive between stages.

## Tapis apps used by these pipelines

| App ID                                | Image                                                                 | STAGE env       | Used by                                                                                                |
| ------------------------------------- | --------------------------------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------ |
| `subside-h2i-discover`                | `ghcr.io/<owner>/subside-h2i-opera-analysis:0.1.0`                    | `preflight`     | `discover` task in both pipelines                                                                       |
| `subside-h2i-opera-analysis`          | `ghcr.io/<owner>/subside-h2i-opera-analysis:0.1.0`                    | (default `run`) | `download-opera` task in both pipelines; also the standalone monolithic app                                |
| `subside-werc-build-stack`            | `ghcr.io/<owner>/subside-werc-opera-analysis:0.1.0`                   | `build-stack`   | Pipeline B                                                                                              |
| `subside-werc-compute-reference`      | `ghcr.io/<owner>/subside-werc-opera-analysis:0.1.0`                   | `compute-reference` | Pipeline B                                                                                          |
| `subside-werc-estimate-velocity`      | `ghcr.io/<owner>/subside-werc-opera-analysis:0.1.0`                   | `estimate-velocity` | Pipeline B                                                                                          |
| `subside-werc-export-geotiffs`        | `ghcr.io/<owner>/subside-werc-opera-analysis:0.1.0`                   | `export-geotiffs` | Pipeline B                                                                                            |
| `subside-werc-opera-analysis`         | `ghcr.io/<owner>/subside-werc-opera-analysis:0.1.0`                   | (default `run`) | Standalone monolithic WERC app (not used by the workflow pipelines, kept for ad-hoc use)                |

Two images, seven apps. Build images via the GHA workflow at `.github/workflows/build-images.yml`.

## Registration

```bash
pip install tapipy pyyaml

export TAPIS_USERNAME=<your-portals-username>
export TAPIS_PASSWORD=<your-portals-password>     # or TAPIS_JWT for token auth
export SUBSIDE_WORKFLOW_GROUP=subside-ops          # override if you want a different group id

# Dry-run first (no API calls, prints what would change)
python workflows/register.py --dry-run

# Real registration
python workflows/register.py
```

Flags:
- `--apps-only` — register apps but skip pipelines.
- `--pipelines-only` — register pipelines, skip apps.
- `--group <id>` — override the workflow group id.

The script discovers every `workflow_apps/*/app-*.json` and every `workflows/pipelines/*.yaml`, so adding a new app or pipeline is "drop the file in the right directory and re-run."

## Invoking a pipeline

Once registered, run a pipeline via the Tapis Workflows API. Quick example using tapipy:

```python
from tapipy.tapis import Tapis

t = Tapis(base_url="https://portals.tapis.io", username="...", password="...")
t.get_tokens()

run = t.workflows.run_pipeline(
    group_id="subside-ops",
    pipeline_id="subside-werc-opera",
    args={
        "start_date": "2024-06-01",
        "end_date": "2024-09-01",
        "aoi_geojson_uri": "tapis://cloud.data/<path>/houston-galveston.geojson",
        "earthdata_netrc_uri": "tapis://cloud.data/<path>/.netrc",
        "reference_mode": "auto",
        "allocation": "<your-tacc-allocation>",
    },
)
print(run.uuid)
```

Or via the Tapis CLI:

```bash
tapis workflows run subside-ops/subside-werc-opera --args-file run-args.json
```

### Durable inner-job recovery

API-created runs pass a secret-free `job_name_prefix`. H2I submits an inner job
named `subside-h2i-opera-{lease-id}`; WERC uses
`subside-werc-opera-{lease-id}-attempt-1` and `-attempt-2` for its confirmed OOM
escalation. Each function searches the exact name before submitting and again
after an ambiguous submission response, so a lost HTTP response cannot create a
duplicate compute job. Direct invocations without the parameter retain their
date-based fallback names.

The API reconciles failed or uncertain workflow runs through the authenticated
Jobs API. A confirmed `FINISHED`/`NORMAL_COMPLETION` job with a ready manifest
is automatically handed to the existing `subside-publish` pipeline exactly
once. The API reports `recovering` until that publication is terminal and keeps
the per-run token until then. `subside-publish` remains available for manual
operator recovery when a legacy run is ambiguous or publication is disabled.

### Access-token refresh for long runs

API-created runs also carry an opaque, lease-bound broker credential when
`SUBSIDE_TOKEN_BROKER_URL` is configured. The workflow uses it to request a
fresh bounded Tapis access token when its original token expires while polling
the inner job or while reading files for publication. The OAuth refresh token
is stored encrypted in the Subside API's user token store and is never passed
to a workflow task or exposed in workflow arguments.

Configure the API with `TAPIS_CLIENT_ID`, `TAPIS_CLIENT_KEY`, and the public
HTTPS base URL in `SUBSIDE_TOKEN_BROKER_URL`, then register the updated pipeline
definitions. The OAuth login endpoint must be used at least once for each user
so the API can persist that user's refresh token. Direct workflow invocations
without broker arguments retain their existing static-token behavior.

## Caveats / TODO

- **Pipeline YAML schema** — the format here is a best-effort match for Tapis Workflows V3 as documented at <https://tapis.readthedocs.io/en/latest/technical/workflows.html>. Verify each field against the live tenant; some templated `{{ tasks.X.outputs.archive }}` and `{{ args.X }}` placeholders may need adjusting.
- **`publish` function task** — uses `urllib.request` against `tapis://` URIs as a placeholder. The function-task runtime needs a real Tapis Files fetch helper or a mount; see the inline `RuntimeError` for where to wire that in.
- **Image tags** — `containerImage` in every app JSON pins `:0.1.0`. The GHA workflow publishes `:latest` and `:sha-<short>`; bump these to a pinned tag once you cut a real release.
- **Earthdata credentials** — still env var + `.netrc`. Tapis secrets / identities integration is its own TODO item (see `subside/TAPIS_WORKFLOW_TODO.md`).
- **Anchor history reuse** — `compute-reference`'s `anchor-history` fileInput is `OPTIONAL`; supply it (pointing at a previously-archived anchors directory) to keep per-frame reference reproducibility across pipeline runs.
