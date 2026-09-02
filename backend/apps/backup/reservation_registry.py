"""Deny-by-default registries for Lane E reservations and broad fences."""

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json

from django.apps import apps

from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_canonicalizers import (
    canonicalizer_for,
    canonicalizer_identity,
    component_canonicalizer_identities,
)
from apps.backup.reservation_catalog import UniqueRule


__all__ = (
    "canonicalizer_for",
    "canonicalizer_identity",
    "component_canonicalizer_identities",
)


MIN_COMMITMENT_ENTROPY_BITS = 120


class ReservationMode(StrEnum):
    SEQUENCE_HIGH_WATER = "sequence_high_water"
    HIGH_ENTROPY_COMMITMENT = "high_entropy_commitment"
    BROAD_FENCE = "broad_fence"
    REFUSE = "refuse"


class FenceOperation(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    OVERWRITE = "overwrite"


@dataclass(frozen=True)
class GeneratorProof:
    table: str
    column: str
    generator_identity: str
    minimum_entropy_bits: int
    callable_identity: str
    field_type: str


@dataclass(frozen=True)
class FenceFamily:
    identity: str
    table: str
    columns: tuple[str, ...]
    operations: tuple[FenceOperation, ...]
    dependency_kind: str
    usable_during_restore: bool
    reason: str

    @property
    def definition_sha256(self):
        return _digest({
            "version": "b1-fence-family-v1",
            "identity": self.identity,
            "table": self.table,
            "columns": self.columns,
            "operations": self.operations,
            "dependency_kind": self.dependency_kind,
            "usable_during_restore": self.usable_during_restore,
            "reason": self.reason,
        })


def _proof(table, column, identity, callable_identity, field_type):
    return GeneratorProof(
        table, column, identity, 122, callable_identity, field_type
    )


GENERATOR_PROOFS = {
    ("boxes_box", "code"): _proof(
        "boxes_box", "code", "uuid4-hex-122-bit-v1",
        "apps.boxes.models.generate_box_code", "CharField",
    ),
    **{
        key: _proof(*key, "python-uuid4-122-bit-v1", "uuid.uuid4", "UUIDField")
        for key in (
            ("bookings_bookablespace", "public_token"),
            ("bookings_booking", "public_token"),
            ("events_event", "public_token"),
            ("events_eventseries", "public_token"),
            ("events_eventregistration", "checkin_token"),
            ("hardware_requests_hardwarerequest", "public_token"),
            ("machines_machineservicerequest", "public_token"),
        )
    },
}


# Relationship families are separate from uniqueness rules.  They cover all
# operations that could create or destroy an endpoint while a slice is opaque.
RELATIONSHIP_FAMILIES = (
    FenceFamily(
        identity="readable-main-boundary-fk-v1",
        table="*registry-boundary-table*",
        columns=("*registered-fk*",),
        operations=(FenceOperation.INSERT, FenceOperation.UPDATE, FenceOperation.DELETE),
        dependency_kind="boundary_fk",
        usable_during_restore=True,
        reason="Opaque boundary endpoints cannot be safely committed.",
    ),
    FenceFamily(
        identity="tenant-semantic-reference-v1",
        table="audit_auditlog",
        columns=("target_type", "target_id", "meta"),
        operations=(FenceOperation.INSERT, FenceOperation.UPDATE, FenceOperation.DELETE),
        dependency_kind="semantic_reference",
        usable_during_restore=True,
        reason="Audit semantic references can name an undisclosed endpoint.",
    ),
)


OBJECT_NAMESPACE_FAMILY = FenceFamily(
    identity="object-namespace-low-entropy-v1",
    table="*registry-object-table*",
    columns=("*registered-object-key*",),
    operations=(
        FenceOperation.INSERT,
        FenceOperation.UPDATE,
        FenceOperation.DELETE,
        FenceOperation.OVERWRITE,
    ),
    dependency_kind="object_namespace",
    usable_during_restore=True,
    reason="Only registry-proven random object keys may use commitments.",
)


def reservation_mode(rule: UniqueRule, postgres_major: int) -> ReservationMode:
    """Commit only when entropy and every PostgreSQL comparison are proved."""

    canonicalizers = [canonicalizer_for(item, postgres_major) for item in rule.components]
    if any(item is None for item in canonicalizers):
        return ReservationMode.BROAD_FENCE
    validate_generator_proofs()
    entropy = max(
        (
            GENERATOR_PROOFS[(rule.table, item.source_column)].minimum_entropy_bits
            for item in rule.components
            if (rule.table, item.source_column) in GENERATOR_PROOFS
        ),
        default=0,
    )
    if entropy >= MIN_COMMITMENT_ENTROPY_BITS:
        return ReservationMode.HIGH_ENTROPY_COMMITMENT
    return ReservationMode.BROAD_FENCE


def validate_generator_proofs():
    models_by_table = {
        model._meta.db_table: model for model in apps.get_models()
        if model._meta.managed and not model._meta.proxy
    }
    for proof in GENERATOR_PROOFS.values():
        model = models_by_table.get(proof.table)
        if model is None:
            raise BackupBuildError(
                f"Reservation generator proof names absent table {proof.table}."
            )
        field = model._meta.get_field(proof.column)
        default = field.default
        identity = f"{getattr(default, '__module__', '')}.{getattr(default, '__qualname__', '')}"
        if (
            identity != proof.callable_identity
            or field.__class__.__name__ != proof.field_type
            or field.editable
            or proof.minimum_entropy_bits < MIN_COMMITMENT_ENTROPY_BITS
        ):
            raise BackupBuildError(
                f"Reservation generator proof drifted for {proof.table}.{proof.column}."
            )
    return True


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()
