"""Console organization reach is source-local provenance, never imported authority."""

from .audit_references_targets import AuditReference, AuditReferenceDisposition

UX_AUDIT_EDGES = {
    (action, "organization_id"): AuditReference(
        AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT, "organizations.Organization"
    )
    for action in (
        "organization.link_created", "organization.link_updated", "organization.link_deleted"
    )
}
