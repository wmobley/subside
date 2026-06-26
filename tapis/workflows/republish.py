#!/usr/bin/env python3
"""Re-publish an ALREADY-FINISHED SUBSIDE job to CKAN + STAC via the
``subside-publish`` pipeline — no recompute.

Use this when a run's original pipeline died after the compute job succeeded
(e.g. the run-task poll-loop failure) so its ``publish`` / ``stac-publish`` tasks
never fired. Triggers the standalone ``subside-publish`` pipeline server-side on
TACC, where the job's outputs already live.

SAFETY: by default this is a VALIDATION run — it triggers ``resolve`` + ``publish``
but leaves ``ckan_token``/``stac_url`` blank so the ``stac-publish`` task NO-OPS
(writes nothing to CKAN/STAC). Pass ``--publish`` to perform the real dual-write.

Prereqs:
  * the pipeline is registered:
      python tapis/workflows/register.py --pipelines-only --recreate-pipelines
  * auth env (same as orchestrate.py): TAPIS_USERNAME+TAPIS_PASSWORD or TAPIS_JWT
  * for --publish: SUBSIDE_STAC_URL set (and SUBSIDE_CKAN_URL/ORG); CKAN/STAC
    bearer defaults to YOUR Tapis token.

Usage:
    # validation run (no external write):
    python tapis/workflows/republish.py 05645338-47d6-4503-85bf-6b1550c58d51-007

    # real publish (external write — CKAN + STAC):
    python tapis/workflows/republish.py 05645338-...-007 --publish [--wait]
"""

from __future__ import annotations

import argparse
import os
import sys

import register
import smoke_test

PIPELINE_ID = "subside-publish"


def _token(client) -> str:
    """The caller's Tapis bearer token (used to read the archive + auth CKAN/STAC)."""
    return register._auth_headers(client)["X-Tapis-Token"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("job_uuid", help="Finished Tapis job UUID to publish.")
    p.add_argument("--group", default=register.DEFAULT_GROUP)
    p.add_argument("--publish", action="store_true",
                   help="PERFORM the real CKAN + STAC write. Without this flag the "
                        "stac-publish task no-ops (validation only).")
    p.add_argument("--manifest-name", default="",
                   help="Override the manifest filename (blank = auto from the job's appId).")
    p.add_argument("--collection", default=os.environ.get("SUBSIDE_STAC_COLLECTION", "subsidence-rates"))
    p.add_argument("--item-id", default="", help="STAC Item id (blank = derive from manifest dates + job).")
    p.add_argument("--ckan-url", default=os.environ.get("SUBSIDE_CKAN_URL", "https://ckan.tacc.utexas.edu"))
    p.add_argument("--ckan-org", default=os.environ.get("SUBSIDE_CKAN_ORG", "tacc-water"))
    p.add_argument("--stac-url", default=os.environ.get("SUBSIDE_STAC_URL", ""))
    p.add_argument("--wait", action="store_true", help="Poll until the run finishes and print failures.")
    p.add_argument("--poll-interval", type=int, default=30, help="Seconds between status polls (with --wait).")
    p.add_argument("--timeout", type=int, default=1800, help="Max seconds to poll one run (with --wait).")
    args = p.parse_args(argv)

    client = register._authenticate()
    token = _token(client)
    base_url = os.environ.get("TAPIS_BASE_URL", register.DEFAULT_BASE_URL)

    # Blank ckan_token + stac_url => the stac-publish task no-ops. --publish wires
    # the caller's token + the STAC URL so the dual-write actually runs.
    if args.publish:
        if not args.stac_url:
            return p.error("--publish requires SUBSIDE_STAC_URL (or --stac-url).")
        ckan_token, stac_url, stac_token = token, args.stac_url, token
        print(f"[mode] PUBLISH — will write to CKAN ({args.ckan_url}, org={args.ckan_org}) "
              f"+ STAC ({args.stac_url})")
    else:
        ckan_token, stac_url, stac_token = "", "", ""
        print("[mode] VALIDATION — resolve + publish only; stac-publish will NO-OP "
              "(no CKAN/STAC write). Re-run with --publish to write.")

    run_args = {
        "job_uuid": {"value": args.job_uuid},
        "tapis_base_url": {"value": base_url},
        "tapis_token": {"value": token},
        "manifest_name": {"value": args.manifest_name},
        "stac_collection": {"value": args.collection},
        "stac_item_id": {"value": args.item_id},
        "ckan_url": {"value": args.ckan_url},
        "ckan_org": {"value": args.ckan_org},
        "ckan_token": {"value": ckan_token},
        "stac_url": {"value": stac_url},
        "stac_token": {"value": stac_token},
    }

    print(f"[trigger] runPipeline group={args.group} pipeline={PIPELINE_ID} job={args.job_uuid}")
    run_uuid = smoke_test._trigger(client, args.group, PIPELINE_ID, run_args)
    if not run_uuid:
        print("[error] could not resolve a pipeline run uuid (trigger failed?)", file=sys.stderr)
        return 1
    print(f"[run] {run_uuid}")

    if not args.wait:
        print("Inspect with:  python tapis/workflows/dump_run.py "
              f"{run_uuid} --pipeline publish")
        return 0

    status = smoke_test._poll(client, args.group, PIPELINE_ID, run_uuid, args)
    print(f"\n===== {PIPELINE_ID} run {run_uuid}: {status} =====")
    if str(status).lower() not in ("completed", "success", "succeeded"):
        smoke_test._dump_failures(client, args.group, PIPELINE_ID, run_uuid)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
