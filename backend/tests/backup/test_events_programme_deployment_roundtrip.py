"""Deployment backup/restore coverage for the phase 1-9 programme graph."""

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.backup import archive_builder, storage as backup_storage
from apps.backup.projection_databases import restore_dump, temporary_database
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.evidence.models import EvidenceObjectRetentionState
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces import archive_requests, module_purge
from apps.makerspaces.models import (
    Makerspace, MakerspaceArchiveRequest, MakerspaceMembership, MemberProfile,
)
from tests.backup.test_compound_archive_e3 import (
    _archive,
    _prepare,
    _sovereign,
    allow_projection_databases,
)
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.programme_graph import create_programme_graph


pytestmark = pytest.mark.django_db(transaction=True)
OBJECT_BYTES = b"%PDF-1.7\nprogramme deployment artifact\n%%EOF\n"

PHASE_LABELS = (
    "events.EventSeries", "events.Event", "events.EventRegistration",
    "events.EventCheckInEvent", "events.EventFeedbackSurvey",
    "events.EventFeedbackResponse", "events.EventAttendanceCertificate",
    "events.EventSeriesOrganizer", "events.EventOrganizer",
    "events.MemberCalendarFeed", "events.EventCheckInStationCredential",
    "organizations.Organization", "organizations.OrganizationMakerspace",
    "organizations.OrganizationMembership", "organizations.OrganizationInvitation",
    "operations.ReportMetricRollup", "operations.ReportRollupCursor",
    "evidence.EvidencePhoto", "evidence.EvidenceRetentionPolicy",
    "evidence.EvidenceObjectRetentionState", "payments.Payment", "audit.AuditLog",
    "bookings.BookableSpace", "bookings.Booking", "makerspaces.MemberProfile",
)


