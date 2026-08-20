"""Public barrel for whole-log audit integrity verification."""

from .integrity_activation import _verify_activation, _verify_scope_registry
from .integrity_batches import _continues, _verify_batches
from .integrity_rows import _failure, _verify_genesis_membership, _verify_rows
from .integrity_verification import verify_audit_integrity


__all__ = [
    "_continues",
    "_failure",
    "_verify_activation",
    "_verify_batches",
    "_verify_genesis_membership",
    "_verify_rows",
    "_verify_scope_registry",
    "verify_audit_integrity",
]
