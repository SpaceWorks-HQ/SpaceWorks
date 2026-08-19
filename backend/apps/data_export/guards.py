"""Executable drift guards for the declarative export contract."""

import re
from collections import Counter, defaultdict

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from apps.separability.registry import runtime_active

from .datasets import DATASETS
from .fields import FIELDS, USER_PROJECTIONS
from .models import EXPORTED_MODELS, MODELS
from .references import (
    JSON_FIELDS,
    POLYMORPHIC_PAIRS,
    RAW_USER_REFERENCE_FIELDS,
    RELATIONAL_USER_FIELDS,
    SEMANTIC_REFERENCES,
    USER_EDGES,
)
from .traversals import NON_TRAVERSABLE, TRAVERSALS
from .types import (
    Emitted,
    Fidelity,
    Omitted,
    OUTPUT_DISPOSITIONS,
    PERMITTED_SOURCE_DISPOSITIONS,
    Redacted,
)

CREDENTIAL_NAME = re.compile(
    r"password|secret|token|credential|webhook_url|digest|verifier|state|api_key",
    re.IGNORECASE,
)
REVIEWED_NON_CREDENTIAL = {
    ("makerspaces.MembershipRequest", "state"): "Durable request workflow state.",
    (
        "tenant_migration.ExternalTenantReference",
        "source_archive_digest",
    ): "Archive integrity identifier, not an authentication credential.",
    (
        "apiclients.ApiClient",
        "previous_secret_valid_until",
    ): "Expiry timestamp for the rotation grace window; the secret itself is omitted.",
}


class RegistryError(AssertionError):
    pass


def internal_models():
    return tuple(
        model
        for model in apps.get_models()
        if model.__module__.startswith("apps.") and not model._meta.proxy
    )


def validate_all(
    *, datasets=DATASETS, fields=FIELDS, traversals=TRAVERSALS,
    user_edges=USER_EDGES, semantic_references=SEMANTIC_REFERENCES
):
    validate_model_and_field_coverage(fields)
    validate_dataset_contract(datasets, fields, traversals)
    validate_user_edges(user_edges)
    validate_semantic_references(semantic_references)
    validate_credentials(fields)
    validate_user_projection(datasets)
    if runtime_active("tenant_migration"):
        # Migration semantics are separable. Keep this import behind the runtime
        # guard so a tombstoned deployment can still validate REDACTED exports.
        from apps.tenant_migration.reference_guards import validate_reference_registry

        validate_reference_registry()


def validate_model_and_field_coverage(fields=FIELDS):
    actual_models = {model._meta.label for model in internal_models()}
    _equal("model dispositions", set(MODELS), actual_models)
    for fidelity in Fidelity:
        for label in EXPORTED_MODELS | {"accounts.User"}:
            model = apps.get_model(label)
            actual = {
                field.name
                for field in model._meta.get_fields()
                if field.concrete or field.many_to_many
            }
            declared = {
                field_name
                for (candidate, model_label, field_name) in fields
                if candidate is fidelity and model_label == label
            }
            _equal(f"{fidelity} field dispositions for {label}", declared, actual)


def validate_dataset_contract(datasets=DATASETS, fields=FIELDS, traversals=TRAVERSALS):
    rows = list(datasets.values()) if isinstance(datasets, dict) else list(datasets)
    identity_counts = Counter((row.fidelity, row.path) for row in rows)
    duplicate_paths = [key for key, count in identity_counts.items() if count != 1]
    if duplicate_paths:
        raise RegistryError(f"duplicate dataset paths: {duplicate_paths}")

    models_by_fidelity = defaultdict(set)
    consumed = defaultdict(set)
    omissions = defaultdict(dict)
    for dataset in rows:
        models_by_fidelity[dataset.fidelity].add(dataset.model)
        omissions[(dataset.fidelity, dataset.model)].update(dataset.explicit_omissions)
        names = [column.name for column in dataset.columns]
        if len(names) != len(set(names)):
            raise RegistryError(f"duplicate columns in {dataset.path}")
        source_paths = [source for column in dataset.columns for source in column.sources]
        if len(source_paths) != len(set(source_paths)):
            raise RegistryError(f"duplicate source paths in {dataset.path}")
        for column in dataset.columns:
            for source in column.sources:
                resolved = resolve_source_path(
                    dataset.fidelity, dataset.model, source, traversals, fields
                )
                for label, field_name, disposition in resolved:
                    if isinstance(disposition, Omitted):
                        raise RegistryError(f"{dataset.path}:{column.name} launders omitted {label}.{field_name}")
                    if isinstance(disposition, Redacted):
                        direct_redaction = (
                            isinstance(column.disposition, Redacted)
                            and len(column.sources) == 1
                            and source == field_name
                            and label == dataset.model
                        )
                        if not direct_redaction:
                            raise RegistryError(f"{dataset.path}:{column.name} launders redacted {label}.{field_name}")
                    elif not isinstance(disposition, PERMITTED_SOURCE_DISPOSITIONS):
                        raise RegistryError(f"incompatible source {label}.{field_name}")
                terminal = resolved[-1]
                consumed[(dataset.fidelity, terminal[0])].add(terminal[1])
        validate_keyset(dataset)

    for fidelity in Fidelity:
        covered = models_by_fidelity[fidelity] - {"accounts.User"}
        _equal(f"{fidelity} exported-model dataset coverage", covered, set(EXPORTED_MODELS))
        for label in EXPORTED_MODELS | {"accounts.User"}:
            for (candidate, model_label, field_name), disposition in fields.items():
                if candidate is not fidelity or model_label != label:
                    continue
                if not isinstance(disposition, OUTPUT_DISPOSITIONS):
                    continue
                if field_name in consumed[(fidelity, label)]:
                    continue
                reason = omissions[(fidelity, label)].get(field_name)
                if not reason:
                    raise RegistryError(f"unconsumed output promise: {fidelity} {label}.{field_name}")


