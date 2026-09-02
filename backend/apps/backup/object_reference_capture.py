"""Snapshot enumeration for every typed Lane E object-reference surface."""

from django.apps import apps

from apps.backup.archive_objects import module_for_model
from apps.backup.main_projection_registry import RowDisposition, table_rules
from apps.backup.object_ownership import (
    MAIN_COMPONENT,
    ObjectOwnershipPlan,
    ObjectReference,
    slice_component,
)
from apps.backup.object_ownership_registry import (
    AUDIT_META_OBJECT_VARIANTS,
    BucketRule,
    ReferencePolicy,
    validate_object_reference_registry,
)
from apps.backup.recipient_selection import BackupBuildError


def build_object_ownership_plan(sovereign_makerspace_ids):
    sovereign = frozenset(int(value) for value in sovereign_makerspace_ids)
    rules_by_model = {rule.model._meta.label: rule for rule in table_rules()}
    references = []
    for rule in validate_object_reference_registry():
        model = apps.get_model(rule.model_label)
        table_rule = rules_by_model[rule.model_label]
        owner_lookup = _owner_lookup(table_rule)
        query_fields = ["pk", rule.field_name]
        if rule.bucket == BucketRule.FROM_ROW:
            query_fields.append("bucket_kind")
        if owner_lookup and owner_lookup not in query_fields:
            query_fields.append(owner_lookup)
        if rule.coordination_path and rule.coordination_path not in query_fields:
            query_fields.append(rule.coordination_path)
        if rule.retention_aware:
            query_fields.extend(
                [
                    "object_retention_state__status",
                    "object_retention_state__object_expired_at",
                    "object_retention_state__expired_size_bytes",
                ]
            )
        rows = model._base_manager.exclude(**{rule.field_name: ""}).values(*query_fields)
        for row in rows.iterator(chunk_size=500):
            # A NULL key column survives the exclude() above -- Django keeps NULL rows
            # out of an `exclude(field="")` -- and str(None) would enter the closure as
            # an object literally named "None" that no bucket holds. Only
            # bookings.BookableSpace.image_key is nullable today; the legacy closure in
            # archive_objects.collect_model_objects tests the raw value and skips it.
            raw_key = row[rule.field_name]
            if raw_key is None:
                continue
            key = str(raw_key)
            if not key:
                continue
            bucket = row["bucket_kind"] if rule.bucket == BucketRule.FROM_ROW else rule.bucket
            if bucket not in {"private", "public_image"}:
                raise BackupBuildError("An object reference has an unsupported bucket kind.")
            owner_id = row.get(owner_lookup) if owner_lookup else None
            component = _component_for(table_rule, owner_id, sovereign)
            if rule.policy == ReferencePolicy.COORDINATION_ONLY:
                component = None
            coordination_id = row.get(rule.coordination_path) if rule.coordination_path else None
            retention_state = row.get("object_retention_state__status") or "live"
            if retention_state == "expiring":
                raise BackupBuildError(
                    "Evidence expiry is in progress; retry archive capture later."
                )
            expired_at = row.get("object_retention_state__object_expired_at")
            if retention_state == "expired" and expired_at is None:
                raise BackupBuildError("Expired evidence lacks terminal state.")
            references.append(ObjectReference(
                bucket_kind=str(bucket), object_key=key,
                site=f"{rule.model_label}:{row['pk']}:{rule.field_name}",
                candidate_owner=component,
                canonical_makerspace_id=owner_id,
                module_key=module_for_model(rule.model_label),
                coordination_policy=(
                    rule.coordination_reason
                    if rule.policy == ReferencePolicy.COORDINATION_ONLY
                    else (rule.coordination_reason if coordination_id else "")
                ),
                coordination_makerspace_id=coordination_id,
                retention_state=retention_state,
                object_expired_at=(expired_at.isoformat() if expired_at else ""),
                expired_size_bytes=row.get(
                    "object_retention_state__expired_size_bytes"
                ),
            ))
    references.extend(_audit_meta_references())
    return ObjectOwnershipPlan(references, sovereign)


def _owner_lookup(table_rule):
    if table_rule.disposition != RowDisposition.COPY_TO_SLICE:
        return None
    path = table_rule.predicate.any_paths[0]
    return path if path in {"pk", "id"} else f"{path}_id"


def _component_for(table_rule, owner_id, sovereign):
    if (
        table_rule.disposition == RowDisposition.COPY_TO_SLICE
        and owner_id in sovereign
    ):
        return slice_component(owner_id)
    return MAIN_COMPONENT


def _audit_meta_references():
    AuditLog = apps.get_model("audit.AuditLog")
    result = []
    rows = AuditLog._base_manager.values("pk", "makerspace_id", "action", "meta")
    for row in rows.iterator(chunk_size=500):
        meta = row["meta"]
        if not isinstance(meta, dict) or "object_key" not in meta:
            continue
        field = AUDIT_META_OBJECT_VARIANTS.get(row["action"])
        if field is None:
            raise BackupBuildError(
                "AuditLog.meta contains an undeclared object-reference variant."
            )
        key = meta.get(field)
        if not isinstance(key, str) or not key:
            raise BackupBuildError("AuditLog.meta object reference is malformed.")
        owner_id = row["makerspace_id"]
        result.append(ObjectReference(
            bucket_kind="private", object_key=key,
            site=f"audit.AuditLog:{row['pk']}:meta:{row['action']}.{field}",
            candidate_owner=None, canonical_makerspace_id=owner_id,
            module_key="machines", coordination_policy="audit_history_reference",
            coordination_makerspace_id=owner_id,
        ))
    return result
