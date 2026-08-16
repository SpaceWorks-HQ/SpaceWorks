import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.events.models import Event
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import install_module, uninstall_module
from apps.makerspaces.module_purge import purge_module
from apps.tenant_migration.models import ExternalTenantReference

pytestmark = pytest.mark.django_db(transaction=True)

DIGEST = "a" * 64
MAKERSPACE_SNAPSHOT = {"name": "Foreign Lab", "slug": "foreign-lab"}
EVENT_SNAPSHOT = {
    "title": "Shared Build Night",
    "starts_at": "2026-08-20T18:00:00+00:00",
    "ends_at": "2026-08-20T20:00:00+00:00",
}


def make_space(slug):
    return Makerspace.objects.create(name=slug.title(), slug=slug)


def make_superadmin(username):
    return User.objects.create_superuser(
        username=username,
        email=f"{username}@example.test",
        password="password",
    )


def reference(makerspace, *, source_object_id, **overrides):
    values = {
        "makerspace": makerspace,
        "source_archive_digest": DIGEST,
        "source_model_label": "events.EventCollaborator",
        "source_object_id": source_object_id,
        "field_name": "event",
        "target_model_label": "events.Event",
        "target_object_id": "42",
        "snapshot": EVENT_SNAPSHOT,
    }
    values.update(overrides)
    return ExternalTenantReference(**values)


def test_anchor_accepts_multiple_collaborators_but_source_identity_is_unique():
    makerspace = make_space("reference-constraints")
    first = reference(makerspace, source_object_id="collaborator-1")
    second = reference(makerspace, source_object_id="collaborator-2")

    first.save()
    second.save()

    assert ExternalTenantReference.objects.filter(
        makerspace=makerspace,
        target_model_label="events.Event",
        target_object_id="42",
    ).count() == 2
    with pytest.raises(ValidationError):
        reference(makerspace, source_object_id="collaborator-1").save()


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "source_model_label": "unknown.Model",
            "field_name": "unknown_field",
            "snapshot": MAKERSPACE_SNAPSHOT,
        },
        {
            "source_model_label": "payments.Payment",
            "field_name": "via_makerspace",
            "snapshot": {"name": "Foreign Lab"},
        },
        {
            "source_model_label": "payments.Payment",
            "field_name": "via_makerspace",
            "snapshot": {**MAKERSPACE_SNAPSHOT, "private_id": 7},
        },
        {
            "source_model_label": "events.EventCollaborator",
            "field_name": "event",
            "snapshot": {**EVENT_SNAPSHOT, "starts_at": 123},
        },
    ],
    ids=["unknown-edge", "missing-key", "unknown-key", "wrong-type"],
)
def test_invalid_snapshot_is_rejected_by_save(overrides):
    makerspace = make_space(f"invalid-{overrides['field_name']}")

    with pytest.raises(ValidationError):
        reference(makerspace, source_object_id="invalid", **overrides).save()


def test_whole_makerspace_purge_explicitly_removes_provenance(monkeypatch):
    makerspace = make_space("reference-whole-purge")
    actor = make_superadmin("reference-whole-purge-admin")
    reference(makerspace, source_object_id="whole-purge").save()
    makerspace.archived_at = timezone.now()
    makerspace.archived_by = actor
    makerspace.save(update_fields=("archived_at", "archived_by"))
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda keys: None)
    monkeypatch.setattr(lifecycle, "_delete_public_image_keys", lambda keys: None)

    lifecycle.purge(makerspace, actor)

    assert not ExternalTenantReference.objects.filter(
        source_object_id="whole-purge"
    ).exists()


def test_module_purge_removes_only_provenance_anchored_to_deleted_models():
    makerspace = make_space("reference-module-purge")
    actor = make_superadmin("reference-module-purge-admin")
    install_module(makerspace, "events")
    now = timezone.now()
    event = Event.objects.create(
        makerspace=makerspace,
        title="Hosted event",
        description="",
        starts_at=now + timezone.timedelta(days=1),
        ends_at=now + timezone.timedelta(days=1, hours=2),
        location="Lab",
        capacity=0,
        is_public=True,
    )
    anchored = reference(
        makerspace,
        source_object_id="event-anchor",
        target_object_id=str(event.pk),
    )
    anchorless = reference(
        makerspace,
        source_object_id="anchorless",
        target_model_label="",
        target_object_id="",
    )
    other_module = reference(
        makerspace,
        source_object_id="booking-anchor",
        target_model_label="bookings.BookableSpace",
        target_object_id="99",
    )
    for item in (anchored, anchorless, other_module):
        item.save()
    uninstall_module(makerspace, "events")

    purge_module(makerspace, "events", actor)

    assert not ExternalTenantReference.objects.filter(pk=anchored.pk).exists()
    assert ExternalTenantReference.objects.filter(pk=anchorless.pk).exists()
    assert ExternalTenantReference.objects.filter(pk=other_module.pk).exists()
