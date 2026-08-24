"""Rehydrate and prove E7 state before a compound pointer can move."""

import hashlib
import json
import uuid

from django.db import connections, transaction
from django.utils import timezone

from apps.backup.models import (
    B1FenceContinuity,
    B1ReservationEntry,
    B1RestoreComponentState,
    B1RestoreOperationState,
)
from apps.backup.not_restored import active_component_states
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_enforcement import install_reservation_entry


_FACT_GROUPS = (
    ("reservation_commitments", B1ReservationEntry.Kind.COMMITMENT),
    ("broad_fence_scopes", B1ReservationEntry.Kind.BROAD_FENCE),
    ("relationship_fence_scopes", B1ReservationEntry.Kind.RELATIONSHIP_FENCE),
    ("object_namespace_fences", B1ReservationEntry.Kind.OBJECT_NAMESPACE),
)


def rehydrate_pre_cutover_state(*, inputs, manifest, sibling, using="default"):
    """Persist opaque component identity before installing any reservation."""

    components = _component_map(manifest)
    seeds = manifest.get("not_restored_seeds")
    if not isinstance(seeds, list) or {
        (item.get("component_id"), item.get("makerspace_id"), item.get("state"))
        for item in seeds if isinstance(item, dict)
    } != {
        (str(identity), fact["makerspace_id"], "pending")
        for identity, fact in components.items()
    }:
        raise BackupBuildError("The signed not-restored seed set is inconsistent.")
    operation_values = {
        "artifact_id": uuid.UUID(manifest["artifact_id"]),
        "capture_id": uuid.UUID(manifest["capture_id"]),
        "main_component_id": uuid.UUID(manifest["main_component"]["component_id"]),
        "outer_ciphertext_sha256": inputs.artifact_sha256,
        "outer_manifest_sha256": _digest(manifest),
        "source_proof_sha256": _digest(manifest["source_partition_proof"]),
        "sibling_database_name": sibling.identity.database_name,
        "sibling_database_oid": sibling.identity.database_oid,
        "sibling_server_identity": _digest(list(sibling.identity.durable_key())),
    }
    with transaction.atomic(using=using):
        operation, created = B1RestoreOperationState.objects.using(using).get_or_create(
            operation_id=inputs.run_id, defaults=operation_values
        )
        if not created and any(
            getattr(operation, name) != value
            for name, value in operation_values.items()
        ):
            raise BackupBuildError("Existing compound restore state has another identity.")
        _advance(operation, B1RestoreOperationState.Stage.MAIN_RESTORED, using)
        _advance(operation, B1RestoreOperationState.Stage.ROLES_RECREATED, using)
        for identity, fact in components.items():
            values = {
                "artifact_id": operation.artifact_id,
                "capture_id": operation.capture_id,
                "makerspace_id_snapshot": fact["makerspace_id"],
                "ciphertext_sha256": fact["ciphertext_sha256"],
                "state": B1RestoreComponentState.State.PENDING,
            }
            component, component_created = (
                B1RestoreComponentState.objects.using(using).get_or_create(
                    operation_id=operation.operation_id,
                    component_id=identity,
                    defaults=values,
                )
            )
            if not component_created and any(
                getattr(component, name) != value for name, value in values.items()
            ):
                raise BackupBuildError("Existing not-restored component facts changed.")
        _advance(operation, B1RestoreOperationState.Stage.STATE_REHYDRATED, using)
    return {
        "operation_id": str(operation.operation_id),
        "not_restored_count": len(components),
        "persistent": True,
    }


def install_manifest_enforcement(*, inputs, manifest, using="default"):
    """Consume the E7 installer for every signed component/fact binding."""

    operation = B1RestoreOperationState.objects.using(using).get(pk=inputs.run_id)
    component_ids = set(
        B1RestoreComponentState.objects.using(using).filter(
            operation_id=inputs.run_id
        ).values_list("component_id", flat=True)
    )
    salt = manifest.get("reservation_salt")
    installed = 0
    for name, kind in _FACT_GROUPS:
        facts = manifest.get(name)
        if not isinstance(facts, list):
            raise BackupBuildError(f"The signed {name} declaration is missing.")
        for fact in facts:
            identities = _fact_components(fact, kind)
            if not identities or not identities <= component_ids:
                raise BackupBuildError("A reservation names an unknown component.")
            for component_id in sorted(identities, key=str):
                lookup = {
                    "operation_id": inputs.run_id,
                    "component_id": component_id,
                    "registry_identity": fact.get("constraint_identity")
                    or fact.get("registry_identity"),
                    "kind": kind,
                }
                existing = B1ReservationEntry.objects.using(using).filter(**lookup).first()
                if existing is not None:
                    if (
                        existing.definition_sha256 != fact.get("definition_sha256")
                        or any(
                            existing.safe_payload.get(key) != value
                            for key, value in fact.items()
                        )
                    ):
                        raise BackupBuildError("An installed reservation definition changed.")
                    continue
                install_reservation_entry(
                    operation_id=inputs.run_id,
                    component_id=component_id,
                    kind=kind,
                    fact=fact,
                    reservation_salt=salt,
                    using=using,
                )
                installed += 1
    _advance(operation, B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED, using)
    return {"installed": installed, "state": "database-enforced"}


