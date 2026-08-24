"""Fail-closed negative proof for source audit attestation anchors."""

from django.conf import settings

from apps.audit.anchors import AnchorError
from apps.audit.anchors_object_storage import ObjectStorageAnchorSink
from apps.audit.batch_format import scope_name
from apps.audit.models import AuditBatch, AuditSigningKey
from apps.audit.signing import deployment_identity

from .tenant_dump_errors import TenantDumpPublicationRefused


def prove_no_external_anchor(makerspace_id):
    # A local batch is the durable prerequisite for an external anchor. Refusing any
    # such batch is intentionally conservative: it closes the historical-config gap
    # even when today's object-storage prefix happens to be empty.
    locally_anchored = AuditBatch.objects.filter(
        makerspace_id=makerspace_id
    ).exists() or AuditSigningKey.objects.filter(
        makerspace_id=makerspace_id,
        activated_at__isnull=False,
    ).exists()
    if locally_anchored:
        raise TenantDumpPublicationRefused(
            "Lane D cannot prove audit-anchor absence for local attestation history."
        )
    backend = str(settings.AUDIT_ATTESTATION_ANCHOR_BACKEND).strip().lower()
    if backend != "object_storage":
        raise TenantDumpPublicationRefused(
            "Lane D cannot prove audit-anchor absence without the enumerable object-storage sink."
        )
    try:
        sequence, signer, _root = ObjectStorageAnchorSink().fetch_scope_head(
            deployment_identity(),
            scope_name(makerspace_id),
        )
    except AnchorError as exc:
        raise TenantDumpPublicationRefused(
            "Lane D could not prove external audit-anchor absence."
        ) from exc
    if sequence != -1 or signer is not None:
        raise TenantDumpPublicationRefused(
            "This tenant has externally anchored audit history and cannot use the Lane D format."
        )
    return True
