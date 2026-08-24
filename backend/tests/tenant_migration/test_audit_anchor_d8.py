import pytest

from apps.audit.anchors import AnchorError
from apps.audit.models import AuditBatch
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.tenant_dump_audit_anchors import prove_no_external_anchor
from apps.tenant_migration.tenant_dump_errors import TenantDumpPublicationRefused


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _configured_object_anchor(settings):
    settings.AUDIT_ATTESTATION_S3_BUCKET = "d8-test-audit-anchors"
    settings.AUDIT_ATTESTATION_RETENTION_DAYS = 1
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "d8-test-deployment"


def _space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def test_external_anchor_negative_probe_accepts_only_provable_absence(
    monkeypatch, settings
):
    space = _space("d8-anchor-absent")
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "object_storage"
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_audit_anchors."
        "ObjectStorageAnchorSink.fetch_scope_head",
        lambda *_args: (-1, None, None),
    )

    assert prove_no_external_anchor(space.pk) is True


def test_unavailable_anchor_backend_refuses_without_an_override(settings):
    space = _space("d8-anchor-backend")
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "none"

    with pytest.raises(TenantDumpPublicationRefused, match="cannot prove"):
        prove_no_external_anchor(space.pk)


def test_anchor_transport_failure_refuses_without_an_override(monkeypatch, settings):
    space = _space("d8-anchor-http-failure")
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "object_storage"
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_audit_anchors."
        "ObjectStorageAnchorSink.fetch_scope_head",
        lambda *_args: (_ for _ in ()).throw(AnchorError("HTTP unavailable")),
    )

    with pytest.raises(TenantDumpPublicationRefused, match="could not prove"):
        prove_no_external_anchor(space.pk)


@pytest.mark.parametrize("history", ("local", "external"))
def test_unprovable_or_anchored_history_refuses_without_an_override(
    history, monkeypatch, settings
):
    space = _space(f"d8-anchor-{history}")
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "object_storage"
    if history == "local":
        AuditBatch.objects.create(
            makerspace=space,
            batch_seq=0,
            leaf_count=1,
            merkle_root=b"r" * 32,
            signature=b"s" * 64,
            signer_fingerprint="f" * 64,
        )
    else:
        monkeypatch.setattr(
            "apps.tenant_migration.tenant_dump_audit_anchors."
            "ObjectStorageAnchorSink.fetch_scope_head",
            lambda *_args: (0, "f" * 64, b"r" * 32),
        )

    with pytest.raises(TenantDumpPublicationRefused):
        prove_no_external_anchor(space.pk)
