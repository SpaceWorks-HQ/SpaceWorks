"""Capture private reservation facts from the frozen PostgreSQL source."""

from dataclasses import dataclass, replace
import base64
import hashlib
import json

from django.db import connections
from django.db.models import Q

from apps.backup.main_projection_registry import (
    BoundaryDisposition,
    RowDisposition,
    boundary_queryset,
    boundary_rules,
    sovereign_q,
)
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.reservation_keys import (
    CanonicalComponent,
    fresh_run_salt,
    reservation_commitment,
    reservation_key_v1,
)
from apps.backup.reservation_registry import (
    ReservationMode,
    canonicalizer_for,
    canonicalizer_identity,
    component_canonicalizer_identities,
    reservation_mode,
)
from apps.backup.source_fences import (
    broad_unique_fence,
    object_namespace_fences,
    relationship_fences,
)
from apps.backup.source_sequence_reservations import sequence_facts


@dataclass(frozen=True)
class ReservationCapture:
    run_salt: bytes
    registry_digest: str
    commitments: tuple[dict, ...]
    broad_fences: tuple[dict, ...]
    relationship_fences: tuple[dict, ...]
    object_namespace_fences: tuple[dict, ...]
    sequence_facts: tuple[dict, ...]
    rule_proofs: tuple[dict, ...]
    raw_keys_by_component: dict[str, tuple[tuple[str, bytes], ...]]

    def manifest_facts(self):
        return {
            "reservation_salt": base64.b64encode(self.run_salt).decode("ascii"),
            "reservation_registry_digest": self.registry_digest,
            "reservation_commitments": list(self.commitments),
            "broad_fence_scopes": list(self.broad_fences),
            "relationship_fence_scopes": list(self.relationship_fences),
            "object_namespace_fences": list(self.object_namespace_fences),
            "sequence_reservations": list(self.sequence_facts),
        }

    def bind_object_plan(self, object_plan, makerspace_components):
        if self.object_namespace_fences:
            raise BackupBuildError("Object namespace fences were bound more than once.")
        return replace(
            self,
            object_namespace_fences=object_namespace_fences(
                object_plan, makerspace_components
            ),
        )


def capture_source_reservations(
    using, rules, makerspace_components, *, postgres_major
) -> ReservationCapture:
    """Capture only manifest-safe facts; raw canonical keys stay verifier-private."""

    if postgres_major not in {14, 15, 16, 17}:
        raise BackupBuildError("The source PostgreSQL version has no E7 canonicalizer proof.")
    salt = fresh_run_salt()
    unique_rules = load_unique_rules(using)
    table_rules_by_name = {item.model._meta.db_table: item for item in rules}
    rule_catalog = []
    commitments, fences, proofs = [], [], []
    raw_by_component = {str(value): [] for value in makerspace_components.values()}
    for unique in unique_rules:
        table_rule = table_rules_by_name.get(unique.table)
        if table_rule is None:
            continue
        mode = _effective_mode(unique, using, postgres_major)
        component_counts = []
        canonical_rows = {}
        for makerspace_id, component_id in sorted(makerspace_components.items()):
            queryset = _slice_queryset(
                table_rule, rules, using, (makerspace_id,)
            )
            rows = _evaluate_rule(
                using, unique, queryset, postgres_major,
                canonicalize=mode is ReservationMode.HIGH_ENTROPY_COMMITMENT,
            )
            component_counts.append({
                "component_id": str(component_id), "count": len(rows)
            })
            canonical_rows[str(component_id)] = rows
        slice_count = sum(item["count"] for item in component_counts)
        if slice_count == 0:
            continue
        source_count = _qualifying_count(using, unique, table_rule.model._base_manager.using(using).all())
        main_count = source_count - slice_count
        if main_count < 0:
            raise BackupBuildError(f"Reservation partition count underflow for {unique.index_name}.")
        fence_digest = ""
        if mode is ReservationMode.HIGH_ENTROPY_COMMITMENT:
            canonical_id = canonicalizer_identity(unique, postgres_major)
            component_identities = list(
                component_canonicalizer_identities(unique, postgres_major)
            )
            component_commitments = []
            for component_id, rows in canonical_rows.items():
                published = []
                for framed in rows:
                    if framed is None:
                        continue
                    raw_by_component[component_id].append((unique.identity, framed))
                    published.append(reservation_commitment(salt, framed))
                component_commitments.append({
                    "component_id": component_id,
                    "commitments": sorted(published),
                })
            commitments.append({
                "constraint_identity": unique.identity,
                "definition_sha256": unique.definition_sha256,
                "canonicalizer_identity": canonical_id,
                "key_component_identities": component_identities,
                "component_commitments": component_commitments,
            })
        elif mode is ReservationMode.BROAD_FENCE:
            fence = broad_unique_fence(unique, component_counts)
            fence_digest = fence["definition_sha256"]
            fences.append(fence)
        count_digest = _digest(component_counts)
        proofs.append({
            "constraint_identity": unique.identity,
            "definition_sha256": unique.definition_sha256,
            "reservation_mode": mode,
            "qualifying_source_row_count": source_count,
            "qualifying_main_row_count": main_count,
            "qualifying_slice_row_count": slice_count,
            "owning_component_count_digest": count_digest,
            "component_counts": component_counts,
            "broad_fence_definition_sha256": fence_digest,
            "partition_complete": "pending",
            "main_disjoint": "pending",
            "reconstruction_equal": "pending",
        })
        rule_catalog.append(unique.definition_payload())
    sequences = _bind_sequence_rules(sequence_facts(using), unique_rules)
    relationships = relationship_fences(using, rules, makerspace_components)
    return ReservationCapture(
        run_salt=salt,
        registry_digest=_digest({
            "version": "b1-reservation-registry-v1",
            "unique_rules": rule_catalog,
            "sequence_facts": sequences,
            "relationship_fences": relationships,
        }),
        commitments=tuple(sorted(commitments, key=_sort_fact)),
        broad_fences=tuple(sorted(fences, key=_sort_fact)),
        relationship_fences=relationships,
        object_namespace_fences=(),
        sequence_facts=sequences,
        rule_proofs=tuple(sorted(proofs, key=lambda item: item["constraint_identity"])),
        raw_keys_by_component={
            key: tuple(sorted(value)) for key, value in raw_by_component.items()
        },
    )


