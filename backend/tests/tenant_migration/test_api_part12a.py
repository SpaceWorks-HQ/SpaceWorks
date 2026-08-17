from datetime import timedelta
import uuid

import pytest
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from rest_framework.test import APIClient
from drf_spectacular.generators import SchemaGenerator

from apps.accounts.models import User
from apps.data_export.models import DataExportJob
from apps.data_export.models import MODELS
from apps.data_export.fields import FIELDS
from apps.data_export.types import Fidelity, OmittedModel, Redacted, Remapped
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.tenant_migration.models import (
    DisclosureClosureApproval,
    TenantImportJob,
    TenantMigrationExportJob,
)
from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS
from apps.tenant_migration.services_import_job import CLEANUP_LEASE_NAME

pytestmark = pytest.mark.django_db


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_manage_makerspace_cannot_request_portable_or_issue_its_download_token():
    space = Makerspace.objects.create(name="Portable Auth", slug="portable-auth")
    manager = User.objects.create_user(
        username="portable-manager", access_status=User.AccessStatus.ACTIVE
    )
    MakerspaceMembership.objects.create(
        makerspace=space, user=manager,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    approval = DisclosureClosureApproval.objects.create(
        makerspace=space, closure_digest="a" * 64,
        identity_ids=[], approved_identity_ids=[], approved_by=manager,
    )
    export = DataExportJob.objects.create(
        makerspace=space, requested_by=manager, fidelity="PORTABLE",
        status=DataExportJob.Status.AVAILABLE,
        object_key=f"tenant-migrations/{space.pk}/auth.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )
    TenantMigrationExportJob.objects.create(
        export_job=export, disclosure_approval=approval,
        closure_digest=approval.closure_digest,
        target_age_recipient="age1targetrecipient000000000000",
    )
    redacted = DataExportJob.objects.create(
        makerspace=space, requested_by=manager, fidelity="REDACTED",
        status=DataExportJob.Status.AVAILABLE,
        object_key=f"data-exports/{space.pk}/manager-redacted.zip",
        expires_at=timezone.now() + timedelta(days=1),
    )
    client = client_for(manager)

    create = client.post(
        reverse("tenant-migration-exports", args=(space.pk,)),
        {"approval_id": str(approval.pk), "target_age_recipient": "age1targetrecipient000000000000"},
        format="json",
    )
    token = client.post(reverse("data-export-download-url", args=(space.pk, export.pk)))
    detail = client.get(reverse("data-export-detail", args=(space.pk, export.pk)))
    listing = client.get(reverse("data-export-list-create", args=(space.pk,)))

    assert create.status_code == 403
    assert token.status_code == 403
    assert detail.status_code == 403
    assert [row["id"] for row in listing.data] == [str(redacted.pk)]


def test_import_run_endpoint_claims_the_job_only_once(monkeypatch):
    actor = User.objects.create_superuser(
        username="import-run-root", password="test-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    job = TenantImportJob.objects.create(
        source_archive_digest="a" * 64,
        status=TenantImportJob.Status.READY,
        expires_at=timezone.now() + timedelta(days=1),
    )
    queued = []
    monkeypatch.setattr(
        "apps.tenant_migration.views_import.run_import_job_task.delay",
        lambda *args: queued.append(args),
    )
    client = client_for(actor)
    path = reverse("tenant-migration-import-run", args=(job.pk,))

    first = client.post(path, {}, format="json")
    second = client.post(path, {}, format="json")

    assert first.status_code == 202
    assert first.data["status"] == TenantImportJob.Status.MATERIALIZING
    assert len(queued) == 1
    assert second.status_code == 409
    assert second.data == {
        "detail": "The import is not ready to run.",
        "code": "import_state_conflict",
    }


def test_deployment_identity_exposes_only_the_target_public_age_recipient(
    monkeypatch, settings,
):
    actor = User.objects.create_superuser(
        username="target-identity-root", password="test-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    settings.TENANT_MIGRATION_AGE_RECIPIENT = "age1targetrecipient000000000000"
    settings.TENANT_MIGRATION_AGE_IDENTITY_FILE = "/private/target-age-identity.txt"
    monkeypatch.setattr(
        "apps.tenant_migration.views_cutover.public_deployment_identity",
        lambda: {
            "algorithm": "ed25519",
            "deployment_id": "target-deployment",
            "public_key": "p" * 44,
            "fingerprint": "f" * 64,
        },
    )

    response = client_for(actor).get(
        reverse("tenant-migration-deployment-identity")
    )

    assert response.status_code == 200
    assert response.data["age_recipient"] == settings.TENANT_MIGRATION_AGE_RECIPIENT
    assert settings.TENANT_MIGRATION_AGE_IDENTITY_FILE not in str(response.data)


def test_quiesce_endpoint_reasserts_the_archive_gate_lease(monkeypatch):
    actor = User.objects.create_superuser(
        username="source-gate-root",
        password="test-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    space = Makerspace.objects.create(name="Source Gate API", slug="source-gate-api")
    approval = DisclosureClosureApproval.objects.create(
        makerspace=space,
        closure_digest="a" * 64,
        identity_ids=[],
        approved_identity_ids=[],
        approved_by=actor,
    )
    owner_id = uuid.uuid4()
    export = DataExportJob.objects.create(
        makerspace=space,
        requested_by=actor,
        fidelity="PORTABLE",
        status=DataExportJob.Status.AVAILABLE,
        object_key=f"tenant-migrations/{space.pk}/gate.tar.age",
        manifest={
            "source": {
                "gate": {"owner_id": str(owner_id), "fencing_token": 7}
            }
        },
        expires_at=timezone.now() + timedelta(days=1),
    )
    TenantMigrationExportJob.objects.create(
        export_job=export,
        disclosure_approval=approval,
        closure_digest=approval.closure_digest,
        target_age_recipient="age1targetrecipient000000000000",
        archive_digest="b" * 64,
    )
    lease = object()
    calls = []

    def claim(claimed_space, claimed_actor, **authority):
        calls.append((claimed_space, claimed_actor, authority))
        return lease

    monkeypatch.setattr(
        "apps.tenant_migration.services_export_job.source_gate.claim", claim
    )
    monkeypatch.setattr(
        "apps.tenant_migration.services_export_job.source_gate.heartbeat",
        lambda claimed_lease: calls.append(("heartbeat", claimed_lease)) or lease,
    )

    response = client_for(actor).post(
        reverse("tenant-migration-source-quiesce", args=(space.pk, export.pk)),
        {},
        format="json",
    )

    assert response.status_code == 200
    assert calls == [
        (
            space,
            actor,
            {"owner_id": owner_id, "fencing_token": 7},
        ),
        ("heartbeat", lease),
    ]


def test_openapi_documents_every_part12a_route():
    paths = SchemaGenerator().get_schema(request=None, public=True)["paths"]
    expected = {
        "/api/v1/admin/platform/tenant-migrations/deployment-identity": {"get"},
        "/api/v1/admin/platform/tenant-migrations/pairings": {"get", "post"},
        "/api/v1/admin/platform/tenant-migrations/imports": {"get", "post"},
        "/api/v1/admin/platform/tenant-migrations/imports/{job_id}": {"get"},
        "/api/v1/admin/platform/tenant-migrations/imports/{job_id}/identity-decisions": {"get", "post"},
        "/api/v1/admin/platform/tenant-migrations/imports/{job_id}/run": {"post"},
        "/api/v1/admin/platform/tenant-migrations/imports/{job_id}/verification": {"get"},
        "/api/v1/admin/platform/tenant-migrations/imports/{job_id}/pairings/{pairing_id}/activate": {"post"},
        "/api/v1/admin/platform/tenant-migrations/imports/{job_id}/pairings/{pairing_id}/abort": {"post"},
        "/api/v1/admin/makerspace/{makerspace_id}/tenant-migration/disclosure-closure": {"get"},
        "/api/v1/admin/makerspace/{makerspace_id}/tenant-migration/disclosure-approvals": {"get", "post"},
        "/api/v1/admin/makerspace/{makerspace_id}/tenant-migration/disclosure-approvals/{approval_id}/revoke": {"post"},
        "/api/v1/admin/makerspace/{makerspace_id}/tenant-migration/exports": {"get", "post"},
        "/api/v1/admin/makerspace/{makerspace_id}/tenant-migration/exports/{job_id}": {"get"},
        "/api/v1/admin/makerspace/{makerspace_id}/tenant-migration/exports/{job_id}/download-url": {"post"},
        "/api/v1/admin/makerspace/{makerspace_id}/tenant-migration/exports/{job_id}/quiesce": {"post"},
        "/api/v1/admin/makerspace/{makerspace_id}/tenant-migration/pairings/{pairing_id}/archive-source": {"post"},
        "/api/v1/admin/makerspace/{makerspace_id}/tenant-migration/pairings/{pairing_id}/recover": {"post"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods <= set(paths[path])


def test_part12a_models_have_total_export_dispositions():
    assert isinstance(MODELS["tenant_migration.TenantImportJob"], OmittedModel)
    assert isinstance(MODELS["tenant_migration.ImportIdentityDecision"], OmittedModel)
    assert isinstance(MODELS["tenant_migration.DisclosureClosureApproval"], OmittedModel)
    assert isinstance(MODELS["tenant_migration.TenantMigrationExportJob"], OmittedModel)
    assert isinstance(
        FIELDS[(Fidelity.REDACTED, "tenant_migration.ExternalTenantReference", "snapshot")],
        Redacted,
    )
    assert isinstance(
        FIELDS[(Fidelity.PORTABLE, "tenant_migration.ExternalTenantReference", "makerspace")],
        Remapped,
    )


def test_import_retention_cleanup_is_registered_in_both_schedulers_with_its_own_lease():
    task = "apps.tenant_migration.tasks.cleanup_expired_import_jobs_task"
    assert settings.CELERY_BEAT_SCHEDULE["cleanup-expired-tenant-import-jobs"]["task"] == task
    assert ("cleanup-expired-tenant-import-jobs", task, 60) in SCHEDULED_TASKS
    assert CLEANUP_LEASE_NAME == "tenant-import-expiry-cleanup-work"
