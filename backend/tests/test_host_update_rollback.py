"""Exercise the host handoff with the existing restore supervisor as the seam."""

import shutil
from pathlib import Path

import pytest

from tests.test_host_updater_behavior import NEW, OLD, host, run, write_script

RESTORE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
pytestmark = pytest.mark.skipif(not shutil.which("flock"), reason="rollback supervisor requires Linux flock")


def install_restore(host, *, stage="completed", fail=False):
    root, _ = host
    write_script(root / "scripts/restore.sh", f'''
printf '%s\\n' "$*" > "$TEST_RESTORE_STAGE.args"
printf '%s\\n' '{stage}' > "$TEST_RESTORE_STAGE"
exit {1 if fail else 0}
''')


def rollback(host, **changes):
    (host[0] / ".spaceworks-version").write_text(NEW)
    return run(host, TEST_ROLLBACK_PLAN=f"{OLD} {RESTORE_ID}", **changes)


def test_completed_rollback_hands_off_and_restarts_without_migrations(host):
    install_restore(host)
    result, log = rollback(host)
    root, _ = host
    assert result.returncode == 0, result.stderr
    assert Path(str(root / "restore-stage") + ".args").read_text().strip() == f"{RESTORE_ID} --update-image={OLD}"
    assert (root / ".spaceworks-version").read_text().strip() == OLD
    assert "up -d --no-deps backend frontend" in log
    assert "up -d --no-deps worker beat" in log
    assert "update_control complete" in log
    assert "update_control claim" not in log and "pg_dump" not in log
    assert not (root / "ops/update-rollback.intent").exists()
    assert not (root / ".spaceworks-update.lock").exists()
    assert not (root / "curl.log").exists()


def test_quarantined_rollback_does_not_start_normal_writers(host):
    install_restore(host, stage="restored_quarantined")
    result, log = rollback(host)
    assert result.returncode == 0, result.stderr
    assert "up -d --no-deps backend frontend" in log
    assert "up -d --no-deps worker beat" not in log
    assert "update_control complete" not in log


def test_paused_restore_keeps_durable_intent_and_releases_updater_lock(host):
    install_restore(host, stage="preflight", fail=True)
    result, log = rollback(host)
    root, _ = host
    assert result.returncode != 0
    assert (root / ".spaceworks-version").read_text().strip() == NEW
    assert (root / "ops/update-rollback.intent").read_text().strip() == f"{OLD} {RESTORE_ID}"
    assert not (root / ".spaceworks-update.lock").exists()
    assert "update_control complete" not in log


@pytest.mark.parametrize("stage", ["failed", "aborted"])
def test_terminal_refusal_keeps_current_images_and_does_not_repeat_restore(host, stage):
    root, _ = host
    (root / "restore-stage").write_text(stage)
    result, log = rollback(host)
    assert result.returncode == 0, result.stderr
    assert "up -d" not in log and "update_control complete" not in log
    assert (root / ".spaceworks-version").read_text().strip() == NEW
    assert not (root / "ops/update-rollback.intent").exists()


def test_single_box_refuses_before_restore_or_image_changes(host):
    result, log = rollback(host, SPACEWORKS_COMPOSE_LAYER="single")
    assert result.returncode != 0 and "bundled topology" in result.stderr
    assert "up -d" not in log and "update_control claim" not in log


def test_resume_uses_host_intent_after_the_database_pointer_is_lost(host):
    root, _ = host
    (root / ".spaceworks-version").write_text(NEW)
    ops = root / "ops"
    ops.mkdir()
    intent = ops / "update-rollback.intent"
    intent.write_text(f"{OLD} {RESTORE_ID}\n")
    intent.chmod(0o600)
    (root / "restore-stage").write_text("completed")
    result, log = run(host, TEST_ROLLBACK_PLAN="none")
    assert result.returncode == 0, result.stderr
    assert "update_control rollback-plan" not in log
    assert "up -d --no-deps backend frontend" in log
    assert not intent.exists()
