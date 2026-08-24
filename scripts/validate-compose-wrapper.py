#!/usr/bin/env python3
"""Validate all trusted wrapper inputs before Docker Compose sees them."""

import argparse
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from apps.backup.host_topology_record import validate_compose_wrapper  # noqa: E402
def arguments(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--topology", choices=("bundled", "cloud"), required=True)
    parser.add_argument("--static-env", required=True)
    parser.add_argument("--pointer", required=True)
    parser.add_argument("--record", required=True)
    parser.add_argument("--compose-file", action="append", required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = arguments(argv)
    validate_compose_wrapper(
        topology=args.topology,
        static_env=args.static_env,
        pointer_file=args.pointer,
        topology_record=args.record,
        compose_files=args.compose_file,
    )


if __name__ == "__main__":
    main()
