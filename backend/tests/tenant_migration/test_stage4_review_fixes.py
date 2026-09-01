from contextlib import contextmanager
from datetime import timedelta
import uuid

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.data_export.models import DataExportJob
from apps.makerspaces.models import Makerspace
from apps.tenant_migration import gate_policy
from apps.tenant_migration.models import (
    DisclosureClosureApproval,
    MigrationPairing,
    SourceMigrationGate,
    TenantImportJob,
    TenantMigrationExportJob,
)


pytestmark = pytest.mark.django_db


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_frozen_source_migration_control_routes_reach_views_instead_of_423(
    monkeypatch,
):
    actor = User.objects.create_superuser(
        username="frozen-route-root", password="test-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    source = Makerspace.objects.create(name="Frozen Route Source", slug="frozen-route-source")
    target = Makerspace.objects.create(
        name="Frozen Route Target", slug="frozen-route-target",
        lifecycle_state=Makerspace.LifecycleState.IMPORTING,
    )
    approval = DisclosureClosureApproval.objects.create(
        makerspace=source, closure_digest="a" * 64,
        identity_ids=[], approved_identity_ids=[], approved_by=actor,
    )
    export = DataExportJob.objects.create(
        makerspace=source, requested_by=actor, fidelity="PORTABLE",
        status=DataExportJob.Status.AVAILABLE,
        object_key=f"tenant-migrations/{source.pk}/frozen.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )
    TenantMigrationExportJob.objects.create(
        export_job=export, disclosure_approval=approval,
        closure_digest=approval.closure_digest,
        target_age_recipient="age1targetrecipient000000000000",
        archive_digest="b" * 64,
    )
    pairing = MigrationPairing.objects.create(
        migration_id=uuid.uuid4(), source_tenant_id=str(source.pk),
        archive_digest="b" * 64, source_deployment_id="source",
        source_public_key="s" * 44, source_fingerprint="s" * 64,
        target_deployment_id="target", target_public_key="t" * 44,
        target_fingerprint="t" * 64, approved_by=actor,
    )
    import_job = TenantImportJob.objects.create(
        id=pairing.migration_id, source_archive_digest=pairing.archive_digest,
        source_makerspace_id=str(source.pk), source_deployment_id="source",
        target_makerspace=target, status=TenantImportJob.Status.COMPLETED,
        expires_at=timezone.now() + timedelta(days=1),
    )
    receipt = {
        "payload": {}, "signer_fingerprint": "f" * 64, "signature": "x" * 88,
    }
    now = timezone.now()
    SourceMigrationGate.objects.create(
        makerspace=source, state=SourceMigrationGate.State.QUIESCED,
        owner_id=uuid.uuid4(), fencing_token=1, actor=actor,
        heartbeat_at=now, lease_expires_at=now + timedelta(hours=1),
        presign_drain_until=now, quiesced_at=now,
    )
    locked_routes = []
    from apps.tenant_migration import middleware as gate_middleware

    real_shared_boundary = gate_middleware.shared_boundary

    @contextmanager
    def observed_shared_boundary(makerspace_id):
        locked_routes.append(makerspace_id)
        with real_shared_boundary(makerspace_id):
            yield

    monkeypatch.setattr(
        gate_middleware, "shared_boundary", observed_shared_boundary
    )
    monkeypatch.setattr(
        "apps.tenant_migration.views_cutover.claim_completed_export",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.views_admission_export.export_services.issue_download_token",
        lambda *_args: ("download-token", timezone.now() + timedelta(minutes=5)),
    )
    for name in ("retire_source", "activate_target", "abort_target", "reopen_source"):
        monkeypatch.setattr(
            f"apps.tenant_migration.views_cutover.cutover.{name}",
            lambda **_kwargs: receipt,
        )
    client = client_for(actor)

    responses = [
        client.post(reverse("tenant-migration-source-quiesce", args=(source.pk, export.pk))),
        client.post(reverse("tenant-migration-export-download-url", args=(source.pk, export.pk))),
        client.post(reverse("tenant-migration-source-archive", args=(source.pk, pairing.pk))),
        client.post(
            reverse("tenant-migration-target-activate", args=(import_job.pk, pairing.pk)),
            {"receipt": receipt}, format="json",
        ),
        client.post(reverse("tenant-migration-target-abort", args=(import_job.pk, pairing.pk))),
        client.post(
            reverse("tenant-migration-source-recover", args=(source.pk, pairing.pk)),
            {"receipt": receipt}, format="json",
        ),
    ]
    pairing_validation = client.post(
        reverse("tenant-migration-pairings"), {}, format="json"
    )

    assert [response.status_code for response in responses] == [200] * 6
    assert pairing_validation.status_code == 400
    assert locked_routes == [source.pk] * 4
    assert set(gate_policy.HTTP_EXEMPTIONS).isdisjoint({
        "tenant-migration-pairings",
        "tenant-migration-imports",
        "tenant-migration-import-decisions",
        "tenant-migration-import-run",
        "tenant-migration-target-activate",
        "tenant-migration-target-abort",
    })


def test_import_detail_serializes_persisted_target_lifecycle():
    actor = User.objects.create_superuser(
        username="import-lifecycle-root", password="test-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    target = Makerspace.objects.create(
        name="Activated Import", slug="activated-import",
        lifecycle_state=Makerspace.LifecycleState.ACTIVE,
    )
    job = TenantImportJob.objects.create(
        source_archive_digest="a" * 64, target_makerspace=target,
        status=TenantImportJob.Status.COMPLETED,
        expires_at=timezone.now() + timedelta(days=1),
    )

    response = client_for(actor).get(
        reverse("tenant-migration-import-detail", args=(job.pk,))
    )

    assert response.status_code == 200
    assert response.data["target_lifecycle_state"] == Makerspace.LifecycleState.ACTIVE


def test_no_membership_decision_rejects_archived_required_dependents_at_boundary(
    monkeypatch,
):
    actor = User.objects.create_superuser(
        username="membership-dependency-root", password="test-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    job = TenantImportJob.objects.create(
        source_archive_digest="a" * 64, archive_path="staged.age",
        status=TenantImportJob.Status.AWAITING_IDENTITY,
        expires_at=timezone.now() + timedelta(days=1),
    )
    rows = {
        "accounts.User": [{"id": "17", "email": "member@example.test"}],
        "makerspaces.MakerspaceMembership": [{"id": "23", "user_id": "17"}],
        "makerspaces.MemberProfile": [{"id": "31", "membership_id": "23"}],
        "presence.PresenceSession": [{"id": "47", "membership_id": "23"}],
    }

    class FakeArchive:
        def __init__(self, _root):
            pass

        def rows(self, label):
            return iter(rows.get(label, ()))

    @contextmanager
    def decrypted_archive(_path):
        yield object(), ()

    monkeypatch.setattr("apps.tenant_migration.archive_stream.PortableArchive", FakeArchive)
    monkeypatch.setattr(
        "apps.tenant_migration.import_staging.decrypted_archive", decrypted_archive
    )

    response = client_for(actor).post(
        reverse("tenant-migration-import-decisions", args=(job.pk,)),
        {"decisions": [{
            "source_user_id": "17", "identity_resolution": "create_walk_in",
            "membership_disposition": "no_membership",
        }]},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "membership_dependency_conflict"
    assert "makerspaces.MemberProfile=1" in response.data["detail"]
    assert "presence.PresenceSession=1" in response.data["detail"]
    job.refresh_from_db()
    assert job.status == TenantImportJob.Status.AWAITING_IDENTITY
    assert not job.identity_decisions.exists()