def _slice_queryset(table_rule, rules, using, makerspace_ids):
    query = None
    if table_rule.disposition == RowDisposition.COPY_TO_SLICE:
        query = sovereign_q(table_rule.predicate, makerspace_ids)
    for boundary in boundary_rules(rules):
        if (
            boundary.source_rule == table_rule
            and boundary.disposition == BoundaryDisposition.DROP_ROW_TO_SLICE
        ):
            boundary_query = Q(pk__in=boundary_queryset(
                boundary, using, makerspace_ids
            ).values("pk"))
            query = boundary_query if query is None else query | boundary_query
    manager = table_rule.model._base_manager.using(using)
    return manager.none() if query is None else manager.filter(query)


def _effective_mode(rule, using, postgres_major):
    if rule.primary and len(rule.components) == 1 and rule.components[0].source_column:
        connection = connections[using]
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.pg_get_serial_sequence(%s, %s)",
                [f"{rule.schema}.{rule.table}", rule.components[0].source_column],
            )
            if cursor.fetchone()[0]:
                return ReservationMode.SEQUENCE_HIGH_WATER
    return reservation_mode(rule, postgres_major)


def _evaluate_rule(using, rule, queryset, postgres_major, *, canonicalize):
    if queryset.query.is_empty():
        return []
    if not canonicalize:
        return [None] * _qualifying_count(using, rule, queryset)
    connection = connections[using]
    query = queryset.order_by().values("pk").query
    subquery, params = query.get_compiler(using=using).as_sql()
    quote = connection.ops.quote_name
    canonicalizers = []
    for component in rule.components:
        canonicalizer = canonicalizer_for(component, postgres_major)
        if canonicalizer is None:
            raise BackupBuildError(f"Unique rule {rule.index_name} has no canonicalizer.")
        canonicalizers.append(canonicalizer.sql(component.expression_sql))
    predicate = rule.predicate_sql or "TRUE"
    sql = (
        f"SELECT {', '.join(canonicalizers)} FROM {quote(rule.schema)}.{quote(rule.table)} "
        f"WHERE {quote(queryset.model._meta.pk.column)} IN ({subquery}) "
        f"AND (({predicate}) IS TRUE)"
    )
    result = []
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        for row in cursor.fetchall():
            components = tuple(
                CanonicalComponent(spec.type_identity, None if value is None else bytes(value))
                for spec, value in zip(rule.components, row, strict=True)
            )
            result.append(reservation_key_v1(
                rule.identity, components,
                nulls_not_distinct=rule.nulls_not_distinct,
            ))
    return result


def _qualifying_count(using, rule, queryset):
    if queryset.query.is_empty():
        return 0
    connection = connections[using]
    query = queryset.order_by().values("pk").query
    subquery, params = query.get_compiler(using=using).as_sql()
    quote = connection.ops.quote_name
    predicate = rule.predicate_sql or "TRUE"
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FROM {quote(rule.schema)}.{quote(rule.table)} "
            f"WHERE {quote(queryset.model._meta.pk.column)} IN ({subquery}) "
            f"AND (({predicate}) IS TRUE)",
            params,
        )
        return cursor.fetchone()[0]


def _sort_fact(item):
    return tuple(str(item.get(key, "")) for key in (
        "constraint_identity", "component_id", "commitment", "definition_sha256"
    ))


def _bind_sequence_rules(facts, unique_rules):
    identities = {
        (rule.schema, rule.table, rule.components[0].source_column): rule
        for rule in unique_rules
        if rule.primary and len(rule.components) == 1
    }
    result = []
    for fact in facts:
        rule = identities.get((fact["schema"], fact["table"], fact["column"]))
        result.append({
            **fact,
            "constraint_identity": rule.identity if rule else "",
            "definition_sha256": rule.definition_sha256 if rule else "",
        })
    return tuple(result)


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()
