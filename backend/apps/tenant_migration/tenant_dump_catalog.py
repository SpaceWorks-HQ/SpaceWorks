"""Fail-closed model, table and field guards for the Lane D source catalog."""

from collections import Counter
import hashlib
import json

from django.apps import apps

from .tenant_dump_authority import AUTHORITY_FIELD_OVERRIDES
from .tenant_dump_field_snapshot import (
    AUTO_CREATED_FIELD_NAMES,
    FIRST_PARTY_FIELD_NAMES,
    THIRD_PARTY_FIELD_NAMES,
    UNMANAGED_FIELD_NAMES,
)
from .tenant_dump_model_catalog import (
    AUTO_CREATED_TABLE_RULES,
    FIRST_PARTY_APP_LABELS,
    FIRST_PARTY_MODEL_RULES,
    THIRD_PARTY_INSTALLED_APP_LABELS,
    THIRD_PARTY_MODEL_APP_LABELS,
    THIRD_PARTY_MODEL_RULES,
    UNMANAGED_MODEL_RULES,
    UNOWNED_TABLE_RULES,
)
from .tenant_dump_types import (
    AuthorityDisposition,
    AuthorityField,
    ModelDisposition,
    NoAuthorityField,
    authority,
)


class TenantDumpCatalogError(AssertionError):
    pass


# SHA-256 of the ordered model/table/field graph produced by ``catalog_schema``.
# Updating it is an explicit review act; runtime introspection never blesses drift.
CATALOG_SCHEMA_SHA256 = "e56b68cf7e2853e745f5bbf72040fa21229ac9b7727ad2e172cfc0f436e8a86c"


def catalog_models(apps_registry=apps):
    """Use Django's complete model universe, including generated M2M tables."""
    return tuple(
        model
        for model in apps_registry.get_models(include_auto_created=True)
        if not model._meta.proxy
    )


def governed_fields(model):
    """Match Django M2Ms even though they are not concrete columns."""
    return tuple(
        field
        for field in model._meta.get_fields()
        if field.concrete or field.many_to_many
    )


def catalog_schema(models=None):
    rows = []
    for model in models or catalog_models():
        rows.append({
            "app_label": model._meta.app_label,
            "auto_created": bool(model._meta.auto_created),
            "db_table": model._meta.db_table,
            "fields": sorted(field.name for field in governed_fields(model)),
            "label": model._meta.label,
            "managed": bool(model._meta.managed),
        })
    return sorted(rows, key=lambda item: item["label"])


