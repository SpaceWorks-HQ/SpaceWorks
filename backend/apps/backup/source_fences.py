"""Manifest-safe broad relationship and object fences derived from registries."""

import hashlib
import json

from apps.backup.main_projection_registry import boundary_rules, sovereign_q
from apps.backup.object_ownership_registry import AUDIT_META_OBJECT_VARIANTS


def broad_unique_fence(rule, component_counts):
    definition = {
        "version": "b1-broad-unique-fence-v1",
        "constraint_identity": rule.identity,
        "schema": rule.schema,
        "table": rule.table,
        "columns": [item.source_column for item in rule.components],
        "operations": ["insert", "update"],
        "component_ids": [
            item["component_id"] for item in component_counts if item["count"]
        ],
    }
    return {**definition, "definition_sha256": digest(definition)}


def relationship_fences(using, rules, makerspace_components):
    """Fence every undisclosed endpoint family, including inbound row creation."""

    facts = []
    for boundary in boundary_rules(rules):
        component_ids = _owning_components(
            boundary.target_rule.model,
            boundary.target_predicate,
            using,
            makerspace_components,
        )
        if not component_ids:
            continue
        facts.extend((
            _relationship_fact(
                identity=(
                    f"boundary-inbound:{boundary.source_model._meta.db_table}:"
                    f"{boundary.field.column}:{boundary.target_rule.model._meta.db_table}"
                ),
                table=boundary.source_model._meta.db_table,
                columns=(boundary.field.column,),
                operations=("insert", "update", "delete"),
                dependency_kind="boundary_inbound_fk",
                component_ids=component_ids,
            ),
            _relationship_fact(
                identity=f"boundary-endpoint:{boundary.target_rule.model._meta.db_table}",
                table=boundary.target_rule.model._meta.db_table,
                columns=(boundary.target_rule.model._meta.pk.column,),
                operations=("insert", "update", "delete"),
                dependency_kind="boundary_endpoint",
                component_ids=component_ids,
            ),
        ))
    if makerspace_components:
        facts.append(_relationship_fact(
            identity="semantic-reference:audit-auditlog-v1",
            table="audit_auditlog",
            columns=("target_type", "target_id", "meta"),
            operations=("insert", "update", "delete"),
            dependency_kind="semantic_reference",
            component_ids=tuple(sorted(str(value) for value in makerspace_components.values())),
            extra={"registered_variants": sorted(AUDIT_META_OBJECT_VARIANTS)},
        ))
    return _deduplicate(facts)


def object_namespace_fences(object_plan, makerspace_components):
    grouped = {}
    for reference in object_plan.references:
        if not reference.candidate_owner or not reference.candidate_owner.startswith("slice:"):
            continue
        model_label, _pk, field_name, *_rest = reference.site.split(":")
        key = (model_label, field_name, reference.bucket_kind)
        component_id = makerspace_components.get(reference.canonical_makerspace_id)
        if component_id is None:
            continue
        grouped.setdefault(key, set()).add(str(component_id))
    facts = []
    from django.apps import apps

    for (model_label, field_name, bucket_kind), components in sorted(grouped.items()):
        model = apps.get_model(model_label)
        field = model._meta.get_field(field_name)
        definition = {
            "version": "b1-object-namespace-fence-v1",
            "registry_identity": digest({
                "model": model_label,
                "field": field_name,
                "bucket_kind": bucket_kind,
            }),
            "schema": "public",
            "table": model._meta.db_table,
            "columns": [field.column],
            "bucket_kind": bucket_kind,
            "operations": ["insert", "update", "delete", "overwrite"],
            "component_ids": sorted(components),
        }
        facts.append({**definition, "definition_sha256": digest(definition)})
    return tuple(facts)


def _owning_components(model, predicate, using, makerspace_components):
    result = []
    manager = model._base_manager.using(using)
    for makerspace_id, component_id in sorted(makerspace_components.items()):
        if manager.filter(sovereign_q(predicate, (makerspace_id,))).exists():
            result.append(str(component_id))
    return tuple(result)


def _relationship_fact(
    *, identity, table, columns, operations, dependency_kind, component_ids, extra=None
):
    definition = {
        "version": "b1-relationship-fence-v1",
        "registry_identity": digest(identity),
        "schema": "public",
        "table": table,
        "columns": list(columns),
        "operations": list(operations),
        "dependency_kind": dependency_kind,
        "component_ids": list(component_ids),
        **(extra or {}),
    }
    return {**definition, "definition_sha256": digest(definition)}


def _deduplicate(facts):
    unique = {fact["definition_sha256"]: fact for fact in facts}
    return tuple(unique[key] for key in sorted(unique))


def digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()
