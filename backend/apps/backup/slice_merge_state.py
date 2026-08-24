"""Transactional state, reservation locks, and final commit for E8."""

from django.db import connections, transaction

from apps.backup.models import (
    B1FenceContinuity,
    B1ReservationEntry,
    B1RestoreComponentState,
    B1RestoreOperationState,
)
from apps.backup.slice_merge_cleanup import (
    clear_verified_reservations,
    drop_staging_schema,
)
from apps.backup.slice_merge_types import SliceMergeError


CHECKPOINT_RANK = {
    "": 0, "staged": 1, "keys_installed": 2, "rows_applied": 3,
    "objects_promoted": 4, "verified": 5,
}


def locked_state(operation_id, component_ids, *, using):
    with transaction.atomic(using=using):
        operation = B1RestoreOperationState.objects.using(using).select_for_update().get(
            operation_id=operation_id
        )
        components = list(B1RestoreComponentState.objects.using(using).select_for_update().filter(
            operation_id=operation_id, component_id__in=component_ids
        ).order_by("component_id"))
        list(B1ReservationEntry.objects.using(using).select_for_update().filter(
            operation_id=operation_id, component_id__in=component_ids
        ).order_by("component_id", "pk"))
    if len(components) != len(component_ids):
        raise SliceMergeError("A requested opaque component is not registered.")
    return operation, components


def validate_component_states(operation, components):
    if operation.stage != B1RestoreOperationState.Stage.CUTOVER_READY:
        raise SliceMergeError("The compound restore is not ready for delayed tenant merges.")
    allowed = {
        B1RestoreComponentState.State.PENDING,
        B1RestoreComponentState.State.DEPENDENCY_WAIT,
        B1RestoreComponentState.State.MERGING,
    }
    if any(item.state not in allowed for item in components):
        raise SliceMergeError("A component is not in a mergeable not-restored state.")


def begin_merging(components, *, using):
    ids = [item.pk for item in components]
    with transaction.atomic(using=using):
        list(B1RestoreComponentState.objects.using(using).select_for_update().filter(pk__in=ids))
        B1RestoreComponentState.objects.using(using).filter(pk__in=ids).exclude(
            state=B1RestoreComponentState.State.MERGING
        ).update(state=B1RestoreComponentState.State.MERGING)
    for item in components:
        item.state = B1RestoreComponentState.State.MERGING


def checkpoint(components, value, *, using):
    ids = [item.pk for item in components]
    with transaction.atomic(using=using):
        rows = list(B1RestoreComponentState.objects.using(using).select_for_update().filter(
            pk__in=ids
        ).order_by("component_id"))
        current = _same_checkpoint(rows)
        if CHECKPOINT_RANK[current] >= CHECKPOINT_RANK[value]:
            return
        if CHECKPOINT_RANK[value] != CHECKPOINT_RANK[current] + 1:
            raise SliceMergeError("A merge checkpoint cannot skip an ordered step.")
        B1RestoreComponentState.objects.using(using).filter(pk__in=ids).update(
            merge_checkpoint=value
        )


def common_checkpoint(components, *, using):
    rows = list(B1RestoreComponentState.objects.using(using).filter(
        pk__in=[item.pk for item in components]
    ).order_by("component_id"))
    return _same_checkpoint(rows)


def record_and_resolve_dependencies(operation_id, components, facts, *, using):
    supplied = {item.component_id for item in components}
    with transaction.atomic(using=using):
        all_rows = list(B1RestoreComponentState.objects.using(using).select_for_update().filter(
            operation_id=operation_id
        ).order_by("component_id"))
        by_component = {row.component_id: row for row in all_rows}
        missing = set()
        for component in components:
            normalized = sorted(facts[component.component_id], key=lambda item: item["component_id"])
            required = set()
            for fact in normalized:
                try:
                    required_id = type(component.component_id)(fact["component_id"])
                except (KeyError, TypeError, ValueError):
                    raise SliceMergeError("An authenticated dependency fact is invalid.") from None
                if required_id not in by_component or required_id == component.component_id:
                    raise SliceMergeError("A dependency fact is outside this signed restore operation.")
                required.add(required_id)
            current = by_component[component.component_id]
            if current.dependency_facts and current.dependency_facts != normalized:
                raise SliceMergeError("Authenticated dependency facts changed across merge attempts.")
            if not current.dependency_facts and normalized:
                B1RestoreComponentState.objects.using(using).filter(pk=current.pk).update(
                    dependency_facts=normalized
                )
            missing.update(
                value for value in required
                if value not in supplied
                and by_component[value].state != B1RestoreComponentState.State.RESTORED
            )
    return missing