def verify_pre_cutover_state(*, inputs, using="default"):
    operation = B1RestoreOperationState.objects.using(using).get(pk=inputs.run_id)
    with transaction.atomic(using=using):
        reservations = B1ReservationEntry.objects.using(using).filter(
            operation_id=inputs.run_id
        )
        now = timezone.now()
        reservations.filter(catalog_verified_at__isnull=True).update(
            catalog_verified_at=now
        )
        if reservations.filter(installed_at__isnull=True).exists():
            raise BackupBuildError("A pre-cutover reservation is not installed.")
        if B1FenceContinuity.objects.using(using).filter(
            operation_id=inputs.run_id, enabled=False
        ).exists():
            raise BackupBuildError("A pre-cutover fence lost continuity.")
        component_count = B1RestoreComponentState.objects.using(using).filter(
            operation_id=inputs.run_id
        ).count()
        active_count = active_component_states().using(using).filter(
            operation_id=inputs.run_id
        ).count()
        if component_count == 0 or active_count != component_count:
            raise BackupBuildError(
                "Persistent not-restored component state is incomplete."
            )
        _advance(operation, B1RestoreOperationState.Stage.CATALOG_VERIFIED, using)
    return {
        "verified": True,
        "reservations": reservations.count(),
        "fences": B1FenceContinuity.objects.using(using).filter(
            operation_id=inputs.run_id
        ).count(),
    }


def readiness_declarations(*, using="default"):
    return {
        "reservations": [_relation_declaration(
            "backup_b1reservationentry", using
        )],
        "fences": _fence_declarations(using),
        "not_restored": [_relation_declaration(
            "backup_b1restorecomponentstate", using
        )],
    }


def mark_quarantine_verified(*, inputs, using="default"):
    operation = B1RestoreOperationState.objects.using(using).get(pk=inputs.run_id)
    for stage in (
        B1RestoreOperationState.Stage.OBJECTS_VERIFIED,
        B1RestoreOperationState.Stage.QUARANTINE_VERIFIED,
        B1RestoreOperationState.Stage.CUTOVER_READY,
    ):
        _advance(operation, stage, using)
    return {"verified": True}


def _advance(operation, target, using):
    operation.refresh_from_db(using=using)
    if operation.stage == target:
        return
    if operation.stage == B1RestoreOperationState.Stage.FAILED:
        raise BackupBuildError("A failed compound restore cannot resume forward.")
    ranks = [
        B1RestoreOperationState.Stage.VERIFIED,
        B1RestoreOperationState.Stage.MAIN_RESTORED,
        B1RestoreOperationState.Stage.ROLES_RECREATED,
        B1RestoreOperationState.Stage.STATE_REHYDRATED,
        B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED,
        B1RestoreOperationState.Stage.CATALOG_VERIFIED,
        B1RestoreOperationState.Stage.OBJECTS_VERIFIED,
        B1RestoreOperationState.Stage.QUARANTINE_VERIFIED,
        B1RestoreOperationState.Stage.CUTOVER_READY,
    ]
    if ranks.index(operation.stage) > ranks.index(target):
        return
    changed = B1RestoreOperationState.objects.using(using).filter(
        pk=operation.pk, stage=operation.stage
    ).update(stage=target)
    if changed != 1:
        raise BackupBuildError("Compound restore state did not advance exactly once.")
    operation.stage = target


def _component_map(manifest):
    result = {}
    for item in manifest.get("slice_components", ()):
        try:
            identity = uuid.UUID(item["component_id"])
            makerspace_id = item["makerspace_id"]
            digest = item["ciphertext_sha256"]
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupBuildError("A signed slice component is invalid.") from exc
        if identity in result or type(makerspace_id) is not int or makerspace_id <= 0:
            raise BackupBuildError("A signed slice component identity is duplicated.")
        result[identity] = {
            "makerspace_id": makerspace_id,
            "ciphertext_sha256": digest,
        }
    if not result:
        raise BackupBuildError("A compound restore has no opaque component.")
    return result


def _fact_components(fact, kind):
    values = (
        [item.get("component_id") for item in fact.get("component_commitments", ())]
        if kind == B1ReservationEntry.Kind.COMMITMENT
        else fact.get("component_ids", ())
    )
    try:
        return {uuid.UUID(value) for value in values}
    except (TypeError, ValueError, AttributeError) as exc:
        raise BackupBuildError("A reservation component identity is invalid.") from exc


def _relation_declaration(table, using):
    with connections[using].cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*), COALESCE(jsonb_agg(to_jsonb(snapshot) "
            f"ORDER BY to_jsonb(snapshot)::text)::text, '[]') "
            f"FROM public.{table} AS snapshot"
        )
        count, rows = cursor.fetchone()
    return {"schema": "public", "table": table, "expected_rows": count,
            "sha256": hashlib.sha256(rows.encode()).hexdigest()}


def _fence_declarations(using):
    result = []
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT namespace.nspname, relation.relname, trigger.tgname, "
            "pg_get_triggerdef(trigger.oid, true) FROM pg_trigger trigger "
            "JOIN pg_class relation ON relation.oid=trigger.tgrelid "
            "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
            "WHERE trigger.tgname='backup_b1_reservation_guard' "
            "AND trigger.tgenabled IN ('O','A') AND NOT trigger.tgisinternal "
            "ORDER BY namespace.nspname, relation.relname"
        )
        for schema, table, trigger, definition in cursor.fetchall():
            result.append({
                "schema": schema, "table": table, "trigger": trigger,
                "enabled": True,
                "definition_sha256": hashlib.sha256(definition.encode()).hexdigest(),
            })
    return result


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode()).hexdigest()
