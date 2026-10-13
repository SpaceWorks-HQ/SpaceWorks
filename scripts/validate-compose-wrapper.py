#!/usr/bin/env python3
"""Validate all trusted wrapper inputs before Docker Compose sees them."""

import argparse
import os
from pathlib import Path
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
        # A privileged restore may operate a user-owned install. Trust the
        # repository owner's private .env, while pointer/record stay root-owned.
        static_owner_uid=Path(os.environ.get("SPACEWORKS_UPDATE_INSTALL_DIR", ROOT)).stat().st_uid,
    )


if __name__ == "__main__":
    main()
