"""Shared, deny-by-default canonicalizers for E7 values and catalog SQL."""

from dataclasses import dataclass
import hashlib
import json
from typing import Callable

from apps.backup.catalog_casts import canonicalize_varchar_array_text_casts
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_catalog import IndexComponent, UniqueRule


SUPPORTED_POSTGRES_MAJORS = frozenset({14, 15, 16, 17})


@dataclass(frozen=True)
class Canonicalizer:
    identity: str
    type_names: frozenset[str]
    operator_classes: frozenset[str]
    sql_template: str
    supported_majors: frozenset[int] = SUPPORTED_POSTGRES_MAJORS
    catalog_rewriter: Callable[[str], str] | None = None

    def sql(self, expression):
        return self.sql_template.format(expression=expression)

    def catalog_definition(self, definition):
        if self.catalog_rewriter is None:
            return definition
        return self.catalog_rewriter(definition)


CANONICALIZERS = (
    Canonicalizer(
        "postgres-int-send-v1",
        frozenset({"int2", "int4", "int8"}),
        frozenset({"pg_catalog.int2_ops", "pg_catalog.int4_ops", "pg_catalog.int8_ops"}),
        "pg_catalog.int8send(({expression})::bigint)",
    ),
    Canonicalizer(
        "postgres-uuid-send-v1", frozenset({"uuid"}),
        frozenset({"pg_catalog.uuid_ops"}),
        "pg_catalog.uuid_send(({expression})::uuid)",
    ),
    Canonicalizer(
        "postgres-bytea-send-v1", frozenset({"bytea"}),
        frozenset({"pg_catalog.bytea_ops"}),
        "pg_catalog.bytea_send(({expression})::bytea)",
    ),
    Canonicalizer(
        "postgres-deterministic-text-utf8-v1",
        frozenset({"text", "varchar", "name"}),
        frozenset({"pg_catalog.text_ops", "pg_catalog.varchar_ops", "pg_catalog.name_ops"}),
        "pg_catalog.convert_to(({expression})::text, 'UTF8')",
    ),
    Canonicalizer(
        "postgres-bpchar-trim-utf8-v1", frozenset({"bpchar"}),
        frozenset({"pg_catalog.bpchar_ops"}),
        "pg_catalog.convert_to(pg_catalog.rtrim(({expression})::text, ' '), 'UTF8')",
    ),
    Canonicalizer(
        "postgres-varchar-array-text-deparse-v1",
        frozenset(), frozenset(), "",
        catalog_rewriter=canonicalize_varchar_array_text_casts,
    ),
)


def canonicalizer_for(component: IndexComponent, postgres_major: int):
    type_name = component.type_identity.split(".", 1)[-1].split(":", 1)[0]
    for item in CANONICALIZERS:
        if (
            postgres_major in item.supported_majors
            and type_name in item.type_names
            and component.operator_class in item.operator_classes
            and _collation_is_byte_exact(component)
        ):
            return item
    return None


def canonicalize_catalog_definition(definition: str) -> str:
    """Apply only the catalog rewrites proved in this canonicalizer registry."""

    canonical = definition
    for item in CANONICALIZERS:
        canonical = item.catalog_definition(canonical)
    return canonical


def canonicalizer_identity(rule: UniqueRule, postgres_major: int) -> str:
    values = []
    for component in rule.components:
        item = canonicalizer_for(component, postgres_major)
        if item is None:
            raise ValueError(f"No proved canonicalizer for {rule.index_name}.")
        values.append(item.identity)
    return _digest({"version": "b1-component-canonicalizers-v1", "values": values})


def component_canonicalizer_identities(rule: UniqueRule, postgres_major: int):
    result = []
    for component in rule.components:
        canonicalizer = canonicalizer_for(component, postgres_major)
        if canonicalizer is None:
            raise BackupBuildError(
                f"No proved canonicalizer exists for {rule.index_name}."
            )
        result.append({
            "type_identity": component.type_identity,
            "canonicalizer_identity": canonicalizer.identity,
        })
    return tuple(result)


def _collation_is_byte_exact(component):
    if not component.collation:
        return True
    if not component.collation_deterministic:
        return False
    if component.collation_version != component.collation_actual_version:
        return False
    return (
        component.collation in {"pg_catalog.C", "pg_catalog.POSIX"}
        and component.collation_provider == "c"
        and component.collation_locale in {"C", "POSIX"}
    )


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()
