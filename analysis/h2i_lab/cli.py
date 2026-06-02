"""Command line entrypoint for the H2I Lab OPERA workflow."""

from __future__ import annotations

import argparse
import json

from .config import H2IRunConfig
from .runner import preflight, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run H2I Lab OPERA DISP-S1 workflow steps.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("preflight", "run"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--config", required=True, help="Path to H2I run-config JSON.")
        command_parser.add_argument("--output-dir", help="Override output_dir from config.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = H2IRunConfig.from_json_file(args.config)
    if args.output_dir:
        config = H2IRunConfig.from_dict({**config.__dict__, "output_dir": args.output_dir})

    payload = preflight(config) if args.command == "preflight" else run(config)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

