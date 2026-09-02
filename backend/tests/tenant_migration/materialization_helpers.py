from contextlib import contextmanager
from datetime import timedelta

from django.apps import apps
from django.db import connection, transaction
from django.utils import timezone

from apps.data_export.runner import build_archive
from apps.encryption.services import get_or_create_active_dek
from apps.events.models import Event, EventRegistration
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import MakerspaceMembership
from apps.tenant_migration.keys import collect_source_keys
from apps.tenant_migration.models import ImportIdentityDecision, TenantImportJob
from apps.tenant_migration.unique_values import DEPLOYMENT_GLOBAL_UNIQUE_RULES
from tests.data_export.portable_helpers import make_job


def _models_with_non_regenerable_identity():
    """Every exported model carrying a value the importer refuses to remint."""
    return [
        apps.get_model(label)
        for (label, _rule), policy in DEPLOYMENT_GLOBAL_UNIQUE_RULES.items()
        if getattr(policy.generator, "refuses_collision", False)
    ]


@contextmanager
def portable_import_case(space, source_user, *, rotate=None, prepare_source=None):
    get_or_create_active_dek(space.pk)
    membership = MakerspaceMembership.objects.create(
        makerspace=space,
        user=source_user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=space.roles.get(slug="member"),
    )
    request = HardwareRequest.objects.create(
        makerspace=space,
        requester=source_user,
        requester_username=source_user.username,
        requester_name="Archive Member",
        requester_contact_email="member@example.test",
        requester_contact_phone="+15550001111",
    )
    event = Event.objects.create(
        makerspace=space,
        title="Portable workshop",
        starts_at=timezone.now() + timedelta(days=1),
        ends_at=timezone.now() + timedelta(days=1, hours=2),
        created_by=source_user,
        registration_requires_approval=True,
        registration_cutoff_lead_minutes=45,
    )
    registration = EventRegistration.objects.create(
        event=event,
        name="Archive Member",
        email="member@example.test",
        phone="+15550001111",
        member=source_user,
        registered_via_makerspace=space,
        payment_via_makerspace=space,
    )
    source_data = (
        prepare_source(space, source_user, request)
        if prepare_source is not None
        else None
    )
    if rotate is not None:
        rotate(space.pk)
    export_job = make_job(space, source_user)
    root, manifest, tempdir = build_archive(export_job, page_size=2, package=False)
    job = TenantImportJob.objects.create(
        source_archive_digest="d" * 64,
        source_makerspace_id=str(space.pk),
        source_makerspace_slug=space.slug,
        source_makerspace_name=space.name,
        source_deployment_id="source-test",
        actor=source_user,
        storage_mode="versioned",
        status=TenantImportJob.Status.READY,
        expires_at=timezone.now() + timedelta(days=1),
    )
    try:
        yield SimpleImportCase(
            root=root,
            manifest=manifest,
            tempdir=tempdir,
            job=job,
            request=request,
            event=event,
            registration=registration,
            membership=membership,
            source_data=source_data,
            carried=collect_source_keys(space),
        )
    finally:
        tempdir.cleanup()


class SimpleImportCase:
    def __init__(self, **values):
        self.__dict__.update(values)

    def release_non_regenerable_identities(self):
        """Make this database stand in for a target deployment, not its own source.

        The archive is built from rows that stay in this one test database and is then
        imported back as if it came from the ``source-test`` deployment. A real import
        never meets its own source — ``pairing`` refuses a same-deployment move — so a
        preserved value the target already holds is a contradiction, and the importer
        is right to stop rather than remint an immutable identity. Drop the local rows
        that carry one, through the same append-only escape hatch a tenant purge uses,
        and the import gets the clean target the protocol actually guarantees it.

        Call this after the source objects are captured and before materialization.
        """
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
            for model in _models_with_non_regenerable_identity():
                model._base_manager.all().delete()

    def decide_walk_in(self, source_user):
        return ImportIdentityDecision.objects.create(
            job=self.job,
            source_user_id=str(source_user.pk),
            source_email=source_user.email,
            identity_resolution=ImportIdentityDecision.IdentityResolution.CREATE_WALK_IN,
            membership_disposition=ImportIdentityDecision.MembershipDisposition.IMPORT_MEMBERSHIP,
        )

    def decide_link(self, source_user, target_user):
        return ImportIdentityDecision.objects.create(
            job=self.job,
            source_user_id=str(source_user.pk),
            source_email=source_user.email,
            identity_resolution=ImportIdentityDecision.IdentityResolution.LINK_EXISTING,
            membership_disposition=ImportIdentityDecision.MembershipDisposition.IMPORT_MEMBERSHIP,
            target_user=target_user,
        )
