"""Public barrel for Ed25519 audit signing-key rotation."""

from .rotation_lifecycle import (
    abort_rotation,
    finalize_rotation,
    prepare_rotation,
    publish_rotation,
)
from .rotation_protocol import (
    EMPTY_HEAD_ROOT,
    AuditSigningKeyRotationError,
    latest_rotation_state,
    rotation_audit_meta,
    rotation_envelope,
    scope_head,
    validate_rotation,
)

__all__ = [
    "EMPTY_HEAD_ROOT",
    "AuditSigningKeyRotationError",
    "abort_rotation",
    "finalize_rotation",
    "latest_rotation_state",
    "prepare_rotation",
    "publish_rotation",
    "rotation_audit_meta",
    "rotation_envelope",
    "scope_head",
    "validate_rotation",
]
