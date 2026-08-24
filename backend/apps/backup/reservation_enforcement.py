"""Target-side binding and installation of database-enforced E7 reservations."""

import base64
import hashlib
import json

from django.db import connections, transaction
from django.utils import timezone

from apps.backup.models import B1FenceContinuity, B1ReservationEntry
from apps.backup.postgres_client import server_major
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.reservation_registry import (
    canonicalizer_for,
    canonicalizer_identity,
    component_canonicalizer_identities,
)


FENCE_KINDS = frozenset({
    B1ReservationEntry.Kind.BROAD_FENCE,
    B1ReservationEntry.Kind.RELATIONSHIP_FENCE,
    B1ReservationEntry.Kind.OBJECT_NAMESPACE,
})


def install_reservation_entry(
    *, operation_id, component_id, kind, fact, reservation_salt=None, using="default"
):
    """Bind a signed fact to the reproduced catalog and install its row trigger.

    The database's AFTER trigger creates the target-table guard in the same
    transaction as this immutable row. A commitment gets target-derived SQL only
    after its exact catalog and canonicalizer identities reproduce successfully.
    """

    payload = _catalog_bound_payload(
        fact, kind=kind, reservation_salt=reservation_salt, using=using
    )
    identity = payload.get("constraint_identity") or payload.get("registry_identity")
    if not _is_digest(identity) or not _is_digest(payload.get("definition_sha256")):
        raise BackupBuildError("A reservation identity or definition digest is invalid.")
    with transaction.atomic(using=using):
        entry = B1ReservationEntry.objects.using(using).create(
            operation_id=operation_id,
            component_id=component_id,
            registry_identity=identity,
            kind=kind,
            definition_sha256=payload["definition_sha256"],
            safe_payload=payload,
            installed_at=timezone.now(),
        )
        trigger_oid = _installed_trigger_oid(payload, using=using)
        if kind in FENCE_KINDS:
            continuity, created = B1FenceContinuity.objects.using(using).get_or_create(
                operation_id=operation_id,
                registry_identity=identity,
                defaults={
                    "definition_sha256": payload["definition_sha256"],
                    "trigger_oids": [trigger_oid],
                },
            )
            if not created and (
                continuity.definition_sha256 != payload["definition_sha256"]
                or continuity.trigger_oids != [trigger_oid]
            ):
                raise BackupBuildError("Fence continuity does not match the installed trigger.")
    return entry


def _catalog_bound_payload(fact, *, kind, reservation_salt, using):
    payload = dict(fact)
    if kind != B1ReservationEntry.Kind.COMMITMENT:
        _validate_fact_digest(payload)
        return payload
    rules = {item.identity: item for item in load_unique_rules(using)}
    rule = rules.get(payload.get("constraint_identity"))
    major = _server_major(using)
    if rule is None or rule.definition_sha256 != payload.get("definition_sha256"):
        raise BackupBuildError("The commitment unique rule was not reproduced exactly.")
    expected_components = list(component_canonicalizer_identities(rule, major))
    if (
        payload.get("canonicalizer_identity") != canonicalizer_identity(rule, major)
        or payload.get("key_component_identities") != expected_components
    ):
        raise BackupBuildError("The commitment names an unknown canonicalizer identity.")
    try:
        salt = (
            bytes(reservation_salt)
            if isinstance(reservation_salt, (bytes, bytearray))
            else base64.b64decode(reservation_salt, validate=True)
        )
    except (TypeError, ValueError) as exc:
        raise BackupBuildError("The commitment reservation salt is invalid.") from exc
    if len(salt) != 32:
        raise BackupBuildError("The commitment reservation salt must be 32 bytes.")
    components = []
    for component in rule.components:
        canonicalizer = canonicalizer_for(component, major)
        if canonicalizer is None:
            raise BackupBuildError("The target has no proved commitment canonicalizer.")
        components.append({
            "type_identity": component.type_identity,
            "canonicalizer_identity": canonicalizer.identity,
            "canonicalizer_sql": canonicalizer.sql(component.expression_sql),
        })
    payload.update({
        "reservation_salt": base64.b64encode(salt).decode("ascii"),
        "enforcement": {
            "schema": rule.schema,
            "table": rule.table,
            "predicate_sql": rule.predicate_sql,
            "nulls_not_distinct": rule.nulls_not_distinct,
            "components": components,
        },
    })
    return payload


def _validate_fact_digest(payload):
    expected = payload.get("definition_sha256")
    definition = dict(payload)
    definition.pop("definition_sha256", None)
    if expected != _digest(definition):
        raise BackupBuildError("The database fence definition digest is invalid.")


def _installed_trigger_oid(payload, *, using):
    enforcement = payload.get("enforcement", {})
    schema = payload.get("schema", enforcement.get("schema", "public"))
    table = payload.get("table", enforcement.get("table"))
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT trigger.oid FROM pg_catalog.pg_trigger trigger "
            "JOIN pg_catalog.pg_class target ON target.oid = trigger.tgrelid "
            "JOIN pg_catalog.pg_namespace namespace ON namespace.oid = target.relnamespace "
            "WHERE namespace.nspname = %s AND target.relname = %s "
            "AND trigger.tgname = 'backup_b1_reservation_guard' "
            "AND trigger.tgenabled = 'O' AND NOT trigger.tgisinternal",
            [schema, table],
        )
        row = cursor.fetchone()
    if row is None:
        raise BackupBuildError("The database reservation trigger was not installed and enabled.")
    return row[0]


def _server_major(using):
    if using == "default":
        return server_major()
    with connections[using].cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        return int(cursor.fetchone()[0]) // 10000


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()


def _is_digest(value):
    return (
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
