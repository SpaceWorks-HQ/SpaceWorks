#!/usr/bin/env python3
"""Root-only entrypoint for D7 Cloud static configuration initialization."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from apps.backup.cloud_environment import init_from_current_environment  # noqa: E402
from apps.backup.host_supervisor import supervise_run  # noqa: E402


def render_compose_config(compose_path, static_env, pointer_path):
    """Render Compose only in this root-owned host process, never in Django."""
    scrubbed = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "DOCKER_HOST", "DOCKER_CONTEXT", "XDG_RUNTIME_DIR"}
    }
    completed = subprocess.run(
        [
            "docker", "compose", "--env-file", str(static_env),
            "--env-file", str(pointer_path), "-f", str(compose_path), "config",
        ],
        env=scrubbed,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init-from-current-environment",))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--ops-dir", default="/var/lib/spaceworks/ops")
    parser.add_argument("--static-env", default="/etc/spaceworks/cloud.env")
    parser.add_argument("--compose", default=str(ROOT / "docker-compose.cloud.yml"))
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise RuntimeError("Cloud environment initialization must run as root.")
    ops = Path(args.ops_dir)
    with supervise_run(
        ops,
        run_id=args.run_id,
        artifact_sha256=args.artifact_sha256,
        phases=("cloud-config-initialization",),
    ) as session:
        if session.resume.phase is None:
            raise RuntimeError("Cloud environment was already initialized for this run.")
        begun = session.ledger.begin(
            "cloud-config-initialization", {"source": "invoking-environment"}
        )
        result = init_from_current_environment(
            compose_path=args.compose,
            static_env_path=args.static_env,
            pointer_path=ops / "database-pointer.env",
            topology_record_path=ops / "compose-topology.json",
            compose_renderer=render_compose_config,
        )
        session.ledger.finish(begun, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
