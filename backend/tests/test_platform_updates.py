import re
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.updates import services
from apps.updates.models import PlatformUpdateSettings
from tests.return_helpers import authenticated_client, make_user

pytestmark = pytest.mark.django_db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def superadmin(name="updates-superadmin"):
    return make_user(
        name,
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )


def test_update_settings_are_superadmin_only_and_toggle_is_audited():
    regular = make_user("updates-regular", access_status=User.AccessStatus.ACTIVE)
    root = superadmin()
    url = reverse("admin-platform-update-settings")

    assert authenticated_client(regular).get(url).status_code == 403

    client = authenticated_client(root)
    response = client.patch(
        url,
        {"automatic_updates_enabled": True, "status": "running"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["automatic_updates_enabled"] is True
    assert response.data["status"] == PlatformUpdateSettings.Status.IDLE
    event = AuditLog.objects.get(action="platform.update_settings_updated")
    assert event.actor == root
    assert event.meta == {"automatic_updates_enabled": True}


def test_update_now_queues_audited_request():
    root = superadmin("updates-queue-superadmin")
    response = authenticated_client(root).post(
        reverse("admin-platform-update-now"),
        format="json",
    )

    assert response.status_code == 202
    assert response.data["status"] == PlatformUpdateSettings.Status.QUEUED
    assert response.data["update_requested_at"] is not None
    assert AuditLog.objects.filter(
        actor=root,
        action="platform.update_requested",
    ).exists()


def test_automatic_updates_can_be_turned_off():
    settings = PlatformUpdateSettings.load()
    settings.automatic_updates_enabled = True
    settings.save(update_fields=("automatic_updates_enabled", "updated_at"))
    root = superadmin("updates-off-superadmin")

    response = authenticated_client(root).patch(
        reverse("admin-platform-update-settings"),
        {"automatic_updates_enabled": False},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["automatic_updates_enabled"] is False
    assert services.claim_update(
        current_version="0.5.0-main.1.aaaaaaaaaaaa",
        available_version="0.5.0-main.2.bbbbbbbbbbbb",
    ) is False
    event = AuditLog.objects.get(action="platform.update_settings_updated")
    assert event.meta == {"automatic_updates_enabled": False}


def test_host_claim_respects_toggle_and_manual_queue():
    settings = PlatformUpdateSettings.load()

    assert services.claim_update(
        current_version="0.5.0-main.1.aaaaaaaaaaaa",
        available_version="0.5.0-main.2.bbbbbbbbbbbb",
    ) is False

    services.queue_update()
    assert services.claim_update(
        current_version="0.5.0-main.1.aaaaaaaaaaaa",
        available_version="0.5.0-main.2.bbbbbbbbbbbb",
    ) is True
    settings.refresh_from_db()
    assert settings.status == PlatformUpdateSettings.Status.RUNNING
    assert settings.target_version == "0.5.0-main.2.bbbbbbbbbbbb"
    assert settings.update_requested_at is None


def test_backup_and_completion_status_are_safe_for_display():
    services.record_backup("../../pre-update-20260723T100000Z.sql.gz")
    services.complete_update("0.5.0-main.2.bbbbbbbbbbbb")
    settings = PlatformUpdateSettings.load()

    assert settings.last_backup_name == "pre-update-20260723T100000Z.sql.gz"
    assert settings.last_backup_at is not None
    assert settings.status == PlatformUpdateSettings.Status.IDLE
    assert settings.current_version == "0.5.0-main.2.bbbbbbbbbbbb"
    assert settings.last_updated_at is not None


def test_update_control_command_enables_and_claims_updates():
    output = StringIO()
    call_command("update_control", "set-auto", "on", stdout=output)
    call_command(
        "update_control",
        "claim",
        "--current=0.5.0-main.1.aaaaaaaaaaaa",
        "--available=0.5.0-main.2.bbbbbbbbbbbb",
        "--force",
        stdout=output,
    )

    settings = PlatformUpdateSettings.load()
    assert settings.automatic_updates_enabled is True
    assert settings.status == PlatformUpdateSettings.Status.RUNNING
    assert output.getvalue().splitlines() == ["on", "run"]


# --------------------------------------------------------------------------
# The failure leg, and the recovery from it (plan Track D, phase 15).
# --------------------------------------------------------------------------

def test_a_failed_update_is_recorded_and_leaves_no_target_behind():
    """A half-finished update must not read as one still in progress.

    `target_version` is what the host updater acts on, so a failure that left it set
    would describe a release the deployment is not running and is not moving towards.
    """
    services.claim_update(
        current_version="0.5.0-main.1.aaaaaaaaaaaa",
        available_version="0.5.0-main.2.bbbbbbbbbbbb",
        force=True,
    )

    services.fail_update("  migrate exited 1: relation already exists  ")
    settings = PlatformUpdateSettings.load()

    assert settings.status == PlatformUpdateSettings.Status.FAILED
    assert settings.target_version == ""
    assert settings.last_error == "migrate exited 1: relation already exists"
    assert settings.current_version == "0.5.0-main.1.aaaaaaaaaaaa"


def test_a_failure_message_cannot_grow_without_bound():
    """The updater pipes real stderr in, and this row is rendered in the console."""
    services.fail_update("x" * 5000)

    assert len(PlatformUpdateSettings.load().last_error) == 500


def test_a_failed_update_can_be_retried_and_the_error_is_cleared():
    """FAILED is a resting state, not a dead end: queueing again must be enough."""
    services.fail_update("network unreachable")

    services.queue_update()
    queued = PlatformUpdateSettings.load()
    assert queued.status == PlatformUpdateSettings.Status.QUEUED
    assert queued.last_error == ""

    assert services.claim_update(
        current_version="0.5.0-main.1.aaaaaaaaaaaa",
        available_version="0.5.0-main.2.bbbbbbbbbbbb",
    ) is True
    assert PlatformUpdateSettings.load().status == PlatformUpdateSettings.Status.RUNNING


def test_the_host_updater_round_trip_runs_entirely_through_the_command():
    """The full sequence scripts/update.sh drives: claim, back up, then fail or finish.

    Every transition has to be reachable from the CLI, because the privileged host
    updater is the only thing allowed to drive them -- see the Docker-socket tests below.
    """
    output = StringIO()
    for args in (
        ("claim", "--current=0.5.0-main.1.aaaaaaaaaaaa",
         "--available=0.5.0-main.2.bbbbbbbbbbbb", "--force"),
        ("record-backup", "--name=/var/backups/pre-update-20260808T100000Z.sql.gz"),
        ("fail", "--message=compose up exited 1"),
    ):
        call_command("update_control", *args, stdout=output)

    failed = PlatformUpdateSettings.load()
    assert failed.status == PlatformUpdateSettings.Status.FAILED
    assert failed.last_backup_name == "pre-update-20260808T100000Z.sql.gz"

    call_command("update_control", "complete", "--version=0.5.0-main.2.bbbbbbbbbbbb", stdout=output)
    finished = PlatformUpdateSettings.load()

    assert finished.status == PlatformUpdateSettings.Status.IDLE
    assert finished.current_version == "0.5.0-main.2.bbbbbbbbbbbb"
    assert finished.last_error == ""
    assert output.getvalue().splitlines() == ["run", "recorded", "failed", "complete"]


# --------------------------------------------------------------------------
# The privilege boundary: the web process never gets the Docker socket.
# --------------------------------------------------------------------------
#
# This is the reason the update path is split in two at all. Restarting containers means
# talking to the Docker daemon, and the daemon socket is root-equivalent on the host: a
# container holding it can start a privileged container mounting `/`. So the web process,
# which is the part exposed to the internet, only ever writes rows -- `update_control`
# turns those rows into actions from a privileged *host* script that was never reachable
# from a request. An RCE in Django then buys the attacker the database, which is bad, and
# not the host, which is worse.
#
# These guard the shape of that split rather than any one line of it, because the tempting
# regression is small and looks helpful: mounting the socket "just for the updater", or
# shelling out to `docker compose restart` from a view to save the operator a step.

def _compose_files():
    return sorted(REPO_ROOT.glob("docker-compose*.yml"))


def test_no_compose_file_hands_a_django_service_the_docker_socket():
    offenders = [
        path.name
        for path in _compose_files()
        if "docker.sock" in path.read_text(encoding="utf-8-sig")
    ]

    assert not offenders, (
        f"{offenders} mount the Docker daemon socket. It is root-equivalent on the host, "
        f"so a container holding it can escape to the host -- which is why updates are "
        f"applied by scripts/update.sh and the web process only records state."
    )


def test_the_web_process_never_shells_out_to_docker():
    """The application may describe an update; only the host script may perform one."""
    docker_call = re.compile(r"""["']docker\b|\bdocker\s+compose\b|docker_client|from\s+docker\b""")
    offenders, scanned = [], 0
    for path in (REPO_ROOT / "backend" / "apps").rglob("*.py"):
        if any(part in {"__pycache__", "migrations"} for part in path.parts):
            continue
        scanned += 1
        if docker_call.search(path.read_text(encoding="utf-8-sig")):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert scanned > 100, f"only scanned {scanned} files -- the walk is not finding apps/"
    assert docker_call.search("subprocess.run(['docker', 'compose', 'up'])"), (
        "the pattern no longer recognises a docker invocation, so this test proves nothing"
    )
    assert not offenders, (
        f"{offenders} invoke Docker from application code. The web process has no socket "
        f"to reach it with, so this cannot work in a real deployment even if it passes "
        f"locally -- put the action in scripts/update.* and drive it from update_control."
    )


def test_the_host_script_is_the_thing_that_drives_docker():
    """The negative tests above are only meaningful if the work happens somewhere."""
    script = (REPO_ROOT / "scripts" / "update.sh").read_text(encoding="utf-8-sig")

    assert "docker compose" in script
    assert "update_control" in script
