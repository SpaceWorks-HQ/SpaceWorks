from .audit_references_targets import AuditReference, AuditReferenceDisposition

WP3_AUDIT_EDGES = {
    ('payment.failed', 'event_id'): AuditReference(
        AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT, None, 'provider_failure_event',
    ),
}
