"""HOST-ONLY: the backend image does not include repository-level scripts/."""

import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IMPORT_SCRIPT = REPOSITORY_ROOT / "scripts" / "import-backup.sh"
pytestmark = pytest.mark.skipif(
    not IMPORT_SCRIPT.exists(),
    reason="HOST-ONLY: scripts/import-backup.sh is outside the backend test image",
)


DOCKER_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$DOCKER_STUB_LOG"

map_path() {
  case "$1" in
    /var/lib/spaceworks/ops/*)
      printf '%s/%s\n' "$SPACEWORKS_OPS_HOST_DIR" "${1#/var/lib/spaceworks/ops/}"
      ;;
    *) printf '%s\n' "$1" ;;
  esac
}

if [[ " $* " == *" preflight_backup_import "* ]]; then
  printf '%s\n' 'Import preflight refused [manifest_signature]: stub refusal.' >&2
  exit 23
fi

for ((index=1; index <= $#; index++)); do
  argument="${!index}"
  if [[ "$argument" == "age" ]]; then
    output=""
    for ((inner=index + 1; inner <= $#; inner++)); do
      value="${!inner}"
      if [[ "$value" == "-o" ]]; then
        next=$((inner + 1))
        output="${!next}"
      fi
    done
    source="${!#}"
    cp -- "$(map_path "$source")" "$(map_path "$output")"
    exit 0
  fi
  if [[ "$argument" == "-" ]]; then
    first=$((index + 1))
    second=$((index + 2))
    third=$((index + 3))
    python3 - "$(map_path "${!first}")" "$(map_path "${!second}")" \
      "$(map_path "${!third}")"
    exit 0
  fi
done

printf '%s\n' "unexpected docker invocation: $*" >&2
exit 91
"""


def _write_outer_tar(path):
    values = {
        "manifest.json": json.dumps({"format": "invalid-for-stub"}).encode(),
        "keys/env.json": json.dumps({"SECRET_KEY": "archive-secret"}).encode(),
    }
    with tarfile.open(path, "w") as archive:
        for name, payload in values.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


def test_failing_preflight_precedes_environment_and_service_mutation(tmp_path):
    fake_root = tmp_path / "deployment"
    scripts = fake_root / "scripts"
    commands = tmp_path / "commands"
    ops = tmp_path / "ops"
    scripts.mkdir(parents=True)
    commands.mkdir()
    ops.mkdir()
    copied_script = scripts / "import-backup.sh"
    copied_script.write_bytes(IMPORT_SCRIPT.read_bytes())
    copied_script.chmod(0o755)
    (scripts / "restore.sh").write_text("#!/usr/bin/env bash\nexit 99\n")
    (fake_root / "docker-compose.prod.yml").write_text("services: {}\n")
    original_env = b"SECRET_KEY='target-secret'\nUNRELATED='preserved'\n"
    env_file = fake_root / ".env"
    env_file.write_bytes(original_env)
    identity = ops / "age-identity.txt"
    identity.write_text("AGE-SECRET-KEY-STUB\n")
    source = tmp_path / "download.tar.age"
    _write_outer_tar(source)
    docker = commands / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    environment = {
        **os.environ,
        "PATH": f"{commands}:{os.environ['PATH']}",
        "SPACEWORKS_OPS_HOST_DIR": str(ops),
        "DOCKER_STUB_LOG": str(log),
    }

    completed = subprocess.run(
        [str(copied_script), str(source), "target-admin"],
        cwd=fake_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 23
    assert "[manifest_signature]" in completed.stderr
    assert env_file.read_bytes() == original_env
    assert not list(fake_root.glob(".env.pre-restore-*"))
    invocations = log.read_text()
    assert "run --rm --no-deps -T backend" in invocations
    assert "--force-recreate" not in invocations
    assert not any(" up -d " in f" {line} " for line in invocations.splitlines())
    assert "import_backup_archive" not in invocations
    assert not list(ops.glob("import-*"))
