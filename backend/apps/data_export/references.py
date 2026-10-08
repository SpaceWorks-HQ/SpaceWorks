"""Relational and semantic reference registries for the global User closure."""
from .fields import FIELDS
from .models import EXPORTED_MODELS
from .references_json_fields import JSON_REFERENCE_FIELDS
from .references_core import (
    _EXCLUDED_USER_EDGE_REASONS as _CORE_EXCLUDED_USER_EDGE_REASONS,
    RAW_USER_REFERENCE_FIELDS,
    RELATIONAL_USER_FIELDS as _CORE_RELATIONAL_USER_FIELDS,
)
from .references_devices import DEVICE_EXCLUDED_USER_EDGE_REASONS, DEVICE_USER_FIELDS

RELATIONAL_USER_FIELDS = _CORE_RELATIONAL_USER_FIELDS | DEVICE_USER_FIELDS
_EXCLUDED_USER_EDGE_REASONS = {
    **_CORE_EXCLUDED_USER_EDGE_REASONS, **DEVICE_EXCLUDED_USER_EDGE_REASONS,
}
from .types import (
    Fidelity,
    Omitted,
    SemanticUserRef,
    SourceLocalProvenance,
    UserEdge,
)
class DanglingUserReferenceError(RuntimeError):
    """A raw user ID cannot be bound safely in a portable archive."""
def require_raw_user(fidelity, *, model, row_pk, field, user_id, existing_user_ids):
    """Enforce the declared no-dangling contract before a raw ID is remapped."""
    if fidelity is Fidelity.PORTABLE and user_id not in existing_user_ids:
        raise DanglingUserReferenceError(
            f"{model} row {row_pk} has dangling {field}={user_id}"
        )
    return user_id
USER_EDGES = {}
for _fidelity in Fidelity:
    for _label, _field in RELATIONAL_USER_FIELDS | RAW_USER_REFERENCE_FIELDS:
        disposition = FIELDS.get((_fidelity, _label, _field))
        included = _label in EXPORTED_MODELS and not isinstance(disposition, Omitted)
        USER_EDGES[(_fidelity, _label, _field)] = UserEdge(
            included=included,
            raw=(_label, _field) in RAW_USER_REFERENCE_FIELDS,
            reason=(
                "Pull the referenced person into the bounded user closure."
                if included
                else _EXCLUDED_USER_EDGE_REASONS.get(
                    (_label, _field),
                    "The source model or field is excluded at this fidelity.",
                )
            ),
        )

POLYMORPHIC_PAIRS = frozenset(
    {
        ("audit.AuditLog", "target_type+target_id"),
        ("boxes.QrCode", "target_type+target_id"),
        ("hardware_requests.PublicToolLoan", "target_type+target_id"),
        ("operations.QrPrintBatchItem", "target_type+target_id"),
    }
)

JSON_FIELDS = JSON_REFERENCE_FIELDS

SEMANTIC_REFERENCES = {}
for _fidelity in Fidelity:
    # PORTABLE keeps audit targets as inert source provenance, so it does not pull user
    # targets into the global closure. REDACTED remains shipped operator-facing behavior;
    # narrowing it would silently drop people from an existing export.
    SEMANTIC_REFERENCES[(_fidelity, "audit.AuditLog", "target_type+target_id")] = (
        (
            SemanticUserRef(
                "audit.AuditLog",
                "target_type=accounts.user + target_id",
                "A user audit target joins the REDACTED user closure, as shipped.",
            ),
            SourceLocalProvenance(
                "audit.AuditLog",
                "target_type!=accounts.user + target_id",
                "Non-user polymorphic targets retain their source model label.",
            ),
        )
        if _fidelity is Fidelity.REDACTED
        else (
            SourceLocalProvenance(
                "audit.AuditLog",
                "target_type + target_id",
                "The audit target registry decides remap versus inert source provenance.",
            ),
        )
    )
    for _model, _location in POLYMORPHIC_PAIRS - {
        ("audit.AuditLog", "target_type+target_id")
    }:
        SEMANTIC_REFERENCES[(_fidelity, _model, _location)] = (
            SourceLocalProvenance(
                _model, _location, "Physical/domain target IDs are source-local provenance."
            ),
        )
    for _model, _field in JSON_FIELDS:
        if (_model, _field) == ("audit.AuditLog", "meta"):
            decision = SourceLocalProvenance(
                _model,
                "meta id-bearing paths",
                "The per-action audit registry remaps or source-namespaces every ID path.",
            )
        elif _field.endswith("_actor_snapshot"):
            # `source_user_id` here is deliberately NOT a live reference: Phase 7 v13
            # made imported actor references typed TEXT snapshots precisely because the
            # source user may not exist at the target or may map to a different person.
            # Remapping it would bind evidence to the wrong human, so it stays
            # source-local at BOTH fidelities.
            decision = SourceLocalProvenance(
                _model,
                f"{_field}.source_user_id",
                "Imported actor provenance is source-local text and is never remapped.",
            )
        else:
            decision = SourceLocalProvenance(
                _model,
                f"{_field}.*_id",
                "Reviewed JSON schema contains no live user reference at this fidelity.",
            )
        SEMANTIC_REFERENCES[(_fidelity, _model, f"json:{_field}")] = (decision,)