def _source_graph(slug):
    user = get_user_model().objects.create_user(
        username=f"{slug}-manager", email=f"{slug}@example.test",
        role=get_user_model().Role.SPACE_MANAGER, is_staff=True,
    )
    space = Makerspace.objects.create(
        name=slug, slug=slug, superadmin_access_enabled=True,
        enabled_modules=["membership", "events", "bookings", "reports"],
    )
    membership = MakerspaceMembership.objects.create(
        makerspace=space, user=user, role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    MemberProfile.objects.create(
        membership=membership, is_visible=True, show_attended_events=True,
        headline="Programme mentor",
    )
    bookable = BookableSpace.objects.create(
        makerspace=space, name="Training bench", capacity=4, created_by=user,
    )
    Booking.objects.create(
        space=bookable, name="Archive Member", email=user.email,
        phone="+15550001111", member=user,
        starts_at=timezone.now() + timedelta(days=2),
        ends_at=timezone.now() + timedelta(days=2, hours=1),
    )
    request = HardwareRequest.objects.create(
        makerspace=space, requester=user, requester_username=user.username,
        requester_name="Archive Member", requester_contact_email=user.email,
    )
    Event.objects.create(
        makerspace=space, title="Portable workshop",
        starts_at=timezone.now() + timedelta(days=1),
        ends_at=timezone.now() + timedelta(days=1, hours=2), created_by=user,
    )
    EventRegistration.objects.create(
        event=space.events.get(), name="Archive Member", email=user.email,
        phone="+15550001111", member=user,
        registered_via_makerspace=space, payment_via_makerspace=space,
    )
    return space, user, create_programme_graph(space, user, request)


def _rows(space_id):
    from django.apps import apps

    rows = {}
    for label in PHASE_LABELS:
        model = apps.get_model(label)
        if label == "organizations.Organization":
            queryset = model.objects.filter(makerspace_links__makerspace_id=space_id)
        elif label.startswith("organizations."):
            lookup = {
                "organizations.OrganizationMakerspace": "makerspace_id",
                "organizations.OrganizationMembership": "organization__makerspace_links__makerspace_id",
                "organizations.OrganizationInvitation": "organization__makerspace_links__makerspace_id",
            }[label]
            queryset = model.objects.filter(**{lookup: space_id})
        elif label == "events.EventOrganizer":
            queryset = model.objects.filter(event__makerspace_id=space_id)
        elif label == "events.EventSeriesOrganizer":
            queryset = model.objects.filter(series__makerspace_id=space_id)
        elif label == "events.MemberCalendarFeed":
            queryset = model.objects.filter(membership__makerspace_id=space_id)
        elif label == "events.EventCheckInStationCredential":
            queryset = model.objects.filter(event__makerspace_id=space_id)
        elif label.startswith("events.EventFeedback"):
            lookup = {
                "events.EventFeedbackSurvey": "event__makerspace_id",
                "events.EventFeedbackResponse": "survey__event__makerspace_id",
            }[label]
            queryset = model.objects.filter(**{lookup: space_id})
        elif label == "events.EventAttendanceCertificate":
            queryset = model.objects.filter(registration__event__makerspace_id=space_id)
        elif label == "bookings.Booking":
            queryset = model.objects.filter(space__makerspace_id=space_id)
        elif label == "makerspaces.MemberProfile":
            queryset = model.objects.filter(membership__makerspace_id=space_id)
        elif label == "events.EventRegistration":
            queryset = model.objects.filter(event__makerspace_id=space_id)
        elif label == "events.EventSeries":
            queryset = model.objects.filter(makerspace_id=space_id)
        elif label == "evidence.EvidenceObjectRetentionState":
            queryset = model.objects.filter(evidence__makerspace_id=space_id)
        else:
            queryset = model.objects.filter(makerspace_id=space_id)
        rows[label] = list(queryset.order_by(model._meta.pk.name).values())
    return rows


def test_deployment_restore_preserves_disabled_archived_graph_and_two_key_request(
    allow_projection_databases, monkeypatch, settings
):
    with enabled_encryption():
        space, manager, _graph = _source_graph("programme-deployment")
        # Uninstall is retention-only: the data remains but the module state stays OFF.
        space.enabled_modules = []
        space.save(update_fields=("enabled_modules",))
        resolver = get_user_model().objects.create_superuser(
            username="programme-resolver", email="resolver@example.test", password="pw"
        )
        monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
        monkeypatch.setattr(archive_requests, "schedule_resolved", lambda _pk: None)
        request = archive_requests.create(space, manager, "Lease ended.")
        archive_requests.approve(request, resolver, "Independent approval.")
        # approve() stamps archived_at in the database; the local object is stale.
        space.refresh_from_db()
        expected = _rows(space.pk)

        # A second tenant takes the destructive path. Its archive must not recreate
        # the event graph (or the rollup derived from it) after restore.
        purged_space, _purged_manager, _ = _source_graph("programme-purged")
        purged_space.enabled_modules = []
        purged_space.save(update_fields=("enabled_modules",))
        settings.MANAGED_POSTGRES = True
        monkeypatch.setattr(module_purge, "_delete_private_keys", lambda keys: keys)
        monkeypatch.setattr(module_purge, "_free_private_storage", lambda *_args: None)
        monkeypatch.setattr(
            module_purge, "_delete_public_images_and_free_storage", lambda *_args: None
        )
        module_purge.purge_module(purged_space, "events", resolver)
        module_purge.purge_module(purged_space, "bookings", resolver)
        module_purge.purge_module(purged_space, "membership", resolver)
        assert not Event.objects.filter(makerspace=purged_space).exists()
        assert not BookableSpace.objects.filter(makerspace=purged_space).exists()
        assert not MemberProfile.objects.filter(
            membership__makerspace=purged_space
        ).exists()

        # A deployment archive is a COMPOUND archive: the readable main is derived by
        # excluding tenants that hold their own custody, and the source verifier proves
        # main + slices == the full dump. Give the run one sovereign tenant so this test
        # exercises that supported shape. (A deployment with NO sovereign tenant — the
        # default, since superadmin_access_enabled starts True — cannot build a
        # deployment archive at all today; that gap is tracked separately and is not
        # what this test is for.)
        _sovereign()
        _prepare(monkeypatch, settings)
        # Capture the object bytes for real against a fake bucket. Stubbing capture out
        # cannot work on the compound path: the ownership plan is built from the rows
        # themselves, and bind_component proves the manifest EQUALS that closure, so an
        # empty manifest is a mismatch rather than a shortcut. Expired evidence needs no
        # bytes -- it is captured as a tombstone and asserted absent from the bucket.
        def _download(_bucket, key, destination, *, versioned):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(OBJECT_BYTES)
            return {
                "key": key,
                "version_id": "programme-v1",
                "size": len(OBJECT_BYTES),
                "sha256": hashlib.sha256(OBJECT_BYTES).hexdigest(),
                "metadata": {},
                "content_type": "application/octet-stream",
                "headers": {},
            }

        absent = []
        monkeypatch.setattr(backup_storage, "download_object", _download)
        monkeypatch.setattr(
            backup_storage,
            "assert_object_absent",
            lambda _bucket, key: absent.append(key),
        )
        _sealed, _manifest, tempdir, _digest = archive_builder.build_archive(_archive())
        # Expired evidence travels as a tombstone, and capture has to PROVE no bytes
        # survive it -- under the final key and under the staging key a presign writes.
        expired_keys = list(
            EvidenceObjectRetentionState.objects.filter(
                status=EvidenceObjectRetentionState.Status.EXPIRED
            ).values_list("evidence__object_key", flat=True)
        )
        assert len(expired_keys) == 2
        assert sorted(absent) == sorted(
            key for base in expired_keys for key in (base, f"staging/{base}")
        )
        try:
            dump = Path(tempdir.name, "bundle", "database.dump")
            with temporary_database("programme_restore") as (using, database_name):
                restore_dump(dump, database_name)
                restored = Makerspace.objects.using(using).get(pk=space.pk)
                assert restored.enabled_modules == []
                assert restored.archived_at == space.archived_at
                archived_request = MakerspaceArchiveRequest.objects.using(using).get(pk=request.pk)
                assert archived_request.status == MakerspaceArchiveRequest.Status.APPROVED
                assert archived_request.requested_by_id == manager.pk
                assert archived_request.resolved_by_id == resolver.pk
                assert not Event.objects.using(using).filter(
                    makerspace_id=purged_space.pk
                ).exists()
                assert not BookableSpace.objects.using(using).filter(
                    makerspace_id=purged_space.pk
                ).exists()
                assert not MemberProfile.objects.using(using).filter(
                    membership__makerspace_id=purged_space.pk
                ).exists()
                from apps.operations.models import ReportMetricRollup
                assert not ReportMetricRollup.objects.using(using).filter(
                    makerspace_id=purged_space.pk, source_module="events"
                ).exists()
                from django.apps import apps
                for label, source_rows in expected.items():
                    model = apps.get_model(label)
                    target_rows = list(model.objects.using(using).filter(
                        pk__in=[row[model._meta.pk.attname] for row in source_rows]
                    ).order_by(model._meta.pk.name).values())
                    assert target_rows == source_rows, label
        finally:
            tempdir.cleanup()