def schema_digest(models=None):
    encoded = json.dumps(
        catalog_schema(models), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_field_rule(model_rule):
    if model_rule.disposition in {ModelDisposition.DROP, ModelDisposition.EMPTY}:
        return authority(AuthorityDisposition.DROP, model_rule.reason)
    if model_rule.disposition in {ModelDisposition.RESET, ModelDisposition.BOOTSTRAP}:
        return authority(AuthorityDisposition.RESET, model_rule.reason)
    if model_rule.disposition is ModelDisposition.PRESERVE_LIVE:
        return authority(AuthorityDisposition.PRESERVE, model_rule.reason)
    return NoAuthorityField(
        "Ordinary tenant row identity/content; it does not independently select "
        "target authority or disclosure."
    )


def build_field_policies():
    policies = {}
    universes = (
        (FIRST_PARTY_MODEL_RULES, FIRST_PARTY_FIELD_NAMES),
        (AUTO_CREATED_TABLE_RULES, AUTO_CREATED_FIELD_NAMES),
        (THIRD_PARTY_MODEL_RULES, THIRD_PARTY_FIELD_NAMES),
        (UNMANAGED_MODEL_RULES, UNMANAGED_FIELD_NAMES),
    )
    for model_rules, field_names in universes:
        if set(model_rules) != set(field_names):
            raise TenantDumpCatalogError(
                "Lane D model/field snapshot labels drifted; "
                f"missing={sorted(set(model_rules) - set(field_names))}, "
                f"extra={sorted(set(field_names) - set(model_rules))}"
            )
        for label, model_rule in model_rules.items():
            for field_name in field_names[label]:
                policies[(label, field_name)] = _default_field_rule(model_rule)
    for edge, rule in AUTHORITY_FIELD_OVERRIDES.items():
        if edge not in policies:
            raise TenantDumpCatalogError(
                f"Lane D authority override names an ungoverned field: {edge}"
            )
        policies[edge] = rule
    return policies


FIELD_POLICIES = build_field_policies()


def validate_field_coverage(models, declarations):
    actual = {
        (model._meta.label, field.name)
        for model in models
        for field in governed_fields(model)
    }
    declared = set(declarations)
    if declared != actual:
        raise TenantDumpCatalogError(
            "Lane D field catalog drifted; "
            f"missing={sorted(actual - declared)}, extra={sorted(declared - actual)}"
        )
    for edge, rule in declarations.items():
        if not isinstance(rule, (AuthorityField, NoAuthorityField)) or not rule.reason:
            raise TenantDumpCatalogError(f"Lane D field has no disposition/reason: {edge}")
        if isinstance(rule, AuthorityField) and (
            not rule.dispositions
            or any(not isinstance(item, AuthorityDisposition) for item in rule.dispositions)
        ):
            raise TenantDumpCatalogError(f"Lane D authority disposition is invalid: {edge}")


def validate_catalog(
    *,
    apps_registry=apps,
    field_policies=FIELD_POLICIES,
    expected_schema_digest=CATALOG_SCHEMA_SHA256,
    unmanaged_rules=UNMANAGED_MODEL_RULES,
):
    models = catalog_models(apps_registry)
    installed_apps = {config.label for config in apps_registry.get_app_configs()}
    _equal(
        "installed app allowlist",
        set(FIRST_PARTY_APP_LABELS | THIRD_PARTY_INSTALLED_APP_LABELS),
        installed_apps,
    )
    auto = {model._meta.label for model in models if model._meta.auto_created}
    unmanaged = {
        model._meta.label
        for model in models
        if not model._meta.auto_created and not model._meta.managed
    }
    first_party = {
        model._meta.label
        for model in models
        if not model._meta.auto_created
        and model._meta.managed
        and model._meta.app_label in FIRST_PARTY_APP_LABELS
    }
    third_party = {
        model._meta.label
        for model in models
        if not model._meta.auto_created
        and model._meta.managed
        and model._meta.app_label in THIRD_PARTY_MODEL_APP_LABELS
    }
    unknown_managed = {
        model._meta.label
        for model in models
        if not model._meta.auto_created
        and model._meta.managed
        and model._meta.app_label
        not in FIRST_PARTY_APP_LABELS | THIRD_PARTY_MODEL_APP_LABELS
    }
    _equal("first-party model universe", set(FIRST_PARTY_MODEL_RULES), first_party)
    _equal("auto-created through universe", set(AUTO_CREATED_TABLE_RULES), auto)
    _equal("third-party model universe", set(THIRD_PARTY_MODEL_RULES), third_party)
    _equal("unmanaged model universe", set(unmanaged_rules), unmanaged)
    if unknown_managed:
        raise TenantDumpCatalogError(
            f"managed models belong to an unreviewed app allowlist: {sorted(unknown_managed)}"
        )
    if any(rule.disposition is not ModelDisposition.REFUSE for rule in unmanaged_rules.values()):
        raise TenantDumpCatalogError("every unmanaged ORM model must be REFUSE")
    validate_field_coverage(models, field_policies)
    _validate_table_ownership(models)
    actual_digest = schema_digest(models)
    if expected_schema_digest != actual_digest:
        raise TenantDumpCatalogError(
            "Lane D schema/catalog digest drifted; "
            f"expected={expected_schema_digest}, actual={actual_digest}"
        )


def validate_unowned_tables(table_names, *, models=None, rules=UNOWNED_TABLE_RULES):
    owned = {model._meta.db_table for model in models or catalog_models()}
    unowned = set(table_names) - owned
    _equal("unowned database table universe", set(rules), unowned)


def _validate_table_ownership(models):
    counts = Counter(model._meta.db_table for model in models)
    duplicates = sorted(table for table, count in counts.items() if count != 1)
    if duplicates:
        raise TenantDumpCatalogError(
            f"physical tables have multiple model-universe owners: {duplicates}"
        )


def _equal(subject, declared, actual):
    if declared != actual:
        raise TenantDumpCatalogError(
            f"{subject} drifted; missing={sorted(actual - declared)}, "
            f"extra={sorted(declared - actual)}"
        )
