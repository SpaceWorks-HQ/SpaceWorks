#!/usr/bin/env python3
"""Privileged consume-only socket lifecycle for a host-orchestrated run."""

import argparse
from datetime import timedelta
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from apps.backup.host_capability_journal import CapabilityJournal  # noqa: E402
from apps.backup.host_capability_socket import CapabilitySocketServer  # noqa: E402
from apps.backup.host_capability_types import record_from_marker, utc_now  # noqa: E402
from apps.backup.host_launch_grant import generate_launch_grant_keys  # noqa: E402
from apps.backup.host_marker import read_marker  # noqa: E402
from apps.backup.operation_lock import host_operation_lock  # noqa: E402


def arguments(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init-keys", "arm", "rearm", "invalidate", "serve"))
    parser.add_argument("--ops-dir", default="/var/lib/spaceworks/ops")
    parser.add_argument("--state-dir", default="/var/lib/spaceworks/host")
    parser.add_argument("--expires-seconds", type=int, default=60)
    parser.add_argument("--reason", default="operator-invalidated")
    parser.add_argument("--peer-uid", type=int, default=10001)
    return parser.parse_args(argv)


def _paths(state_dir):
    state = Path(state_dir)
    return {
        "marker": state / "public" / "restore-marker.json",
        "journal": state / "private" / "capability-journal.jsonl",
        "socket": state / "public" / "capability.sock",
        "private": state / "private" / "launch-grant-private.key",
        "public": state / "public" / "launch-grant-public.key",
    }


def main(argv=None):
    args = arguments(argv)
    if os.geteuid() != 0:
        raise RuntimeError("Host capability control must run as root.")
    paths = _paths(args.state_dir)
    if args.action == "init-keys":
        existing = (Path(paths["private"]).exists(), Path(paths["public"]).exists())
        if all(existing):
            return
        if any(existing):
            raise RuntimeError("Launch-grant keypair is incomplete; refusing implicit rotation.")
        generate_launch_grant_keys(paths["private"], paths["public"])
        return
    with host_operation_lock(args.ops_dir, require_root_owned=True):
        marker = read_marker(paths["marker"])
        journal = CapabilityJournal(paths["journal"])
        if args.action == "invalidate":
            journal.invalidate_all(args.reason)
            return
        if args.expires_seconds < 1 or args.expires_seconds > 300:
            raise RuntimeError("Capability expiry must be between 1 and 300 seconds.")
        record = record_from_marker(
            marker,
            allowed_role="backend",
            expires_at=utc_now() + timedelta(seconds=args.expires_seconds),
        )
        if args.action == "arm":
            journal.arm(record)
            return
        if args.action == "rearm":
            previous_nonce = journal.latest_spent_nonce()
            if previous_nonce is None:
                raise RuntimeError("No spent capability is available for explicit re-arm.")
            journal.rearm(previous_nonce, record)
            return
        if args.action == "serve":
            CapabilitySocketServer(
                socket_path=paths["socket"],
                journal=journal,
                marker_path=paths["marker"],
                private_key_path=paths["private"],
                public_key_path=paths["public"],
                pointer_path=Path(args.ops_dir) / "database-pointer.env",
                expected_peer_uid=args.peer_uid,
            ).serve_forever()


if __name__ == "__main__":
    main()