def dependency_wait(components, *, using):
    with transaction.atomic(using=using):
        ids = [item.pk for item in components]
        list(B1RestoreComponentState.objects.using(using).select_for_update().filter(pk__in=ids))
        B1RestoreComponentState.objects.using(using).filter(pk__in=ids).update(
            state=B1RestoreComponentState.State.DEPENDENCY_WAIT,
            merge_checkpoint="",
        )


def verify_constraints_and_reservations(operation_id, components, *, using):
    connection = connections[using]
    connection.check_constraints()
    entries = list(B1ReservationEntry.objects.using(using).filter(
        operation_id=operation_id,
        component_id__in=[item.component_id for item in components],
    ))
    if any(item.installed_at is None for item in entries):
        raise SliceMergeError("A component reservation is not installed at final verification.")
    targets = {
        (
            item.safe_payload.get("schema")
            or item.safe_payload.get("enforcement", {}).get("schema")
            or "public",
            item.safe_payload.get("table")
            or item.safe_payload.get("enforcement", {}).get("table"),
        )
        for item in entries
    }
    with connection.cursor() as cursor:
        for schema, table in targets:
            if not table:
                raise SliceMergeError("An installed reservation lost its target table.")
            cursor.execute(
                "SELECT 1 FROM pg_catalog.pg_trigger trigger "
                "JOIN pg_catalog.pg_class target ON target.oid = trigger.tgrelid "
                "JOIN pg_catalog.pg_namespace namespace ON namespace.oid = target.relnamespace "
                "WHERE namespace.nspname = %s AND target.relname = %s "
                "AND trigger.tgname = 'backup_b1_reservation_guard' "
                "AND trigger.tgenabled = 'O' AND NOT trigger.tgisinternal",
                [schema, table],
            )
            if cursor.fetchone() is None:
                raise SliceMergeError("A reservation database trigger is absent or disabled.")
    if B1FenceContinuity.objects.using(using).filter(
        operation_id=operation_id, enabled=False
    ).exists():
        raise SliceMergeError("A dependency fence lost continuity before final verification.")


def finalize(operation_id, components, schema, *, using):
    ids = [item.pk for item in components]
    component_ids = [item.component_id for item in components]
    with transaction.atomic(using=using):
        rows = list(B1RestoreComponentState.objects.using(using).select_for_update().filter(
            pk__in=ids
        ).order_by("component_id"))
        list(B1ReservationEntry.objects.using(using).select_for_update().filter(
            operation_id=operation_id, component_id__in=component_ids
        ).order_by("component_id", "pk"))
        if _same_checkpoint(rows) != B1RestoreComponentState.MergeCheckpoint.VERIFIED:
            raise SliceMergeError("Final merge commit requires completed verification.")
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.b1_merge_operation', %s, true)", [str(operation_id)]
            )
        drop_staging_schema(schema, using=using)
        B1RestoreComponentState.objects.using(using).filter(pk__in=ids).update(
            state=B1RestoreComponentState.State.RESTORED
        )
        clear_verified_reservations(operation_id, component_ids, using=using)


def mark_failed(operation_id, component_ids, *, using):
    if not component_ids:
        return
    with transaction.atomic(using=using):
        rows = B1RestoreComponentState.objects.using(using).select_for_update().filter(
            operation_id=operation_id, component_id__in=component_ids,
            state=B1RestoreComponentState.State.MERGING,
        )
        ids = list(rows.values_list("pk", flat=True))
        B1RestoreComponentState.objects.using(using).filter(pk__in=ids).update(
            state=B1RestoreComponentState.State.FAILED
        )


def _same_checkpoint(rows):
    values = {item.merge_checkpoint for item in rows}
    if len(values) != 1:
        raise SliceMergeError("A cross-linked merge group has divergent checkpoints.")
    return values.pop()
