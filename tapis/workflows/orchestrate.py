"""Run a SUBSIDE pipeline on the **hosted Tapis Workflows engine**.

This used to be a local DAG workaround (submit the run job + run the function
tasks locally) for the Workflows restricted-service block. The goal now is to run
the *actual* pipeline server-side in Tapis — so the whole DAG (run -> publish ->
stac-publish) executes in the Workflows engine and any failure surfaces there,
where it can be taken to the Tapis devs.

It reuses smoke_test.py for staging + the Workflows trigger/poll, and adds the
``stac_*`` publish args (from subside/.env) so the ``stac-publish`` task actually
runs (not skipped). The CKAN/STAC bearer defaults to YOUR Tapis token.

Usage::

    pip install tapipy pyyaml python-dotenv
    export TAPIS_USERNAME=... TAPIS_PASSWORD=...        # or TAPIS_JWT
    # subside/.env supplies EARTHDATA_* and SUBSIDE_STAC_*/CKAN_* automatically.

    python tapis/workflows/orchestrate.py --pipeline h2i --allocation PT2050-DataX --with-netrc
    python tapis/workflows/orchestrate.py --pipeline werc --allocation PT2050-DataX --with-netrc --dry-run

Prereqs for stac-publish to succeed in the engine:
  * the pipeline is registered with the stac-publish task (register.py --recreate-pipelines),
  * stac-platform is pushed to GitHub main (the task does `pip install git+...`),
  * SUBSIDE_STAC_URL (incl. /api/v1) is set in subside/.env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import register
import smoke_test


def _client_token(client) -> str:
    """The caller's Tapis access token — passed so the function task can auth to
    CKAN + the STAC API as the user. NOTE: this is embedded in the Workflows run
    args (visible in run history); it's your own token."""
    at = getattr(client, "access_token", None)
    return getattr(at, "access_token", None) or (str(at) if at else "")


def _ckan_auth_token(token: str) -> str:
    token = str(token or "").strip()
    if not token or token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}" if token.count(".") == 2 else token


def _build_args(pipeline_key: str, aoi_uri: str, netrc_uri: str | None,
                allocation: str, client) -> dict:
    """smoke_test's run args + the stac_* publish args (when SUBSIDE_STAC_URL set).

    Values are wrapped as ``{"value": <scalar>}`` — the shape the Workflows /run
    endpoint validates against.
    """
    args = smoke_test._build_args(pipeline_key, aoi_uri, netrc_uri, allocation)
    args.update({
        "tapis_base_url": {"value": register.DEFAULT_BASE_URL},
        "tapis_token": {"value": _client_token(client)},
    })

    stac_url = os.environ.get("SUBSIDE_STAC_URL")
    if not stac_url:
        print("[note] SUBSIDE_STAC_URL unset -> the stac-publish task will skip.")
        return args

    token = _client_token(client)
    ckan_token = _ckan_auth_token(os.environ.get("SUBSIDE_CKAN_TOKEN") or token)
    args.update({
        "stac_collection": {"value": os.environ.get("SUBSIDE_STAC_COLLECTION", "subsidence-rates")},
        "ckan_url": {"value": os.environ.get("SUBSIDE_CKAN_URL", "https://ckan.tacc.utexas.edu")},
        "ckan_org": {"value": os.environ.get("SUBSIDE_CKAN_ORG", "tacc-water")},
        "ckan_token": {"value": ckan_token},
        "stac_url": {"value": stac_url},
        "stac_token": {"value": os.environ.get("SUBSIDE_STAC_TOKEN") or token},
    })
    print("[note] stac-publish enabled -> CKAN/STAC bearer = your Tapis token "
          "(embedded in the run args).")
    return args


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pipeline", choices=["h2i", "werc"], default="h2i")
    p.add_argument("--allocation", default=None, help="TACC allocation (env: TACC_ALLOCATION / SUBSIDE_DEFAULT_ALLOCATION).")
    p.add_argument("--staging-system", default="cloud.data")
    p.add_argument("--staging-path", default=None, help="Default: home/<user>/subside-smoke.")
    p.add_argument("--with-netrc", action="store_true")
    p.add_argument("--group", default=register.DEFAULT_GROUP)
    p.add_argument("--poll-interval", type=int, default=30)
    p.add_argument("--timeout", type=int, default=7200)
    p.add_argument("--no-poll", action="store_true", help="Trigger the run + print its uuid; don't poll.")
    p.add_argument("--dry-run", action="store_true", help="Stage + print the run args; trigger nothing.")
    args = p.parse_args(argv)

    # Load subside/.env (EARTHDATA_*, SUBSIDE_STAC_*/CKAN_*, default allocation).
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except ImportError:
        pass

    args.allocation = args.allocation or os.environ.get("TACC_ALLOCATION") \
        or os.environ.get("SUBSIDE_DEFAULT_ALLOCATION")
    args.staging_system = os.environ.get("TAPIS_STAGING_SYSTEM", args.staging_system)
    if not args.allocation:
        raise SystemExit("Need --allocation (or $TACC_ALLOCATION / SUBSIDE_DEFAULT_ALLOCATION).")
    if args.with_netrc and not (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")):
        raise SystemExit("--with-netrc needs EARTHDATA_USERNAME + EARTHDATA_PASSWORD "
                         "(set them in subside/.env or the environment).")

    client = register._authenticate()
    print(f"Authenticated against {register.DEFAULT_BASE_URL} as {client.username}")
    if args.staging_path is None:
        args.staging_path = f"home/{client.username}/subside-smoke"

    pipeline_id = smoke_test.PIPELINES[args.pipeline]
    aoi_uri, netrc_uri = smoke_test._stage_inputs(client, args)
    run_args = _build_args(args.pipeline, aoi_uri, netrc_uri, args.allocation, client)

    if args.dry_run:
        shown = {k: ({"value": "***"} if "token" in k else v) for k, v in run_args.items()}
        print(f"\n[dry-run] would trigger Workflows pipeline '{pipeline_id}' (group={args.group}) with args:")
        print(json.dumps(shown, indent=2, default=str))
        return 0

    print(f"\n[trigger] runPipeline group={args.group} pipeline={pipeline_id}")
    run_uuid = smoke_test._trigger(client, args.group, pipeline_id, run_args)
    if not run_uuid:
        print("[error] could not resolve a pipeline run uuid (trigger failed?)")
        return 1
    print(f"[run] {run_uuid}")
    if args.no_poll:
        print("(--no-poll) not polling. Check the Workflows run for status.")
        return 0

    status = smoke_test._poll(client, args.group, pipeline_id, run_uuid, args)
    print(f"\n===== {pipeline_id} run {run_uuid}: {status} =====")
    return 0 if status in smoke_test.SUCCESS_STATES else 1


if __name__ == "__main__":
    sys.exit(main())
