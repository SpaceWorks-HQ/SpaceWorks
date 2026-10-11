"""Run the actual host updater with local command seams and no Docker/network access."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(not BASH or not (ROOT / "scripts/update.sh").exists(), reason="requires bash and repository scripts")
OLD = "0.5.0-main.1.aaaaaaaaaaaa"
NEW = "0.5.0-main.2.bbbbbbbbbbbb"


def write_script(path, source):
    path.write_text("#!/usr/bin/env bash\n" + source, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def host(tmp_path):
    scripts, bins = tmp_path / "scripts", tmp_path / "bin"
    scripts.mkdir()
    bins.mkdir()
    for name in ("update.sh", "update-lock.sh", "module-selection.sh", "update-rollback.sh"):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    (tmp_path / ".spaceworks-version").write_text(OLD)
    write_script(bins / "docker", "exit 0\n")
    write_script(bins / "sleep", "exit 0\n")
    write_script(bins / "curl", '''
printf '%s\\n' "$*" >> "$TEST_CURL_LOG"
[[ "${TEST_FAILURE:-}" != github ]] || exit 22
printf '[{"tag_name":"v%s","draft":false,"prerelease":false,"published_at":"2026-10-10T10:00:00Z"}]\\n' "$TEST_RELEASE"
''')
    write_script(scripts / "spaceworks-compose.sh", '''
printf '%s\\n' "$*" >> "$TEST_COMPOSE_LOG"
printf '%s: %s\\n' "${MAKERSPACE_IMAGE_TAG:-current}" "$*" >> "$TEST_IMAGE_LOG"
case "$*" in
  *"update_control rollback-plan"*) echo "${TEST_ROLLBACK_PLAN:-none}" ;;
  *"update_control claim"*) echo "${TEST_DECISION:-run} $TEST_RELEASE" ;;
  *"update_control snapshot"*) [[ "${TEST_FAILURE:-}" != snapshot ]] || exit 1 ;;
  *"backup_control describe"*)
    stage=requested
    [[ ! -f "$TEST_RESTORE_STAGE" ]] || stage="$(cat "$TEST_RESTORE_STAGE")"
    printf '{"stage": "%s"}\\n' "$stage" ;;
  *"update_control complete"*) [[ "${TEST_FAILURE:-}" != complete ]] || exit 1 ;;
  *"exec -T"*"python -c"*)
    if [[ "${TEST_FAILURE:-}" == readiness && "${MAKERSPACE_IMAGE_TAG:-}" == "$TEST_RELEASE" ]]; then exit 1; fi ;;
  *"pull "*)
    if [[ "${TEST_FAILURE:-}" == pull ]]; then exit 1; fi ;;
esac
exit 0
''')
    environment = {
        **os.environ, "PATH": str(bins) + os.pathsep + os.environ["PATH"],
        "SPACEWORKS_OPS_HOST_DIR": str(tmp_path / "ops"),
        "TEST_COMPOSE_LOG": str(tmp_path / "compose.log"),
        "TEST_CURL_LOG": str(tmp_path / "curl.log"), "TEST_RELEASE": NEW,
        "TEST_IMAGE_LOG": str(tmp_path / "images.log"),
        "TEST_RESTORE_STAGE": str(tmp_path / "restore-stage"),
        "SPACEWORKS_COMPOSE_LAYER": "none", "SPACEWORKS_COMPOSE_BUILD_LAYER": "0",
    }
    environment.pop("MAKERSPACE_IMAGE_TAG", None)
    return tmp_path, environment


def run(host, **overrides):
    root, environment = host
    result = subprocess.run(
        [BASH, str(root / "scripts/update.sh"), "--no-module-changes"],
        cwd=root, env={**environment, **overrides}, capture_output=True, text=True, timeout=30,
    )
    log = root / "compose.log"
    return result, log.read_text(encoding="utf-8") if log.exists() else ""


def test_success_finishes_and_releases_both_locks(host):
    result, log = run(host)
    root, _ = host
    assert result.returncode == 0, result.stderr
    assert (root / ".spaceworks-version").read_text(encoding="utf-8").strip() == NEW
    assert "update_control complete" in log
    assert log.index("update_control snapshot") < log.index("pull ") < log.index("update_control complete")
    assert "--releases-stdin" in log
    assert "update_control fail" not in log
    assert not (root / ".spaceworks-update.lock").exists()
    curl = (root / "curl.log").read_text(encoding="utf-8")
    assert "--max-time 30" in curl and "--retry 2" in curl


@pytest.mark.parametrize("failure", ["complete", "readiness"])
def test_failed_deployment_rolls_back_and_resets_the_version_marker(host, failure):
    result, log = run(host, TEST_FAILURE=failure)
    root, _ = host
    assert result.returncode != 0
    assert "Rollback complete" in result.stdout
    assert (root / ".spaceworks-version").read_text(encoding="utf-8").strip() == OLD
    assert "update_control fail" in log
    assert not (root / ".spaceworks-update.lock").exists()


@pytest.mark.parametrize("failure", ["github", "pull"])
def test_failed_provider_check_or_pull_keeps_the_previous_release(host, failure):
    result, log = run(host, TEST_FAILURE=failure)
    root, _ = host
    assert result.returncode != 0
    assert (root / ".spaceworks-version").read_text(encoding="utf-8").strip() == OLD
    assert "update_control complete" not in log
    assert ("update_control fail" in log) == (failure == "pull")
    assert not (root / ".spaceworks-update.lock").exists()


def test_noop_never_takes_a_backup_or_replaces_containers(host):
    result, log = run(host, TEST_DECISION="skip")
    assert result.returncode == 0
    assert "pg_dump" not in log and "pull " not in log
    assert (host[0] / ".spaceworks-version").read_text(encoding="utf-8") == OLD


def test_single_box_uses_its_running_app_for_readiness_and_pulls_its_image(host):
    result, log = run(host, SPACEWORKS_COMPOSE_LAYER="single")
    assert result.returncode == 0, result.stderr
    assert "pull migrate app" in log and "exec -T app python -c" in log
    assert "exec -T backend python -c" not in log


def test_persisted_single_box_layer_is_respected(host):
    (host[0] / ".spaceworks-layer").write_text("single\n")
    result, log = run(host, SPACEWORKS_COMPOSE_LAYER="")
    assert result.returncode == 0, result.stderr
    assert "pull migrate app" in log


def test_a_live_update_owner_is_refused_before_any_provider_call(host):
    root, _ = host
    lock = root / ".spaceworks-update.lock"
    lock.mkdir()
    (lock / "owner").write_text(f"{os.getpid()} 1\n")
    result, log = run(host)
    assert result.returncode != 0
    assert "Another update owns" in result.stderr
    assert log == "" and lock.exists()


def test_snapshot_failure_cancels_before_images_or_migrations_change(host):
    result, log = run(host, TEST_FAILURE="snapshot")
    assert result.returncode != 0
    assert "update_control fail" in log
    assert "pull " not in log and "Running migrations" not in result.stdout
    assert (host[0] / ".spaceworks-version").read_text().strip() == OLD
    assert not (host[0] / ".spaceworks-update.lock").exists()


def test_a_dead_update_owner_is_recovered(host):
    root, _ = host
    lock = root / ".spaceworks-update.lock"
    lock.mkdir()
    (lock / "owner").write_text("2147483647 1\n")
    result, _ = run(host)
    assert result.returncode == 0, result.stderr
    assert "Recovering the stale update lock" in result.stdout
    assert not lock.exists()
