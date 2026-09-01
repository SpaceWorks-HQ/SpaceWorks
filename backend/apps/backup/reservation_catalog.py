"""Exact PostgreSQL unique-index catalog identities for Lane E reservations."""

from dataclasses import dataclass
import hashlib
import json

from django.db import connections

from apps.backup.recipient_selection import BackupBuildError


@dataclass(frozen=True)
class IndexComponent:
    position: int
    expression_sql: str
    source_column: str
    type_identity: str
    operator_class: str
    collation: str
    collation_provider: str
    collation_deterministic: bool
    collation_locale: str
    collation_version: str
    collation_actual_version: str


@dataclass(frozen=True)
class UniqueRule:
    schema: str
    table: str
    index_name: str
    exact_index_definition: str
    exact_constraint_definition: str
    predicate_sql: str
    nulls_not_distinct: bool
    deferrable: bool
    initially_deferred: bool
    primary: bool
    components: tuple[IndexComponent, ...]

    @property
    def definition_sha256(self):
        return _digest(self.definition_payload())

    @property
    def identity(self):
        return _digest({"registry": "b1-unique-rule-v1", **self.definition_payload()})

    def definition_payload(self):
        # Lazy import avoids the catalog/registry type-definition cycle while
        # keeping every E7 definition identity on the shared canonicalizer path.
        from apps.backup.reservation_canonicalizers import (
            canonicalize_catalog_definition,
        )

        canonicalize = canonicalize_catalog_definition
        return {
            "schema": self.schema,
            "table": self.table,
            "index_name": self.index_name,
            "key_components": [
                {
                    **component.__dict__,
                    "expression_sql": canonicalize(component.expression_sql),
                }
                for component in self.components
            ],
            "nulls_not_distinct": self.nulls_not_distinct,
            "predicate_sql": canonicalize(self.predicate_sql),
            "deferrable": self.deferrable,
            "initially_deferred": self.initially_deferred,
            "primary": self.primary,
            "exact_index_definition": canonicalize(self.exact_index_definition),
            "exact_constraint_definition": canonicalize(
                self.exact_constraint_definition
            ),
        }


def load_unique_rules(using="default") -> tuple[UniqueRule, ...]:
    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute(_CATALOG_SQL)
        records = cursor.fetchall()
    grouped = {}
    for record in records:
        header = record[:13]
        component = IndexComponent(
            position=record[13],
            expression_sql=record[14],
            source_column=record[15] or "",
            type_identity=record[16],
            operator_class=record[17],
            collation=record[18] or "",
            collation_provider=record[19] or "",
            collation_deterministic=record[20] is not False,
            collation_locale=record[21] or "",
            collation_version=record[22] or "",
            collation_actual_version=record[23] or "",
        )
        grouped.setdefault(header, []).append(component)
    result = []
    for header, components in grouped.items():
        (
            schema, table, index_name, index_definition,
            constraint_definition, predicate, nulls_not_distinct,
            deferrable, initially_deferred, _index_oid, _table_oid,
            _constraint_oid, primary,
        ) = header
        result.append(UniqueRule(
            schema=schema,
            table=table,
            index_name=index_name,
            exact_index_definition=index_definition,
            exact_constraint_definition=constraint_definition or "",
            predicate_sql=predicate or "",
            nulls_not_distinct=bool(nulls_not_distinct),
            deferrable=bool(deferrable),
            initially_deferred=bool(initially_deferred),
            primary=bool(primary),
            components=tuple(sorted(components, key=lambda item: item.position)),
        ))
    return tuple(sorted(result, key=lambda item: (item.schema, item.table, item.index_name)))


def assert_rule_reproduced(expected: UniqueRule, using="default"):
    actual = {item.identity: item for item in load_unique_rules(using)}.get(expected.identity)
    if actual is None or actual.definition_payload() != expected.definition_payload():
        raise BackupBuildError(
            f"Target PostgreSQL did not reproduce unique rule {expected.index_name}."
        )
    return actual


def _digest(value) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_CATALOG_SQL = r"""
SELECT ns.nspname,
       tbl.relname,
       idx.relname,
       pg_catalog.pg_get_indexdef(i.indexrelid),
       pg_catalog.pg_get_constraintdef(con.oid, true),
       pg_catalog.pg_get_expr(i.indpred, i.indrelid, true),
       COALESCE((to_jsonb(i)->>'indnullsnotdistinct')::boolean, false),
       COALESCE(con.condeferrable, false),
       COALESCE(con.condeferred, false),
       i.indexrelid,
       i.indrelid,
       con.oid,
       i.indisprimary,
       keys.ordinality,
       pg_catalog.pg_get_indexdef(i.indexrelid, keys.ordinality::integer, true),
       source_attribute.attname,
       type_ns.nspname || '.' || typ.typname || ':' ||
           pg_catalog.format_type(index_attribute.atttypid, index_attribute.atttypmod),
       op_ns.nspname || '.' || op.opcname,
       CASE WHEN coll.oid IS NULL THEN ''
            ELSE coll_ns.nspname || '.' || coll.collname END,
       COALESCE(coll.collprovider::text, ''),
       COALESCE(coll.collisdeterministic, true),
       COALESCE(
           to_jsonb(coll)->>'collcollate',
           to_jsonb(coll)->>'colliculocale',
           to_jsonb(coll)->>'colllocale',
           ''
       ),
       COALESCE(coll.collversion, ''),
       COALESCE(pg_catalog.pg_collation_actual_version(coll.oid), '')
  FROM pg_catalog.pg_index i
  JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
  JOIN pg_catalog.pg_class tbl ON tbl.oid = i.indrelid
  JOIN pg_catalog.pg_namespace ns ON ns.oid = tbl.relnamespace
  LEFT JOIN pg_catalog.pg_constraint con
    ON con.conindid = i.indexrelid
   AND con.conrelid = i.indrelid
   AND con.contype IN ('p', 'u', 'x')
  CROSS JOIN LATERAL unnest(i.indkey, i.indclass, i.indcollation)
      WITH ORDINALITY AS keys(attnum, opclass_oid, collation_oid, ordinality)
  JOIN pg_catalog.pg_attribute index_attribute
    ON index_attribute.attrelid = i.indexrelid
   AND index_attribute.attnum = keys.ordinality
  JOIN pg_catalog.pg_type typ ON typ.oid = index_attribute.atttypid
  JOIN pg_catalog.pg_namespace type_ns ON type_ns.oid = typ.typnamespace
  JOIN pg_catalog.pg_opclass op ON op.oid = keys.opclass_oid
  JOIN pg_catalog.pg_namespace op_ns ON op_ns.oid = op.opcnamespace
  LEFT JOIN pg_catalog.pg_collation coll ON coll.oid = NULLIF(keys.collation_oid, 0)
  LEFT JOIN pg_catalog.pg_namespace coll_ns ON coll_ns.oid = coll.collnamespace
  LEFT JOIN pg_catalog.pg_attribute source_attribute
    ON source_attribute.attrelid = i.indrelid
   AND source_attribute.attnum = NULLIF(keys.attnum, 0)
 WHERE ns.nspname = 'public'
   AND i.indisunique
   AND i.indisvalid
 ORDER BY ns.nspname, tbl.relname, idx.relname, keys.ordinality
"""
