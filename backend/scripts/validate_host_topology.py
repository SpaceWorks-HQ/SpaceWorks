#!/usr/bin/env python3
"""Validate scheduler fencing declarations in one or more YAML topologies."""

from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backup.topology import validate_scheduler_contract


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: validate_host_topology.py <compose.yml> [...]")
    for name in argv[1:]:
        with Path(name).open(encoding="utf-8") as handle:
            validate_scheduler_contract(yaml.safe_load(handle))


if __name__ == "__main__":
    main(sys.argv)
