"""Command line entrypoint for the WERC OPERA workflow."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace

from subside_analysis.h2i_lab.config import H2IRunConfig

from .config import WercRunConfig
from .runner import preflight, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run WERC OPERA DISP-S1 stack/reference/velocity workflow steps."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "run"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument(
            "--config", required=True, help="Path to WERC run-config JSON."
        )
        command_parser.add_argument(
            "--output-dir", help="Override output_dir from config."
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = WercRunConfig.from_json_file(args.config)
    if args.output_dir:
        h2i = H2IRunConfig.from_dict({**config.h2i.__dict__, "output_dir": args.output_dir})
        config = replace(config, h2i=h2i)

    payload = preflight(config) if args.command == "preflight" else run(config)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