def resolve_source_path(
    fidelity, root_label, source, traversals=TRAVERSALS, fields=FIELDS
):
    model = apps.get_model(root_label)
    resolved = []
    parts = source.split("__")
    for index, part in enumerate(parts):
        field = _field_by_name_or_attname(model, part)
        if field.many_to_many:
            raise RegistryError(f"M2M traversal is forbidden: {model._meta.label}.{field.name}")
        disposition = fields.get((fidelity, model._meta.label, field.name))
        if disposition is None:
            raise RegistryError(f"unclassified source field: {model._meta.label}.{field.name}")
        resolved.append((model._meta.label, field.name, disposition))
        if index == len(parts) - 1:
            continue
        if not field.is_relation or field.related_model is None:
            raise RegistryError(f"source path crosses scalar field: {source}")
        hop = (model._meta.label, field.name)
        if hop in NON_TRAVERSABLE or hop not in traversals[fidelity]:
            raise RegistryError(f"relationship hop is not permitted: {hop}")
        model = field.related_model
    return tuple(resolved)


def validate_keyset(dataset):
    model = apps.get_model(dataset.model)
    fields = [_field_by_name_or_attname(model, name) for name in dataset.keyset]
    if any(field.null for field in fields):
        raise RegistryError(f"nullable keyset in {dataset.path}")
    names = tuple(field.name for field in fields)
    individually_unique = any(field.primary_key or field.unique for field in fields)
    declared_unique = any(
        tuple(constraint.fields) == names
        for constraint in model._meta.constraints
        if isinstance(constraint, models.UniqueConstraint) and constraint.fields
    )
    if not individually_unique and not declared_unique and names not in model._meta.unique_together:
        raise RegistryError(f"keyset is not a total order in {dataset.path}: {names}")


def validate_user_edges(user_edges=USER_EDGES):
    user = apps.get_model("accounts.User")
    relational = set()
    raw = set()
    for model in internal_models():
        for field in model._meta.get_fields():
            if field.concrete and field.is_relation and field.related_model is user:
                relational.add((model._meta.label, field.name))
            elif (
                field.concrete
                and isinstance(field, models.IntegerField)
                and field.name.endswith(("user_id", "actor_id"))
            ):
                raw.add((model._meta.label, field.name))
    _equal("relational user edges", relational, set(RELATIONAL_USER_FIELDS))
    _equal("raw user edges", raw, set(RAW_USER_REFERENCE_FIELDS))
    expected = relational | raw
    for fidelity in Fidelity:
        declared = {
            (label, field)
            for candidate, label, field in user_edges
            if candidate is fidelity
        }
        _equal(f"{fidelity} user-edge decisions", declared, expected)


def validate_semantic_references(semantic_references=SEMANTIC_REFERENCES):
    actual_polymorphic = set()
    actual_json = set()
    for label in EXPORTED_MODELS:
        model = apps.get_model(label)
        names = {field.name for field in model._meta.get_fields() if field.concrete}
        if {"target_type", "target_id"} <= names:
            actual_polymorphic.add((label, "target_type+target_id"))
        for field in model._meta.get_fields():
            if isinstance(field, models.JSONField):
                actual_json.add((label, field.name))
    _equal("polymorphic reference pairs", actual_polymorphic, set(POLYMORPHIC_PAIRS))
    _equal("JSON reference schemas", actual_json, set(JSON_FIELDS))
    for fidelity in Fidelity:
        expected = {
            (label, location) for label, location in POLYMORPHIC_PAIRS
        } | {(label, f"json:{field}") for label, field in JSON_FIELDS}
        declared = {
            (label, location)
            for candidate, label, location in semantic_references
            if candidate is fidelity and semantic_references[(candidate, label, location)]
        }
        _equal(f"{fidelity} semantic-reference decisions", declared, expected)


def validate_credentials(fields=FIELDS):
    for (fidelity, label, field_name), disposition in fields.items():
        if not CREDENTIAL_NAME.search(field_name):
            continue
        if isinstance(disposition, Omitted) or (label, field_name) in REVIEWED_NON_CREDENTIAL:
            continue
        raise RegistryError(f"credential-like field not omitted: {fidelity} {label}.{field_name}")


def validate_user_projection(datasets=DATASETS):
    for fidelity in Fidelity:
        dataset = datasets[(fidelity, "global/users.csv")]
        actual = {column.name for column in dataset.columns}
        _equal(f"{fidelity} User projection", actual, set(USER_PROJECTIONS[fidelity]))


def _field_by_name_or_attname(model, name):
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        for field in model._meta.get_fields():
            if getattr(field, "attname", None) == name:
                return field
        raise RegistryError(f"source path does not resolve: {model._meta.label}.{name}") from None


def _equal(subject, declared, actual):
    if declared != actual:
        raise RegistryError(
            f"{subject} drifted; missing={sorted(actual - declared)}, extra={sorted(declared - actual)}"
        )
