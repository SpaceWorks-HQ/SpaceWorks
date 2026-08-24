import pytest

from apps.backup.models import TenantExitCustodyAlarmDelivery
from apps.backup.recipient_states import compromise_recipient, revoke_recipient
from apps.backup.tenant_exit_custody_alarms import required_intents_present_locked
from apps.data_export.models import OMITTED_MODELS
from apps.tenant_migration.models import TenantDumpCapture
from apps.tenant_migration.tenant_dump_capture import request_tenant_dump_capture
from apps.tenant_migration.tenant_dump_cleanup import (
    cleanup_refused_tenant_dump_artifacts,
)
from apps.tenant_migration.tenant_dump_errors import TenantDumpPublicationRefused
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from apps.tenant_migration.tenant_dump_publication import (
    register_unpublished_artifact,
    revalidate_before_encryption,
)
from apps.tenant_migration.tenant_dump_types import ModelDisposition
from tests.tenant_migration.tenant_dump_d3_helpers import (
    makerspace,
    manager,
    recipient,
)


pytestmark = pytest.mark.django_db


def _pending_capture(space, actor):
    capture = request_tenant_dump_capture(actor, space)
    capture.status = TenantDumpCapture.Status.PENDING_PUBLICATION
    capture.unpublished_object_key = f"tenant-dumps/unpublished/{capture.pk}.tar.age"
    capture.save(update_fields=("status", "unpublished_object_key", "updated_at"))
    return capture


@pytest.mark.parametrize("change", ["add", "revoke", "compromise"])
def test_recipient_change_refuses_and_deletes_unpublished_bytes(
    change,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    space = makerspace(f"d3-publish-{change}")
    actor = manager(space)
    first = recipient(space, 10)
    second = recipient(space, 11)
    if change == "revoke":
        recipient(space, 12)
    capture = _pending_capture(space, actor)
    if change == "add":
        recipient(space, 13)
    elif change == "revoke":
        revoke_recipient(recipient=first)
    else:
        compromise_recipient(recipient=second)

    deleted = []
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication.storage.delete_archive",
        lambda key: deleted.append(key) or True,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication._delete_capture_staging",
        lambda _capture_id: None,
    )
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(TenantDumpPublicationRefused, match="changed"):
            revalidate_before_encryption(capture.pk, stage="inner")

    capture.refresh_from_db()
    assert capture.status == TenantDumpCapture.Status.REFUSED
    assert capture.refusal_code == "recipient_changed_before_inner"
    assert capture.unpublished_object_key == ""
    assert deleted == [f"tenant-dumps/unpublished/{capture.pk}.tar.age"]


def test_missing_current_revision_intent_fails_readiness(monkeypatch):
    space = makerspace("d3-missing-intent")
    actor = manager(space)
    recipient(space, 20)
    capture = _pending_capture(space, actor)
    state = space.tenant_exit_custody_state
    TenantExitCustodyAlarmDelivery.objects.filter(
        makerspace=space,
        alarm_revision=state.alarm_revision,
    ).delete()

    assert required_intents_present_locked(state) is False
    monkeypatch.setattr(
        "apps.backup.tenant_exit_custody.ensure_delivery_intents_locked",
        lambda _state: (),
    )
    with pytest.raises(TenantDumpPublicationRefused, match="durable"):
        revalidate_before_encryption(capture.pk, stage="outer")


def test_failed_unpublished_delete_retains_a_durable_retry_key(monkeypatch):
    space = makerspace("d3-delete-retry")
    actor = manager(space)
    recipient(space, 21)
    capture = _pending_capture(space, actor)
    capture.status = TenantDumpCapture.Status.REFUSED
    capture.save(update_fields=("status", "updated_at"))
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_cleanup.storage.delete_archive",
        lambda _key: False,
    )

    assert cleanup_refused_tenant_dump_artifacts() == 0
    capture.refresh_from_db()
    assert capture.unpublished_object_key.endswith(".tar.age")


def test_failed_artifact_registration_journals_an_undeletable_upload(
    monkeypatch, tmp_path
):
    space = makerspace("d3-register-retry")
    actor = manager(space)
    recipient(space, 22)
    capture = _pending_capture(space, actor)
    capture.unpublished_object_key = ""
    capture.save(update_fields=("unpublished_object_key", "updated_at"))
    artifact = tmp_path / "sealed.tar.age"
    artifact.write_bytes(b"sealed")

    original_save = TenantDumpCapture.save
    failed_once = False

    def fail_first_registration(row, *args, **kwargs):
        nonlocal failed_once
        if row.unpublished_object_key and not failed_once:
            failed_once = True
            raise RuntimeError("registration failed")
        return original_save(row, *args, **kwargs)

    monkeypatch.setattr(TenantDumpCapture, "save", fail_first_registration)
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication.storage.upload_archive",
        lambda _key, _path: None,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication.storage.delete_archive",
        lambda _key: False,
    )

    with pytest.raises(RuntimeError, match="registration failed"):
        register_unpublished_artifact(capture.pk, artifact)

    capture.refresh_from_db()
    assert capture.status == TenantDumpCapture.Status.FAILED
    assert capture.refusal_code == "artifact_registration_failed"
    assert capture.unpublished_object_key.endswith(".tar.age")


def test_lane_d_operational_rows_are_drop_disposition():
    labels = {
        "backup.MakerspaceTenantExitCustodyState",
        "backup.TenantExitCustodyAlarmDelivery",
        "tenant_migration.TenantDumpCapture",
    }
    assert labels <= set(OMITTED_MODELS)
    assert all(
        FIRST_PARTY_MODEL_RULES[label].disposition == ModelDisposition.DROP
        for label in labels
    )
