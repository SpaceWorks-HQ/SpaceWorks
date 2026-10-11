import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.models import BackupArchive, DeploymentRecoveryState, RestoreOperation
from apps.updates import services
from apps.updates.errors import UpdateRefused
from apps.updates.models import PlatformUpdateSettings
from apps.updates.rollback import rollback_plan
from tests.return_helpers import authenticated_client, make_user

pytestmark = pytest.mark.django_db
OLD = "0.5.0-main.1.aaaaaaaaaaaa"
NEW = "0.5.0-main.2.bbbbbbbbbbbb"


@pytest.fixture
def restore_point():
    archive = BackupArchive.objects.create(
        scope="deployment", status="available", object_key=f"backups/{uuid.uuid4()}.tar.age",
        age_encrypted=True, completed_at=timezone.now(), expires_at=timezone.now() + timedelta(days=14),
        archive_sha256="a" * 64, manifest={"format": "spaceworks-phase5a-v3", "partial": False},
    )
    row = PlatformUpdateSettings.load()
    row.current_version = NEW
    row.pre_update_version = OLD
    row.pre_update_archive = archive
    row.save()
    actor = make_user("rollback-root", role=User.Role.SUPERADMIN, access_status="active")
    return row, archive, actor


def payload(row, **changes):
    return {
        "archive_id": str(row.pre_update_archive_id) if row.pre_update_archive_id else None,
        "confirm_version": row.pre_update_version, "confirm_data_loss": True, **changes,
    }


def post(actor, body):
    return authenticated_client(actor).post(reverse("admin-platform-update-rollback"), body, format="json")


def test_legacy_database_only_backup_has_a_typed_no_snapshot_refusal():
    row = services.record_backup("pre-update-legacy.sql.gz")
    actor = make_user("legacy-rollback-root", role=User.Role.SUPERADMIN, access_status="active")
    with patch("apps.backup.restore_services.request_restore") as restore:
        response = post(actor, payload(row))
    assert response.status_code == 400 and response.data["reason"] == "no_snapshot"
    restore.assert_not_called()
    assert not AuditLog.objects.filter(action="platform.update_rollback_requested").exists()


@pytest.mark.parametrize("changes,reason", [
    ({"status": "failed"}, "snapshot_unavailable"),
    ({"expires_at": timezone.now() - timedelta(seconds=1)}, "snapshot_unavailable"),
    ({"age_encrypted": False}, "snapshot_unverified"),
    ({"archive_sha256": ""}, "snapshot_unverified"),
    ({"completed_at": None}, "snapshot_unverified"),
    ({"manifest": {"format": "spaceworks-phase5a-v3", "partial": True}}, "snapshot_unsupported"),
    ({"manifest": {"format": "unknown", "partial": False}}, "snapshot_unsupported"),
    ({"manifest": {"format": "spaceworks-phase5a-v3", "partial": False,
                   "protocol_version": "spaceworks-lane-e-b1-v1"}}, "snapshot_unsupported"),
])
def test_rollback_refuses_unavailable_unverified_and_compound_snapshots(restore_point, changes, reason):
    row, archive, actor = restore_point
    for field, value in changes.items():
        setattr(archive, field, value)
    if "expires_at" in changes:
        # Available archive expiry is immutable; simulate elapsed retention instead.
        archive.refresh_from_db()
        expiry_time = archive.expires_at + timedelta(seconds=1)
    else:
        archive.save()
        expiry_time = timezone.now()
    with patch("apps.updates.rollback.timezone.now", return_value=expiry_time), patch("apps.backup.restore_services.request_restore") as restore:
        response = post(actor, payload(row))
    assert response.status_code == 400 and response.data["reason"] == reason
    restore.assert_not_called()
    row.refresh_from_db()
    assert row.rollback_restore_id is None


def test_an_untracked_previous_image_refuses_rollback(restore_point):
    row, _, actor = restore_point
    row.pre_update_version = ""
    row.save()
    response = post(actor, payload(row))
    assert response.status_code == 400 and response.data["reason"] == "no_previous_version"


@pytest.mark.parametrize("changes", [
    {"confirm_data_loss": False}, {"confirm_version": NEW}, {"archive_id": str(uuid.uuid4())},
])
def test_rollback_requires_confirmation_of_the_exact_displayed_restore_point(restore_point, changes):
    row, _, actor = restore_point
    with patch("apps.backup.restore_services.request_restore") as restore:
        response = post(actor, payload(row, **changes))
    assert response.status_code == 400 and response.data["reason"] == "confirmation_mismatch"
    restore.assert_not_called()


