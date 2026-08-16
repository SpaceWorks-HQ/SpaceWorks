import uuid
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.deployment_keys import public_deployment_identity
from apps.tenant_migration.models import TenantImportJob
from apps.tenant_migration.pairing import approve_pairing
from apps.tenant_migration.receipt_crypto import (
    ALGORITHM,
    FORMAT_VERSION,
    generate_key_material,
    sign_payload,
)

DIGEST = "a" * 64


def superadmin(suffix):
    return User.objects.create_superuser(
        username=f"migration-{suffix}",
        email=f"migration-{suffix}@example.test",
        password="pw",
    )


def external_identity(deployment_id=None):
    material = generate_key_material()
    identity = {
        "algorithm": ALGORITHM,
        "deployment_id": deployment_id or str(uuid.uuid4()),
        "public_key": material["public_key"],
        "fingerprint": material["fingerprint"],
    }
    return identity, material["private_key"]


def target_pairing(actor, source_tenant_id="41"):
    source, source_private = external_identity("source-deployment")
    target = public_deployment_identity()
    migration_id = uuid.uuid4()
    pairing = approve_pairing(
        actor=actor,
        migration_id=migration_id,
        source_tenant_id=source_tenant_id,
        archive_digest=DIGEST,
        source=source,
        target=target,
    )
    return pairing, source, source_private


def source_pairing(actor, makerspace):
    source = public_deployment_identity()
    target, target_private = external_identity("target-deployment")
    pairing = approve_pairing(
        actor=actor,
        migration_id=uuid.uuid4(),
        source_tenant_id=str(makerspace.pk),
        archive_digest=DIGEST,
        source=source,
        target=target,
    )
    return pairing, target, target_private


def import_job(pairing, *, status="importing"):
    target = Makerspace.objects.create(
        name=f"Target {pairing.migration_id}",
        slug=f"target-{str(pairing.migration_id)[:8]}",
    )
    return TenantImportJob.objects.create(
        id=pairing.migration_id,
        source_archive_digest=pairing.archive_digest,
        source_makerspace_id=pairing.source_tenant_id,
        source_makerspace_slug="source-lab",
        source_makerspace_name="Source Lab",
        source_deployment_id=pairing.source_deployment_id,
        target_makerspace=target,
        status=status,
        expires_at=timezone.now() + timedelta(days=1),
    )


def signed_envelope(pairing, operation, identity, private_key, **overrides):
    payload = {
        "format_version": FORMAT_VERSION,
        "operation": operation,
        "receipt_id": str(uuid.uuid4()),
        "migration_id": str(pairing.migration_id),
        "source_tenant_id": pairing.source_tenant_id,
        "archive_digest": pairing.archive_digest,
        "source_deployment_id": pairing.source_deployment_id,
        "target_deployment_id": pairing.target_deployment_id,
        "signer_fingerprint": identity["fingerprint"],
    }
    payload.update(overrides)
    return {
        "payload": payload,
        "signer_fingerprint": identity["fingerprint"],
        "signature": sign_payload(payload, private_key),
    }


def bind_job_state(monkeypatch, job):
    from apps.tenant_migration import target_state

    def transition(makerspace_id, expected, new):
        assert makerspace_id == job.target_makerspace_id
        return TenantImportJob.objects.filter(pk=job.pk, status=expected).update(
            status=new
        )

    def has_state(makerspace_id, expected):
        assert makerspace_id == job.target_makerspace_id
        return TenantImportJob.objects.filter(pk=job.pk, status=expected).exists()

    monkeypatch.setattr(target_state, "transition_target", transition)
    monkeypatch.setattr(target_state, "target_has_state", has_state)
