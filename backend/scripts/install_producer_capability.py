#!/usr/bin/env python3
"""Root installer for the host-side compound producer capability marker."""

import argparse
import os
from pathlib import Path
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backup.producer_capability import (  # noqa: E402
    PRIVILEGED_SCRIPT_NAMES,
    capability_marker_payload,
    write_capability_marker_fsynced,
)


def arguments(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--marker", default="/state/public/producer-capability.json"
    )
    parser.add_argument("--scripts-dir", default="/repo/scripts")
    parser.add_argument(
        "--entrypoint", default="/app/scripts/spaceworks_entrypoint.py"
    )
    parser.add_argument("--migrations-dir", default="/app/apps")
    return parser.parse_args(argv)


def verification_public_key(input_text):
    matches = []
    for line in input_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != "BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY":
            continue
        try:
            parsed = shlex.split(value, comments=True, posix=True)
        except ValueError as exc:
            raise RuntimeError("The archive verification public key is malformed.") from exc
        if len(parsed) != 1 or not parsed[0]:
            raise RuntimeError("The archive verification public key is missing.")
        matches.append(parsed[0])
    if len(matches) != 1:
        raise RuntimeError("The installer requires exactly one archive verification public key.")
    return matches[0]


def install_capability(
    *, marker, scripts_dir, entrypoint, migrations_dir, verification_key,
    require_root_owned=True,
):
    scripts = Path(scripts_dir)
    payload = capability_marker_payload(
        script_paths={name: scripts / name for name in PRIVILEGED_SCRIPT_NAMES},
        entrypoint_path=entrypoint,
        verification_public_key=verification_key,
        migrations_root=migrations_dir,
    )
    write_capability_marker_fsynced(
        marker, payload, require_root_owned=require_root_owned
    )
    return payload


def main(argv=None):
    if os.geteuid() != 0:
        raise RuntimeError("The producer capability installer must run as root.")
    args = arguments(argv)
    try:
        public_key = verification_public_key(sys.stdin.read())
    except UnicodeError as exc:
        raise RuntimeError("The archive verification public key is malformed.") from exc
    install_capability(
        marker=args.marker,
        scripts_dir=args.scripts_dir,
        entrypoint=args.entrypoint,
        migrations_dir=args.migrations_dir,
        verification_key=public_key,
    )


if __name__ == "__main__":
    main()
