"""Public barrel for portable AuditLog reference declarations."""

from .audit_references_meta import (
    AUDIT_META_REFERENCES,
    R,
    S,
    _reference,
    _SOURCE_LOCAL_EDGES,
)
from .audit_references_targets import (
    AUDIT_TARGET_DISPOSITIONS,
    SOURCE_ID_PREFIX,
    UNRECOGNISED_AUDIT_TARGET,
    AuditReference,
    AuditReferenceDisposition,
    audit_target_dispositions,
    normalize_audit_target_type,
)


__all__ = [
    "AUDIT_META_REFERENCES",
    "AUDIT_TARGET_DISPOSITIONS",
    "AuditReference",
    "AuditReferenceDisposition",
    "R",
    "S",
    "SOURCE_ID_PREFIX",
    "UNRECOGNISED_AUDIT_TARGET",
    "_SOURCE_LOCAL_EDGES",
    "_reference",
    "audit_target_dispositions",
    "normalize_audit_target_type",
]
