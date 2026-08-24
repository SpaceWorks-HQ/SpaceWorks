#!/usr/bin/env python3
"""Root-only atomic pointer/config record writer; never captures ambient state."""

import argparse
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from apps.backup.host_pointer import PointerRecord, write_pointer_atomic  # noqa: E402
from apps.backup.host_topology_record import (  # noqa: E402
    configuration_facts,
    write_topology_record,
)
from apps.backup.topology import validate_host_orchestration_contract  # noqa: E402
import yaml  # noqa: E402


def arguments(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("initialize-pointer", "record-config"))
    parser.add_argument("--topology", choices=("bundled", "cloud"), required=True)
    parser.add_argument("--static-env", required=True)
    parser.add_argument("--pointer", required=True)
    parser.add_argument("--record", required=True)
    parser.add_argument("--compose-file", action="append", required=True)
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--reader-gid", type=int)
    return parser.parse_args(argv)


def main(argv=None):
    args = arguments(argv)
    with Path(args.compose_file[0]).open(encoding="utf-8") as handle:
        contract = validate_host_orchestration_contract(yaml.safe_load(handle))
    if args.action == "initialize-pointer":
        database_url = sys.stdin.readline().rstrip("\r\n")
        write_pointer_atomic(
            args.pointer,
            PointerRecord(database_url, args.generation),
        )
    facts = configuration_facts(
        topology=args.topology,
        static_env=args.static_env,
        compose_files=args.compose_file,
    )
    if facts["scheduler_mode"] != contract["scheduler"]["mode"]:
        raise RuntimeError(
            "Static scheduler mode disagrees with the Compose topology declaration."
        )
    write_topology_record(args.record, facts)
    if args.reader_gid is not None:
        for path in (Path(args.pointer), Path(args.record)):
            os.chown(path, 0, args.reader_gid)
            os.chmod(path, 0o640)
        os.chown(Path(args.pointer).parent, 0, args.reader_gid)
        os.chmod(Path(args.pointer).parent, 0o750)


if __name__ == "__main__":
    main()