def test_rollback_requires_confirmation_fields_at_the_boundary(restore_point):
    _, _, actor = restore_point
    response = post(actor, {})
    assert response.status_code == 400 and response.data["reason"] == "invalid_confirmation"
    assert not RestoreOperation.objects.exists()


@pytest.mark.parametrize("status", ["running", "queued"])
def test_rollback_refuses_an_update_in_progress(restore_point, status):
    row, _, actor = restore_point
    row.status = status
    row.save()
    response = post(actor, payload(row))
    assert response.status_code == 400 and response.data["reason"] == "update_busy"


def test_rollback_uses_the_existing_restore_boundary_and_is_idempotent(restore_point):
    row, archive, actor = restore_point
    restore = RestoreOperation.objects.create(archive=archive, kind="rollback_in_place", requested_by=actor)
    with patch("apps.backup.restore_services.request_restore", return_value=restore) as request_restore:
        first = post(actor, payload(row))
        repeated = post(actor, payload(row))
    assert first.status_code == repeated.status_code == 202
    assert first.data["id"] == repeated.data["id"] == str(restore.pk)
    request_restore.assert_called_once_with(actor, archive, RestoreOperation.Kind.ROLLBACK_IN_PLACE)
    row.refresh_from_db()
    assert row.rollback_restore_id == restore.pk and row.current_version == NEW
    assert rollback_plan() == (OLD, restore.pk)
    event = AuditLog.objects.get(action="platform.update_rollback_requested")
    assert event.actor == actor and event.meta["archive_id"] == str(archive.pk)
    with pytest.raises(UpdateRefused):
        services.queue_update()


def test_another_active_restore_is_refused_by_the_existing_service(restore_point):
    row, archive, actor = restore_point
    DeploymentRecoveryState.load()
    RestoreOperation.objects.create(archive=archive, kind="rollback_in_place", requested_by=actor)
    response = post(actor, payload(row))
    assert response.status_code == 400 and response.data["reason"] == "restore_refused"
    assert not AuditLog.objects.filter(action="platform.update_rollback_requested").exists()


def test_restore_boundary_refusal_does_not_write_the_update_link_or_audit(restore_point):
    row, _, actor = restore_point
    with patch("apps.backup.restore_services.request_restore", side_effect=ValidationError("Recovery active")):
        response = post(actor, payload(row))
    assert response.status_code == 400 and response.data["reason"] == "restore_refused"
    row.refresh_from_db()
    assert row.rollback_restore_id is None
    assert not AuditLog.objects.filter(action="platform.update_rollback_requested").exists()


def test_rollback_with_the_real_request_service_only_records_intent_and_both_audits(restore_point):
    row, _, actor = restore_point
    response = post(actor, payload(row))
    assert response.status_code == 202 and response.data["stage"] == "requested"
    assert AuditLog.objects.filter(action="backup.restore_requested", actor=actor).exists()
    assert AuditLog.objects.filter(action="platform.update_rollback_requested", actor=actor).exists()
    row.refresh_from_db()
    assert row.current_version == NEW  # No host effect in the web process.


@pytest.mark.parametrize("stage", ["completed", "restored_quarantined"])
def test_completed_rollback_cannot_be_requested_again(restore_point, stage):
    row, archive, actor = restore_point
    row.rollback_restore = RestoreOperation.objects.create(
        archive=archive, kind="rollback_in_place", requested_by=actor, stage=stage,
    )
    row.save()
    with patch("apps.backup.restore_services.request_restore") as request_restore:
        response = post(actor, payload(row))
    assert response.status_code == 400 and response.data["reason"] == "rollback_completed"
    request_restore.assert_not_called()


@pytest.mark.parametrize("stage", ["failed", "aborted"])
def test_failed_or_aborted_rollback_can_be_requested_again(restore_point, stage):
    row, archive, actor = restore_point
    row.rollback_restore = RestoreOperation.objects.create(
        archive=archive, kind="rollback_in_place", requested_by=actor, stage=stage,
    )
    row.save()
    response = post(actor, payload(row))
    assert response.status_code == 202 and response.data["stage"] == "requested"
    assert response.data["id"] != str(row.rollback_restore_id)


def test_active_rollback_blocks_channel_change_and_host_claim(restore_point):
    row, archive, actor = restore_point
    row.rollback_restore = RestoreOperation.objects.create(
        archive=archive, kind="rollback_in_place", requested_by=actor,
    )
    row.save()
    response = authenticated_client(actor).patch(
        reverse("admin-platform-update-settings"), {"channel": "beta"}, format="json",
    )
    assert response.status_code == 400 and response.data["reason"] == "rollback_active"
    with pytest.raises(UpdateRefused):
        services.claim_update(current_version=OLD, available_version=NEW, force=True)
    row.refresh_from_db()
    assert row.channel == "stable" and row.status == "idle"
